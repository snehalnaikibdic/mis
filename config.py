import os
import time
import logging
import ast
import datetime
from queue import Queue

import pytz
import requests
import copy
import redis
import models
import json
import traceback
from io import BytesIO
import zipfile
from decouple import config
from celery.app import Celery
from fastapi import Depends
from sqlalchemy.orm import Session, joinedload
from celery.schedules import crontab
import config
from aes_encryption_decryption import AESCipher
from cygnet_api import CygnetApi
from database import get_db
from finance_view import AsyncFinancing, AsyncDisbursingFund, AsyncRepayment
from models import OldInvoice, old_invoice_ledger_association, InvoiceEncryptedData, LenderInvoiceAssociation
from registration_view import AsyncEntityRegistration, AsyncInvoiceRegistrationCode, AsyncRegistration
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine, text, desc
from enquiry_view import AsyncValidationServiceWithCode, AsyncValidationServiceWithoutCode

from status_check_view import LedgerStatusCheck, InvoiceStatusCheckWithCode, InvoiceStatusCheckWithoutCode
from utils import days_to_past_date
from decouple import config as dconfig
from gspi_api import get_token, verify_ewb, download, get_status
from routers.send_mail import SUCCESS_BODY_TEXT, CORPORATE_GENERATE_OTP_BODY_TEXT

logger = logging.getLogger(__name__)
DAYS_TO_TRANSFER_INV = config('DAYS_TO_TRANSFER_INV')
IBDIC_RBIH_WEBHOOK_STATUS_URL = config('IBDIC_RBIH_WEBHOOK_STATUS_URL')
IBDIC_RBIH_WEBHOOK_STATUS_API_KEY = config('IBDIC_RBIH_WEBHOOK_STATUS_API_KEY')
HUB_WEBHOOK = dconfig('HUB_WEBHOOK', default=False, cast=bool)
REDIS_PORT = dconfig('REDIS_PORT', 6379)
BASE_URL = config('BASE_URL')
r = redis.Redis(host=dconfig('REDIS_HOST'), port=REDIS_PORT, decode_responses=True)
# ORIGINS = [
#     "http://localhost.tiangolo.com",
#     "https://localhost.tiangolo.com",
#     "http://localhost",
#     "http://localhost:8080",
# ]
ORIGINS = ['*']


# SQLALCHEMY_DATABASE_URL = (f"postgresql://{config('DB_USER')}:{config('DB_PASSWORD')}@{config('DB_HOST')}:{config('DB_PORT')}/"
#                            f"{config('DB_NAME')}")
#
# engine = create_engine(
#     SQLALCHEMY_DATABASE_URL, pool_size=20, max_overflow=0,connect_args={}
# )
# SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# def get_db():
#     logger.info("Getting Db session")
#     db = SessionLocal()
#     try:
#         yield db
#     except Exception as e:
#         logger.error(f"Inside exception {e}")
#     finally:
#         logger.info(f"inside get_db finally gets executed")
#         db.close()


class Config:
    CELERY_BROKER_URL: str = config("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
    CELERY_RESULT_BACKEND: str = config("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/0")


settings = Config()

celery = Celery(
    __name__,
    # 'registration_view',
    broker=Config.CELERY_BROKER_URL,
    backend=Config.CELERY_RESULT_BACKEND,
    # include=['registration_view']
)
celery.autodiscover_tasks()

### run beat :: celery -A config beat --loglevel=info
### run worker :: celery -A config worker -Q celery --loglevel=info


celery.conf.beat_schedule = {
    'transfer_invoice': {
        'task': 'config.run_transfer_invoice_task',
        'schedule': crontab(hour='0', minute='0'),  # Run daily at 12:00 PM
        # 'schedule': crontab(minute="*/1"),  # Run every at minute
    },
    'post_webhook_resp': {
        'task': 'config.hub_webhook_eod_task',
        'schedule': crontab(hour='0', minute='0'),  # Run daily at 12:00 PM
        # 'schedule': crontab(minute="*/1"),  # Run every at minute
    },
    'sftp_task': {
        'task': 'config.process_sftp_file',
        # 'schedule': crontab(hour='0', minute='0'),  # Run daily at 12:00 PM
        'schedule': crontab(minute="*/2"),  # Run every at three minute
    },
    'download_zip_file': {
        'task': 'config.download_zip_file_task',
        'schedule': crontab(minute="*/1"),  # Run every 5 minute
    },
    'status_enquiry': {
        'task': 'config.vayana_status_enquiry_task',
        'schedule': crontab(minute="*/1"),  # Run every 10 minute
    },
    'mis_report': {
        'task': 'config.async_mis_report',
        # 'schedule': crontab(hour='0', minute='0'),  # Run daily at 12:00 PM
        'schedule': crontab(minute="*/15"),  # Run every at three minute
    },
}


# # Define the Celery queues
# celery.conf.update(
#     CELERY_QUEUES=(
#         Queue('invoice', routing_key='invoice1'),
#     ),
# )


def get_celery():
    return celery


# @app.post("/tasks", status_code=201)
# def run_task(payload = Body(...)):
#     task_type = payload["type"]
#     task = create_task.delay(int(task_type))
#     return JSONResponse({"task_id": task.id})

@celery.task
def async_sftp_send_email(subject, email_to, body, body_text=SUCCESS_BODY_TEXT):
    from routers.send_mail import send_email_async
    send_email_async(subject, email_to, body, body_text=body_text)


@celery.task(name="create_task")
def create_task(task_type):
    logger.info(f"task start {1}")
    time.sleep(int(task_type) * 10)
    logger.info(f"task end {1}")
    return True


@celery.task
def async_entity_registr_tasks(db, request_data, merchant_key):
    logger.info(f">>>>>>>>>>>>>>>>>>>> inside task >>>>>>>>>>>>>>>>>>> ")
    AsyncEntityRegistration.create_entity_post(db, request_data, merchant_key)


@celery.task
def webhook_task(request_data, merchant_key, flag):
    db = next(get_db())
    if flag == 'entity_registration':
        AsyncEntityRegistration.create_entity_post(db, request_data, merchant_key, 'async')
    elif flag == "invoice_registration_code":
        AsyncInvoiceRegistrationCode.create_invoice_post(db, request_data, merchant_key, 'async')
    elif flag == "async_invoice_registration":
        AsyncRegistration.create_invoice_post(db, request_data, merchant_key, 'async')
    elif flag == "ledger_status_check":
        LedgerStatusCheck.ledger_status_check_post(db, request_data, merchant_key, 'async')
    elif flag == "invoice_status_check_with_code":
        InvoiceStatusCheckWithCode.invoice_status_check_with_code_post(db, request_data, merchant_key, 'async')
    elif flag == "invoice_status_check_without_code":
        InvoiceStatusCheckWithoutCode.invoice_status_check_without_code_post(db, request_data, merchant_key, 'async')
    elif flag == "validation_service_with_code":
        AsyncValidationServiceWithCode.validation_service_with_code(db, request_data, merchant_key)
    elif flag == "validation_service_without_code":
        AsyncValidationServiceWithoutCode.validation_service_without_code(db, request_data, merchant_key)
    elif flag == "async_bulk_invoice_registration":
        AsyncRegistration.create_bulk_invoice_post(db, request_data, merchant_key, 'registration')
    elif flag == "async_bulk_invoice_registration_without_code_fin":
        AsyncRegistration.create_bulk_invoice_post(db, request_data, merchant_key, 'finance')
    elif flag == "async_bulk_invoice_registration_without_code_fin_disbursement":
        AsyncRegistration.create_bulk_invoice_post(db, request_data, merchant_key, 'finance_disbursement')
    elif flag == "async_bulk_invoice_registration_with_code":
        AsyncInvoiceRegistrationCode.create_bulk_invoice_post(db, request_data, merchant_key, 'registration')
    elif flag == "async_bulk_invoice_registration_with_code_fin":
        AsyncInvoiceRegistrationCode.create_bulk_invoice_post(db, request_data, merchant_key, 'finance')
    elif flag == "async_bulk_registration_with_code_finance_disbursement":
        AsyncInvoiceRegistrationCode.create_bulk_invoice_post(db, request_data, merchant_key, 'finance_disbursement')
    elif flag == 'async_bulk_financing':
        AsyncFinancing.bulk_async_invoice_financing(db, request_data, merchant_key)
    elif flag == 'async_bulk_repayment':
        AsyncRepayment.bulk_async_invoice_repayment(db, request_data, merchant_key)
    elif flag == "async_bulk_disbursement":
        AsyncDisbursingFund.bulk_async_invoice_disbursement(db, request_data, merchant_key, 'async_bulk_disbursement')
    elif flag == "async_bulk_disbursement_repayment":
        AsyncDisbursingFund.bulk_async_invoice_disbursement(db, request_data, merchant_key,
                                                            'async_bulk_disbursement_repayment')
    elif flag == 'async_financing':
        AsyncFinancing.async_invoice_financing(db, request_data, merchant_key)
    elif flag == 'async_disbursement':
        AsyncDisbursingFund.async_invoice_disbursing(db, request_data, merchant_key)
    elif flag == 'async_repayment':
        AsyncRepayment.async_invoice_repayment(db, request_data, merchant_key)
    elif flag == "async_bulk_validation_service_without_code":
        AsyncValidationServiceWithoutCode.bulk_validation_service_without_code(db, request_data, merchant_key,
                                                                               'validation_without_code')
    elif flag == "async_bulk_validation_service_with_code":
        AsyncValidationServiceWithCode.bulk_validation_service_with_code(db, request_data, merchant_key,
                                                                         'validation_with_code')

    # logger.info(f"i9nside task")


@celery.task
def run_transfer_invoice_task():
    logger.info("Starting Task Move Invoices")
    lock_expire = 300
    lock_key = 'move_invoice_data'
    acquire_lock = lambda: r.set(lock_key, '1', nx=True, ex=lock_expire)
    release_lock = lambda: r.delete(lock_key)
    if acquire_lock():
        try:
            transfer_invoice_to_old_invoice_table()
        except Exception as e:
            logger.error("Exception while acquiring lock for move_invoice_to_old_table {}".format(str(e)))
            logger.error(traceback.format_exc())
        finally:
            release_lock()
    else:
        logger.info("Other task of move invoices is running, skipping")
    logger.info("End Task Move invoices")


@celery.task
def hub_webhook_eod_task():
    logger.info("Starting Task Move EOD Webhook data")
    lock_expire = 300
    lock_key = 'hub_webhook_eod'
    acquire_lock = lambda: r.set(lock_key, '1', nx=True, ex=lock_expire)
    release_lock = lambda: r.delete(lock_key)
    if acquire_lock():
        try:
            post_async_hub_resp_to_rbi()
        except Exception as e:
            logger.error("Exception while acquiring lock for post_async_webhook_data_for_hub {}".format(str(e)))
            logger.error(traceback.format_exc())
        finally:
            release_lock()
    else:
        logger.info("Other task of post_async_webhook_data_for_hub is running, skipping")
    logger.info("End Task post_async_webhook_data_for_hub")


@celery.task
def process_sftp_file():
    logger.info("Starting Task async_sftp_func_call")
    lock_expire = 300
    lock_key = 'sftp_call'
    acquire_lock = lambda: r.set(lock_key, '1', nx=True, ex=lock_expire)
    release_lock = lambda: r.delete(lock_key)
    if acquire_lock():
        try:
            async_sftp_task()
        except Exception as e:
            logger.error("Exception while acquiring lock for async_sftp_func_call {}".format(str(e)))
            logger.error(traceback.format_exc())
        finally:
            release_lock()
    else:
        logger.info("Other task of async_sftp_func_call is running, skipping")
    logger.info("End Task async_sftp_func_call")


@celery.task
def download_zip_file_task():
    logger.info("Starting Task download_zip_file_vayana")
    lock_expire = 300
    lock_key = 'download_file_vya'
    acquire_lock = lambda: r.set(lock_key, '1', nx=True, ex=lock_expire)
    release_lock = lambda: r.delete(lock_key)
    if acquire_lock():
        try:
            download_zip_file_vayana()
        except Exception as e:
            logger.error("Exception while acquiring lock for download_zip_file_vayana {}".format(str(e)))
            logger.error(traceback.format_exc())
        finally:
            release_lock()
    else:
        logger.info("Other task of download_zip_file_vayana is running, skipping")
    logger.info("End Task download_zip_file_vayana")


@celery.task
def vayana_status_enquiry_task():
    logger.info("Starting Task vayna_status_enquiry")
    lock_expire = 300
    lock_key = 'vya_status_enquiry'
    acquire_lock = lambda: r.set(lock_key, '1', nx=True, ex=lock_expire)
    release_lock = lambda: r.delete(lock_key)
    if acquire_lock():
        try:
            vayana_status_enquiry()
        except Exception as e:
            logger.error("Exception while acquiring lock for vayna_status_enquiry {}".format(str(e)))
            logger.error(traceback.format_exc())
        finally:
            release_lock()
            logger.info("inside finally :: release lock")
    else:
        logger.info("Other task of vayna_status_enquiry is running, skipping")
    logger.info("End Task vayna_status_enquiry")


@celery.task
def async_mis_report():
    logger.info("Starting Task prepare_mis_report")
    lock_expire = 300
    lock_key = 'prep_mis_report'
    acquire_lock = lambda: r.set(lock_key, '1', nx=True, ex=lock_expire)
    release_lock = lambda: r.delete(lock_key)
    if acquire_lock():
        try:
            prepare_mis_report()
        except Exception as e:
            logger.error("Exception while acquiring lock for prepare_mis_report {}".format(str(e)))
            logger.error(traceback.format_exc())
        finally:
            release_lock()
    else:
        logger.info("Other task of prepare_mis_report is running, skipping")
    logger.info("End Task prepare_mis_report")


def transfer_invoice_to_old_invoice_table():
    logger.info(f"inside tasks transfer_invoice_to_old_invoice_table ")
    db = next(get_db())
    try:
        days = int(DAYS_TO_TRANSFER_INV) or 365

        delta_date = days_to_past_date(days)

        inv_objs = db.query(
            models.Invoice
        ).filter(
            models.Invoice.updated_at <= delta_date
        ).all()

        for inv_obj in inv_objs:
            old_inv_obj = models.OldInvoice(
                invoice_no=inv_obj.invoice_no,
                invoice_date=inv_obj.invoice_date,
                invoice_due_date=inv_obj.invoice_due_date,
                invoice_amt=inv_obj.invoice_amt,
                invoice_hash=inv_obj.invoice_hash,
                funded_amt=inv_obj.funded_amt,
                gst_status=bool(inv_obj.gst_status),
                fund_status=inv_obj.fund_status,
                financial_year=inv_obj.financial_year,
                status=inv_obj.status,
                extra_data=inv_obj.extra_data,
                is_active=inv_obj.is_active,
                created_at=inv_obj.created_at,
                updated_at=inv_obj.updated_at
            )
            db.add(old_inv_obj)
            db.commit()
            db.refresh(old_inv_obj)

            for led_obj in inv_obj.ledger:
                # create old_invoice_ledger_association
                old_inv_obj.ledger.append(led_obj)
                db.commit()
                db.refresh(old_inv_obj)

            # delink inv, link old inv
            inv_enc_data_obj = db.query(
                models.InvoiceEncryptedData
            ).filter(
                models.InvoiceEncryptedData.invoice_id == inv_obj.id
            ).first()

            if inv_enc_data_obj:
                inv_enc_data_obj.invoice_id = None
                inv_enc_data_obj.old_invoice_id = old_inv_obj.id
                db.commit()
                db.refresh(inv_enc_data_obj)

            try:
                dis_hist_obj = db.query(
                    models.DisbursedHistory
                ).filter(
                    models.DisbursedHistory.id == inv_obj.id
                ).order_by(
                    desc(models.DisbursedHistory.id)
                ).first()
                if dis_hist_obj:
                    dis_hist_obj.invoice_id = None
                    dis_hist_obj.old_invoice_id = old_inv_obj.id
                    db.commit()
                    db.refresh(dis_hist_obj)

                repay_hist_obj = db.query(
                    models.RepaymentHistory
                ).filter(
                    models.RepaymentHistory.id == inv_obj.id
                ).first()
                if repay_hist_obj:
                    repay_hist_obj.invoice_id = None
                    repay_hist_obj.old_invoice_id = old_inv_obj.id
                    db.commit()
                    db.refresh(repay_hist_obj)

                # delink inv, link old inv to lenInvAss
                len_inv_ass_obj = db.query(
                    models.LenderInvoiceAssociation
                ).filter(
                    models.LenderInvoiceAssociation.invoice_id == inv_obj.id
                ).first()
                if len_inv_ass_obj:
                    len_inv_ass_obj.invoice_id = None
                    len_inv_ass_obj.old_invoice_id = old_inv_obj.id
                    db.commit()
                    db.refresh(len_inv_ass_obj)
            except Exception as e:
                logger.error(f"Error transfer_invoice_to_old_invoice_table LenderInvoiceAssociation")
                pass

            # after moved, delete inv obj from invoice table
            db.delete(inv_obj)
            db.commit()
            # db.refresh(inv_obj)

        logger.info(f"Successfully task transfer_invoice_to_old_invoice_table completed")
    except Exception as e:
        logger.error(f"Error transfer_invoice_to_old_invoice_table. {traceback.format_exc()}")
        pass


def post_async_hub_resp_to_rbi():
    logger.info(f"inside tasks : post_async_hub_resp_to_rbi ")
    db = next(get_db())
    try:
        payload = []
        if HUB_WEBHOOK:
            asia_kolkata = pytz.timezone('Asia/Kolkata')
            today_date = datetime.datetime.now(asia_kolkata).strftime("%Y-%m-%d")

            query = """
                select
                    jsonb_agg(
                        jsonb_build_object(
                            'txncode', ppr.extra_data->>'txnCode'::text,
                            'correlationId', ppr.extra_data->>'correlationId'::text,
                            'status', COALESCE(ppr.extra_data->>'webhook_status'::text, '')
                            )
                    ) as webhook_data
                from
                    post_processing_request ppr 
                where
                    ppr.extra_data->>'txnCode' is not null 
                    and 
                    ppr.updated_at::date = (:parsed_today_date)::date
            ;    
            """
            post_proc_objs = db.execute(text(query), [{'parsed_today_date': today_date}]).first()
            logger.info(f"webhook resp status...:: {post_proc_objs}...{'query'}")
            payload = {
                "payload": post_proc_objs.webhook_data if post_proc_objs and post_proc_objs.webhook_data else []
            }

            logger.info(f"sending webhook to rbih, payload:: {payload}")
            rbih_url = IBDIC_RBIH_WEBHOOK_STATUS_URL
            logger.info(f"rbis_url.......:: {rbih_url}")
            header = {
                'Authorization': 'apikey',
                'Content-Type': 'application/json',
                'apikey': IBDIC_RBIH_WEBHOOK_STATUS_API_KEY
            }
            resp = requests.post(rbih_url, data=json.dumps(payload), timeout=120, headers=header)
            logger.info(f"Successfully task post_async_hub_resp_to_rbi completed {resp.status_code}")
            # return payload
    except Exception as e:
        logger.error(f"Error post_async_hub_resp_to_rbi. {traceback.format_exc()}")
        pass


@celery.task
def post_webhook_data(merchant_key, webhook_data):
    import utils

    db = next(get_db())
    full_webhook_url = utils.get_webhook_url(db, merchant_key)
    logger.info(f"merchant full webhook url >>>>>>>>> {full_webhook_url}")

    try:
        request_id = webhook_data.get('requestId')
        post_pro_req_obj = (
            db.query(
                models.PostProcessingRequest
            ).filter(
                models.PostProcessingRequest.request_extra_data.contains({"requestId": request_id})
            ).first()
        )
        logger.info(f"post_pro_req_obj object :: {post_pro_req_obj.id}")

        try:
            resp = requests.post(full_webhook_url, data=json.dumps(webhook_data),
                                 headers={"content-type": "application/json"}, timeout=120)
            logger.info(f"Webhook url response {resp.status_code} :: data {resp.content}")
            if int(resp.status_code) == 200:
                if post_pro_req_obj:
                    logger.info(f"PostProcessingRequest object :: {post_pro_req_obj.id}")
                    if post_pro_req_obj.extra_data:
                        data = copy.deepcopy(post_pro_req_obj.extra_data)
                        data.update({
                            "webhook_status": 'Sent'
                        })
                    else:
                        data = {
                            "webhook_status": 'Sent'
                        }
                    post_pro_req_obj.extra_data = data
                    db.commit()
                    db.refresh(post_pro_req_obj)
            else:
                if post_pro_req_obj:
                    logger.info(f"PostProcessingRequest object :: {post_pro_req_obj.id}")
                    if post_pro_req_obj.extra_data:
                        data = copy.deepcopy(post_pro_req_obj.extra_data)
                        data.update({
                            "webhook_status": 'Failed'
                        })
                    else:
                        data = {
                            "webhook_status": 'Failed'
                        }
                    post_pro_req_obj.extra_data = data
                    db.commit()
                    db.refresh(post_pro_req_obj)
        except Exception as e:
            if post_pro_req_obj:
                logger.info(f"PostProcessingRequest object :: {post_pro_req_obj.id}")
                if post_pro_req_obj.extra_data:
                    data = copy.deepcopy(post_pro_req_obj.extra_data)
                    data.update({
                        "webhook_status": 'Failed'
                    })
                else:
                    data = {
                        "webhook_status": 'Failed'
                    }
                post_pro_req_obj.extra_data = data
                db.commit()
                db.refresh(post_pro_req_obj)
    except Exception as e:
        logger.exception(f"Exception post_webhook_data")


def async_sftp_task():
    logger.info(f"inside tasks : async_sftp_task ")
    from routers.sftp import fetch_upload_file_to_sftp
    fetch_upload_file_to_sftp()


@celery.task
def async_sftp_idp_process(merchant_dir):
    from routers.sftp import process_sftp_idp
    process_sftp_idp(merchant_dir)


def prepare_mis_report():
    logger.info(f"inside tasks : async_mis_report ")
    from routers.mis_report import MisReport
    MisReport().create_all_materialized_view()
    logger.info(f"async_mis_report :: MisReport...Refreshed...")


@celery.task
def bulk_post_webhook_data(merchant_key, webhook_data):
    import utils

    db = next(get_db())
    full_webhook_url = utils.get_webhook_url(db, merchant_key)
    logger.info(f"merchant full webhook url >>>>>>>>> {full_webhook_url}")

    try:
        request_id = webhook_data.get('requestId')

        req_obj = db.query(
            models.BulkAPIRequestLog
        ).filter(
            models.BulkAPIRequestLog.invoice_id == request_id
        ).first()

        logger.info(f"post_pro_req_obj object :: {req_obj.id}")

        try:
            resp = requests.post(full_webhook_url, data=webhook_data, timeout=120)
            if resp.status_code == 200:
                if req_obj:
                    logger.info(f"PostProcessingRequest object :: {req_obj.id}")
                    if req_obj.extra_data:
                        data = copy.deepcopy(req_obj.extra_data)
                        data.update({
                            "webhook_status": 'Sent'
                        })
                    else:
                        data = {
                            "webhook_status": 'Sent'
                        }
                    req_obj.extra_data = data
                    db.commit()
                    db.refresh(req_obj)
            else:
                if req_obj:
                    logger.info(f"PostProcessingRequest object :: {req_obj.id}")
                    if req_obj.extra_data:
                        data = copy.deepcopy(req_obj.extra_data)
                        data.update({
                            "webhook_status": 'Failed'
                        })
                    else:
                        data = {
                            "webhook_status": 'Failed'
                        }
                    req_obj.extra_data = data
                    db.commit()
                    db.refresh(req_obj)
        except Exception as e:
            if req_obj:
                logger.info(f"PostProcessingRequest object :: {req_obj.id}")
                if req_obj.extra_data:
                    data = copy.deepcopy(req_obj.extra_data)
                    data.update({
                        "webhook_status": 'Failed'
                    })
                else:
                    data = {
                        "webhook_status": 'Failed'
                    }
                req_obj.extra_data = data
                db.commit()
                db.refresh(req_obj)
    except Exception as e:
        logger.exception(f"Exception post_webhook_data")


def create_auth_org(gsp_user_details):
    # ALL REQUEST PACKET WILL COME FROM TABLE NEED TO INTEGRATE HERE
    cache_token_key = f"token@{gsp_user_details.username}"
    cache_org_id_key = f"org_id@{gsp_user_details.username}"
    aes_encryption = AESCipher()
    secret_key = gsp_user_details.gstin + gsp_user_details.mobile_number
    decrypted_password = aes_encryption.gsp_password_decryption(gsp_user_details.password, secret_key)
    logger.info(f" ############# getting decrypted_password {decrypted_password} #############")
    request_data = {
        "handle": gsp_user_details.username,
        "password": decrypted_password,
        "handleType": "email",
        "tokenDurationInMins": 360
    }
    gsp_response, response_data = get_token(request_data, 'vayana')
    if gsp_response.status_code != 200:
        return gsp_response

    auth_token = str(response_data.get('data').get('token'))
    org_id = str(response_data.get('data').get('associatedOrgs')[0].get('organisation').get('id'))
    r.set(cache_token_key, auth_token)
    r.set(cache_org_id_key, org_id)
    r.expire(cache_token_key, 21600)
    r.expire(cache_org_id_key, 21600)

    gsp_response, response_data


def update_ewb_invoice(db, ewb_no, ewb_status, vayana_task_history_obj=None, file_data=None):
    logger.info(f" ############# inside update ewb invoice ################")
    # ewb_obj = (
    #     db.query(
    #         models.Invoice
    #     ).filter(
    #         models.Invoice.extra_data.contains({"ewb_no": ewb_no})
    #
    #     ).first()
    #
    # )

    ewb_obj = (
        db.query(models.Invoice)
        .filter(
            models.Invoice.extra_data.contains({"ewb_no": ewb_no}),
        )
        .order_by(desc(
            models.Invoice.id
        ))
        .first()
    )
    logger.info(f" ############# getting ewb obj {ewb_obj} ewb_status {ewb_status} and {file_data} ################")
    if ewb_obj:
        if ewb_status == "1":
            buyer_gst = ewb_obj.extra_data.get('buyer_gst')
            seller_gst = ewb_obj.extra_data.get('seller_gst')
            invoice_date = ewb_obj.invoice_date
            ewb_obj_invoice_date = file_data.get('docDate')
            invoice_no = ewb_obj.invoice_no
            file_seller_gst = file_data.get('fromGstin')
            file_buyer_gst = file_data.get('toGstin')
            ewb_invoice_no = file_data.get('docNo')
            invoice_formatted_date = invoice_date.strftime("%d/%m/%Y")

            if (invoice_formatted_date == ewb_obj_invoice_date and invoice_no == ewb_invoice_no and file_seller_gst ==
                    seller_gst) and buyer_gst == file_buyer_gst:
                ewb_obj.gst_status = True
            db.commit()
            db.refresh(ewb_obj)

        vayana_task_history_obj.download_status = 'completed'
        db.commit()
        db.refresh(vayana_task_history_obj)


@celery.task
def get_gsp_detail(seller_gst, buyer_gst, ewb_no):
    logger.info(f"$$$$$$$$$$ getting inside get gsp detail {seller_gst} {buyer_gst} {ewb_no} $$$$$$$$$$$$$$$$$$$$$$$")
    db = next(get_db())

    lower_gsp_priority = config('LOWER_GSP_PRIORITY')

    gsp_user_details = (
        db.query(
            models.GSPUserDetails
        ).filter(
            models.GSPUserDetails.gstin == seller_gst
        ).all()
    )
    if not gsp_user_details:
        gsp_user_details = (
            db.query(
                models.GSPUserDetails
            ).filter(
                models.GSPUserDetails.gstin == buyer_gst
            ).all()
        )
    if len(gsp_user_details) > 1:
        gsp_user_details = gsp_user_details.filter(models.GSPUserDetails.gsp == lower_gsp_priority).first()
    else:
        gsp_user_details = gsp_user_details.first()

    logger.info(f" >>>>>>>>>>>>>>>>>>> getting gsp user detail {gsp_user_details} >>>>>>>>>>>>>>>>>>>>>>")
    if gsp_user_details:
        if gsp_user_details.gsp.lower() == 'vayana':
            logger.info(f" $$$$$$$$$$$$$$$$$ getting inside if gsp user vayana $$$$$$$$$$$$$$$$$$$")
            vayana_verify_ewb_task(gsp_user_details.gstin, ewb_no)
        else:
            cygnet_ewaybill_token = gsp_user_details.extra_data.get('cygnet_ewaybill_token')
            cygnet_ewaybill_sek = gsp_user_details.extra_data.get('cygnet_ewaybill_sek')
            if cygnet_ewaybill_token and cygnet_ewaybill_sek:
                logger.info(f" >>>>>> getting inside cygnet if cygnet sek found >>>>>> ")
                get_ewaybill_bulk_request = {
                    "data": {
                        "ewbNo": ewb_no,
                        "gstin": gsp_user_details.gstin,
                        "authtoken": cygnet_ewaybill_token,
                        "sek": cygnet_ewaybill_sek
                    }
                }
                cygnet_api = CygnetApi()
                return_response = cygnet_api.cygnet_get_ewb_details(get_ewaybill_bulk_request)
                logger.info(f" >>>>>>>>>> getting response {return_response} >>>>>>>>>>>>>>>>> ")

                if return_response.get('data'):
                    response_data = json.loads(return_response.get('data'))

                    ewb_obj = (
                        db.query(models.Invoice)
                        .filter(
                            models.Invoice.extra_data.contains({"ewb_no": ewb_no}),
                        )
                        .order_by(desc(
                            models.Invoice.id
                        ))
                        .first()
                    )
                    logger.info(f" >>>>>> getting inside cygnet if cygnet sek found {ewb_obj} >>>>>> ")
                    if ewb_obj:
                        invoice_no = ewb_obj.invoice_no
                        buyer_gst = ewb_obj.extra_data.get('buyer_gst')
                        seller_gst = ewb_obj.extra_data.get('seller_gst')
                        invoice_date = ewb_obj.invoice_date
                        invoice_formatted_date = invoice_date.strftime("%d/%m/%Y")

                        ewb_obj_invoice_date = response_data.get('docDate')
                        file_seller_gst = response_data.get('fromGstin')
                        file_buyer_gst = response_data.get('toGstin')
                        ewb_invoice_no = response_data.get('docNo')
                        if (invoice_formatted_date == ewb_obj_invoice_date and invoice_no == ewb_invoice_no and file_seller_gst ==
                                seller_gst) and buyer_gst == file_buyer_gst:
                        # if response_data.get('docNo') == ewb_obj.invoice_no:
                            ewb_obj.gst_status = True
                            db.commit()
                            db.refresh(ewb_obj)

    else:
        logger.info(f" >>>>>>>>>>>>>>>>>>> getting gsp user detail else condition {gsp_user_details} "
                    f">>>>>>>>>>>>>>>>>>>>>>")
        ewb_obj = (
            db.query(
                models.Invoice
            ).filter(
                models.Invoice.extra_data.contains({"ewb_no": ewb_no})
            ).first()
        )
        logger.info(f" ############# getting ewb obj {ewb_obj} ################")
        if ewb_obj:
            ewb_obj.gst_status = False
            db.commit()
            db.refresh(ewb_obj)


def vayana_verify_ewb_task(seller_gst, ewb_no):
    try:
        logger.info(f"$$$$$$$$$$$$$$$$$$$$ getting inside vayana verify ewb task $$$$$$$$$$$$$$$$$$$$")
        db = next(get_db())

        verify_request_data = {
            "payload": [
                {
                    "ewbNumber": ewb_no
                }
            ],
            "meta": {
                "json": "Y"
            }
        }

        logger.info(
            f"$$$$$$$$$$$$$$$$$$$$ getting inside verify_request_data {verify_request_data} $$$$$$$$$$$$$$$$$$$$")

        gsp_user_details = (
            db.query(
                models.GSPUserDetails
            ).filter(
                models.GSPUserDetails.gstin == seller_gst
            ).first()
        )
        logger.info(f"$$$$$$$$$$$$$$$$$$$$ getting gsp detail {gsp_user_details.username} $$$$$$$$$$$$$$$$$$$$")
        if gsp_user_details:
            cache_token_key = f"token@{gsp_user_details.username}"
            cache_org_id_key = f"org_id@{gsp_user_details.username}"
            auth_token = r.get(cache_token_key)
            org_id = r.get(cache_org_id_key)

            if not auth_token:
                gsp_response, response_data = create_auth_org(gsp_user_details)
                if gsp_response.status_code != 200:
                    return response_data

                auth_token = str(response_data.get('data').get('token'))
                org_id = str(response_data.get('data').get('associatedOrgs')[0].get('organisation').get('id'))

            aes_encryption = AESCipher()
            secret_key = gsp_user_details.gstin + gsp_user_details.mobile_number
            decrypted_password = aes_encryption.gsp_password_decryption(gsp_user_details.password, secret_key)
            logger.info(f" ############# getting decrypted_password {decrypted_password} #############")
            aes_response = aes_encryption.vayana_encryption(decrypted_password)

            logger.info(f"$$$$$$$$$$$$$$$$$$$$ getting aes_response {aes_response} $$$$$$$$$$$$$$$$$$$$")
            encrypted_rek = aes_response.get('X-FLYNN-S-REK')
            encrypted_password = aes_response.get('X-FLYNN-S-DATA')
            verify_gsp_response, gsp_response_data = verify_ewb(
                verify_request_data,
                'vayana',
                org_id,
                auth_token,
                gsp_user_details,
                encrypted_rek,
                encrypted_password
            )
            if verify_gsp_response.status_code != 200:
                return gsp_response_data

            status_response, status_response_data = get_status(
                'vayana',
                org_id,
                auth_token,
                gsp_response_data.get('data').get('task-id'),
                gsp_user_details,
                encrypted_rek,
                encrypted_password
            )

            vayana_task_history = db.query(
                models.VayanaTaskHistory
            ).filter(
                models.VayanaTaskHistory.task_id == gsp_response_data.get('data').get('task-id'),
                models.VayanaTaskHistory.user_id == gsp_user_details.username
            ).first()

            if not vayana_task_history:
                task_history_obj = models.VayanaTaskHistory(
                    task_id=gsp_response_data.get('data').get('task-id'),
                    task_id_status=status_response_data.get('data').get('status').lower(),
                    user_id=gsp_user_details.username
                )
                db.add(task_history_obj)
                db.commit()
                db.refresh(task_history_obj)
    except Exception as e:
        logger.info(f"getting error while verify ewb no {e}")


# PERIODIC TASK
def vayana_status_enquiry():
    try:
        db = next(get_db())

        vayana_task_history = db.query(
            models.VayanaTaskHistory
        ).filter(
            models.VayanaTaskHistory.task_id_status != 'completed'
        ).all()

        for vayana_task_history_data in vayana_task_history:

            gsp_user_details = (
                db.query(
                    models.GSPUserDetails
                ).filter(
                    models.GSPUserDetails.username == vayana_task_history_data.user_id
                ).first()
            )

            cache_token_key = f"token@{vayana_task_history_data.user_id}"
            cache_org_id_key = f"org_id@{vayana_task_history_data.user_id}"
            auth_token = r.get(cache_token_key)
            org_id = r.get(cache_org_id_key)
            if not auth_token:
                gsp_response, response_data = create_auth_org(gsp_user_details)
                if gsp_response.status_code != 200:
                    return response_data

                auth_token = str(response_data.get('data').get('token'))
                org_id = str(response_data.get('data').get('associatedOrgs')[0].get('organisation').get('id'))

            aes_encryption = AESCipher()
            secret_key = gsp_user_details.gstin + gsp_user_details.mobile_number
            decrypted_password = aes_encryption.gsp_password_decryption(gsp_user_details.password, secret_key)
            logger.info(f" ############# getting decrypted_password {decrypted_password} #############")
            aes_response = aes_encryption.vayana_encryption(decrypted_password)
            encrypted_rek = aes_response.get('X-FLYNN-S-REK')
            encrypted_password = aes_response.get('X-FLYNN-S-DATA')

            status_response, status_response_data = get_status(
                'vayana',
                org_id,
                auth_token,
                vayana_task_history_data.task_id,
                gsp_user_details,
                encrypted_rek,
                encrypted_password

            )
            if status_response.status_code != 200:
                return status_response_data

            vayana_task_history = db.query(
                models.VayanaTaskHistory
            ).filter(
                models.VayanaTaskHistory.task_id == vayana_task_history_data.task_id,
                models.VayanaTaskHistory.user_id == vayana_task_history_data.user_id
            ).first()
            if vayana_task_history:
                vayana_task_history.task_id_status = status_response_data.get('data').get('status').lower()
                db.commit()
                db.refresh(vayana_task_history)
    except Exception as e:
        logger.info(f"getting error while status check {e}")


# PERIODIC TASK
def download_zip_file_vayana():
    try:
        db = next(get_db())
        vayana_task_history = db.query(
            models.VayanaTaskHistory
        ).filter(
            models.VayanaTaskHistory.task_id_status == 'completed',
            models.VayanaTaskHistory.download_status.is_(None)
        ).all()
        logger.info(f" ############### getting download history {vayana_task_history} ##########")
        for vayana_task_history_data in vayana_task_history:
            gsp_user_details = (
                db.query(
                    models.GSPUserDetails
                ).filter(
                    models.GSPUserDetails.username == vayana_task_history_data.user_id
                ).first()
            )

            logger.info(
                f" ############### getting download history {vayana_task_history_data.download_status} ##########")
            cache_token_key = f"token@{vayana_task_history_data.user_id}"
            cache_org_id_key = f"org_id@{vayana_task_history_data.user_id}"
            auth_token = r.get(cache_token_key)
            org_id = r.get(cache_org_id_key)
            if not auth_token:

                gsp_response, response_data = create_auth_org(gsp_user_details)
                if gsp_response.status_code != 200:
                    return response_data

                auth_token = str(response_data.get('data').get('token'))
                org_id = str(response_data.get('data').get('associatedOrgs')[0].get('organisation').get('id'))

            download_response = download(
                'vayana',
                org_id,
                auth_token,
                vayana_task_history_data.task_id
            )

            logger.info(f" ##############getting download api response {download_response} status code"
                        f" {download_response.status_code} ###################")
            if download_response.status_code == 200:

                # Read the content of the zip file
                zip_data = BytesIO(download_response.content)

                logger.info(f"getting zip data {zip_data}")

                # Open the zip file
                with zipfile.ZipFile(zip_data, 'r') as zip_ref:
                    extracted_files = {name: zip_ref.read(name) for name in zip_ref.namelist()}

                # Now you can access the extracted files in memory
                for file_name, file_content in extracted_files.items():
                    file_data = json.loads(file_content)
                    logger.info(f" $$$$$$$$$$$$$$$$ getting file data {file_data} ###############")
                    if file_name == "result.json":
                        logger.info(f" >>>>>>>>>>> getting inside file name result >>>>>>>>>>>")
                        for result_json in file_data.get('data'):
                            ewb_status = result_json.get('status')
                            ewb_no = result_json.get('additionalInfo').get('key').get('ewb-number')
                            ewb_obj = (
                                db.query(
                                    models.Invoice
                                ).filter(
                                    models.Invoice.extra_data.contains({"ewb_no": ewb_no})
                                ).first()
                            )
                            logger.info(f" ########## getting ewb no {ewb_obj.id} #########")
                            # if ewb_status == '1':
                            #     logger.info(f" ########## getting if ewb status is true #########")
                            #     ewb_obj.gst_status = True
                            #     db.commit()
                            #     db.refresh(ewb_obj)
                            # else:
                            #     logger.info(f" ####### getting inside else ###########")
                                # update_ewb_invoice(db, ewb_no, ewb_status, vayana_task_history_data)

                            vayana_task_history_data.download_status = 'completed'
                            db.commit()
                            db.refresh(vayana_task_history_data)
                    else:
                        logger.info(f" >>>>>>>>>>> getting inside else if file name not result {file_name} >>>>>>>>>>>")
                        ewb_status = "1"
                        ewb_no = str(file_data.get('ewbNo'))
                        update_ewb_invoice(db, ewb_no, ewb_status, vayana_task_history_data, file_data)
            else:
                return download_response.json()
    except Exception as e:
        logger.error(f"getting error while download api {e}")
