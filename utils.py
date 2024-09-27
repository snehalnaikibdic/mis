import logging
import hashlib
import os
import re
import json
import io
import base64
import redis
import ast
import pytz
import math
import csv
import datetime as dt
import pandas as pd
import numpy as np
import secrets
import string
import time
import random
import uuid

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.asymmetric import padding as asymmetric_padding

from cryptography.hazmat.primitives.asymmetric import rsa
from base64 import urlsafe_b64encode, urlsafe_b64decode

from fastapi import HTTPException, Response
from decouple import config as dconfig
from datetime import datetime, timedelta

from errors import ErrorCodes
import models
from models import MerchantDetails, PostProcessingRequest, Hub
from sqlalchemy import desc, text
from random import randint

from fastapi import Depends
from sqlalchemy.orm import Session
from database import get_db

# logging.config.fileConfig('logging.conf', disable_existing_loggers=False)
# get root logger
logger = logging.getLogger(__name__)
r = redis.Redis(host=dconfig('REDIS_HOST'), port=6379, decode_responses=True)
asia_kolkata = pytz.timezone('Asia/Kolkata')


# Function to generate a random string
def get_random_string(chars=32):
    return os.urandom(chars).hex()


class InvoiceStatus:
    FUNDED = 'funded'
    NON_FUNDED = 'non_funded'
    PARTIAL_DISBURSED = 'partial_disbursed'
    FULL_DISBURSED = 'full_disbursed'
    PARTIAL_PAID = 'partial_paid'
    FULL_PAID = 'full_paid'
    PARTIAL_REPAID = 'partial_repaid'
    REPAID = 'repaid'
    PARTIAL_FUNDED = 'partial_funded'


def create_signature(data, secret_key):
    logger.info(f"getting signature data >>>>>>>>>>>>>>>> {data}")
    logger.info(f"getting merchant secret key >>>>>>>>>>>>>>>> {secret_key}")
    params = json.dumps(data, separators=(',', ':'))
    logger.info(f"getting seperator data >>>>>>>>>>>>>> {params}")
    final_string = '%s%s' % (params, secret_key)
    signature = hashlib.sha256(final_string.encode()).hexdigest()
    logger.info(f"getting signature {signature}")
    # add this signature to the request body and post
    return signature


def create_ledger_hash(data, secret_key):
    final_string = '%s%s' % (data, secret_key)
    signature = hashlib.sha256(final_string.encode()).hexdigest()
    logger.info(f"getting signature {signature}")
    # add this signature to the request body and post
    return signature


def create_response_hash(db, data, merchant_key):
    if 'signature' in data:
        data.pop('signature')
    logger.info(f"getting signature data {data}")

    merchant_details = db.query(MerchantDetails).filter(MerchantDetails.merchant_key == merchant_key).first()
    final_string = '%s%s' % (data, merchant_details.merchant_secret)
    signature = hashlib.sha256(final_string.encode()).hexdigest()
    logger.info(f"getting signature {signature}")
    # add this signature to the request body and post
    return signature


def validate_signature(db, request_data, merchant_key):
    # duplicates_exist = are_duplicates_exist(request_data.get('ledgerData'))
    # logger.info(f"getting duplicates exist >>>>>>>>>>>>>>>>>> {duplicates_exist}")
    # if not duplicates_exist:
    #     duplicates_exist = check_for_duplicate_values(request_data.get('ledgerData'))
    #     if not duplicates_exist:
    merchant_details = db.query(MerchantDetails).filter(MerchantDetails.merchant_key == merchant_key).first()
    request_data_copy = request_data.copy()
    request_data.pop('signature', '')
    logger.info(f"getting requests data >>>>>>>>>>>>>>>> {request_data}")

    if merchant_details:
        created_signature = create_signature(request_data, merchant_details.merchant_secret)
        logger.info(f"created signature @@@@@@@@@@@@@@@@@@ {created_signature}")
        logger.info(f"requested signature @@@@@@@@@@@@@@@@@@ {request_data_copy.get('signature')}")
        if request_data_copy.get('signature') == created_signature:
            return {"requestId": request_data.get('requestId'),
                    **ErrorCodes.get_error_response(200), "merchant_details": merchant_details
                    }
        else:
            # return {"requestId": request_data.get('requestId'), **ErrorCodes.get_error_response(1001),
            # "merchant_details": merchant_details}
            return {"requestId": request_data.get('requestId'), **ErrorCodes.get_error_response(1001)}
    return {"requestId": request_data.get('requestId'), **ErrorCodes.get_error_response(1002),
            "merchant_details": merchant_details}
    #     else:
    #         return {**ErrorCodes.get_error_response(1015)}
    # else:
    #     return {**ErrorCodes.get_error_response(1014)}


def generate_key_secret(length: int):
    return secrets.token_urlsafe(length)


def are_duplicates_exist(json_list):
    # Set to store unique JSON strings
    unique_json_strings = set()

    for json_obj in json_list:
        # Convert JSON object to string
        json_string = json.dumps(json_obj, sort_keys=True)

        # Check if the JSON string is already in the set
        if json_string in unique_json_strings:
            return True  # Duplicate found

        # Add the JSON string to the set
        unique_json_strings.add(json_string)

    return False  # No duplicates found


def get_financial_year():
    import datetime
    today = datetime.date.today()

    # Financial year starts on April 1st
    if today.month >= 4:
        start_year = today.year
        end_year = today.year + 1
    else:
        start_year = today.year - 1
        end_year = today.year

    return f"{start_year}-{end_year}"


def check_for_duplicate_values(json_list):
    seller_id_no = ""
    if json_list.get('sellerIdentifierData'):
        for seller_data in json_list.get('sellerIdentifierData'):
            if seller_data.get('sellerIdType').lower() == "gstin":
                seller_id_no = seller_data.get('sellerIdNo')

    if json_list.get('buyerIdentifierData'):
        for buyer_data in json_list.get('buyerIdentifierData'):
            if buyer_data.get('buyerIdType').lower() == "gstin":
                buyer_id_no = buyer_data.get('buyerIdNo')
                if seller_id_no == buyer_id_no:
                    return True

    return False


# def check_for_entity_gst_duplicate_values(request_data):
#     for entity_register_data in request_data.get('entityRegisterData'):
#         gst_values = []
#         gst_count = 0
#         for entity_identifier_data in entity_register_data.get('entityIdentifierData'):
#             if entity_identifier_data.get('entityIdType').lower() == "gstin":
#                 gst_count = gst_count + 1
#                 if gst_count > 2:
#                     return True
#                 if entity_identifier_data.get('entityIdNo') in gst_values:
#                     return True
#
#                 gst_values.append(entity_identifier_data.get('entityIdNo'))
#
#         print(gst_values)
#
#     return False


def check_for_entity_gst_duplicate_values(request_data):

    for entity_register_data in request_data.get('entityRegisterData'):
        pan_id_no = [entry.get("entityIdNo", "") for entry in entity_register_data.get("entityIdentifierData") if
                     entry.get("entityIdType", "").lower() == 'pan']
        if len(pan_id_no) >= 2:
            return False

        pan_values = []
        gst_values = []
        for entity_identifier_data in entity_register_data.get('entityIdentifierData'):
            if entity_identifier_data.get('entityIdType').lower() == "gstin":
                derived_pan = entity_identifier_data.get('entityIdNo')[2:12]
                if entity_identifier_data.get('entityIdNo').lower() in gst_values:
                    return False
                gst_values.append(entity_identifier_data.get('entityIdNo').lower())

                if pan_id_no:
                    if pan_id_no[0] != derived_pan:
                        return False
                if pan_values:
                    if derived_pan not in pan_values:
                        return False
                    pan_values.append(derived_pan)
                else:
                    pan_values.append(derived_pan)

    return True


def check_invoice_date(invoice_data):
    from datetime import datetime
    date_list = [sub['invoiceDate'] for sub in invoice_data.get('ledgerData')]
    logger.info(f"getting date list >>>>>>>>>>>>>>>>>>{date_list}")
    current_date = datetime.now()
    is_greater_than_current = lambda date: datetime.strptime(date, '%d/%m/%Y') < current_date
    results = list(map(is_greater_than_current, date_list))
    logger.info(f"getting date list >>>>>>>>>>>>>>>>>>{results}")

    if False in results:
        for index, value in enumerate(results):
            if not value:  # Check if the value is False
                print("First False position is:", index)
                date = date_list[index]
                return date
                break  # Stop after finding the first False

    return True


def create_post_processing(db, data, api_type, flag, merchant_key, api_response):
    logger.info(f"getting response data {data}")
    # merchant_details = db.query(models.MerchantDetails).filter(models.MerchantDetails.merchant_key ==
    # merchant_key).first()
    # merchant_id_obj = merchant_details.id if merchant_details.id else ''
    # merchant_id = str(merchant_id_obj).zfill(4)
    # logger.info(f"merchant id create post processing >>>>>>>>>>>>>>>>>>>>>> {merchant_id}")
    if flag == "response":
        invoice_obj = (
            db.query(models.PostProcessingRequest)
            .filter(models.PostProcessingRequest.request_extra_data.contains({"requestId": data.get('requestId')}))
            .order_by(desc(
                models.PostProcessingRequest.id))  # Replace 'your_column_name' with the actual column to order by
            .first()
        )
        logger.info(f"getting invoice object >>>>>>>>>>> {invoice_obj.id} >>>>>>>>>>> ")
        invoice_obj.webhook_response = data
        db.commit()
        db.refresh(invoice_obj)
    else:
        merchant_details = db.query(models.MerchantDetails).filter(
            models.MerchantDetails.merchant_key == merchant_key).first()
        if not merchant_details:
            return {
                "requestId": data.get('requestId'),
                **ErrorCodes.get_error_response(1002)
            }
        merchant_id = merchant_details.id if merchant_details else ''
        logger.info(f"merchant id create post processing >>>>>>>>>>>>>>>>>>>>>> {merchant_id}")
        post_process_create = PostProcessingRequest(
            request_extra_data=data,
            api_response=api_response,
            type=api_type,
            merchant_id=str(merchant_id)
        )
        db.add(post_process_create)
        db.commit()
        db.refresh(post_process_create)
        if api_type == 'asyncFinancing':
            return_response = {"requestId": data.get('requestId'), **ErrorCodes.get_error_response(1028)}
        elif api_type == 'asyncDisbursement':
            return_response = {"requestId": data.get('requestId'), **ErrorCodes.get_error_response(1029)}
        elif api_type == 'asyncRepayment':
            return_response = {"requestId": data.get('requestId'), **ErrorCodes.get_error_response(1033)}
        elif api_type == 'async_validation_service_with_code':
            return_response = {"requestId": data.get('requestId'), **ErrorCodes.get_error_response(1034)}
        elif api_type == 'async_validation_service_without_code':
            return_response = {"requestId": data.get('requestId'), **ErrorCodes.get_error_response(1035)}
        elif api_type == 'ledger_status_check':
            return_response = {"requestId": data.get('requestId'), **ErrorCodes.get_error_response(1050)}
        elif api_type == 'invoice_status_check_with_code':
            return_response = {"requestId": data.get('requestId'), **ErrorCodes.get_error_response(1051)}
        elif api_type == 'invoice_status_check_without_code':
            return_response = {"requestId": data.get('requestId'), **ErrorCodes.get_error_response(1052)}
        else:
            return_response = {"requestId": data.get('requestId'), **ErrorCodes.get_error_response(1023)}
        response_hash = create_response_hash(db, return_response, merchant_key)
        return_response.update({"signature": response_hash})
        return return_response


def create_request_log(db, request_id, request_data, response_data, flag, api_url='', merchant_key=None):
    try:
        # merchant_details = db.query(MerchantDetails).filter(MerchantDetails.merchant_key == merchant_key).first()
        # if not merchant_details:
        #     return {
        #         "requestId": request_data.get('requestId'),
        #         **ErrorCodes.get_error_response(1002)
        #     }
        # merchant_id_obj = merchant_details.id if merchant_details.id else ''
        # merchant_id = str(merchant_id_obj).zfill(4)
        # logger.info(f"merchant_id request log >>>>>>>>>>>>>>>>>>>>>> {merchant_id}")
        api_request_obj = db.query(
            models.APIRequestLog
        ).filter(
            models.APIRequestLog.request_id == request_id
        ).first()
        logger.info(f"getting data iof api request log ################### {api_request_obj}")
        if flag == 'request':
            if api_request_obj:
                return {"requestId": request_id, **ErrorCodes.get_error_response(1009)}
            merchant_details = db.query(MerchantDetails).filter(MerchantDetails.merchant_key == merchant_key).first()
            if not merchant_details:
                return {
                    "requestId": request_data.get('requestId'),
                    **ErrorCodes.get_error_response(1002)
                }
            merchant_id = merchant_details.id if merchant_details else ''
            logger.info(f"merchant_id request log >>>>>>>>>>>>>>>>>>>>>> {merchant_id}")
            request_created = models.APIRequestLog(
                request_id=request_data.get('requestId'),
                request_data=request_data,
                api_url=api_url,
                merchant_id=str(merchant_id)
            )
            db.add(request_created)
            db.commit()
            db.refresh(request_created)
            return {"requestId": request_id, **ErrorCodes.get_error_response(200)}
        else:
            api_request_obj.response_data = response_data
            api_request_obj.updated_at = datetime.now()
            db.commit()
            db.refresh(api_request_obj)
    except Exception as e:
        logger.error(f"getting error while creating request log >>>>>>>>>>>>>>> {e}")
        return {**ErrorCodes.get_error_response(500)}


def get_webhook_url(db, merchant_key):
    merchant_details = db.query(MerchantDetails).filter(MerchantDetails.merchant_key == merchant_key).first()
    return merchant_details.webhook_endpoint


def check_invoice_due_date(request_data):
    # Convert string dates to datetime objects
    invoice_due_date_validation = False
    for request_datas in request_data.get('ledgerData'):
        if request_datas.get('invoiceDueDate'):
            invoice_date_obj = datetime.strptime(request_datas.get('invoiceDate'), "%d/%m/%Y")
            invoice_due_date_obj = datetime.strptime(request_datas.get('invoiceDueDate'), "%d/%m/%Y")

            # Check if invoice due date is greater than invoice date
            if invoice_due_date_obj < invoice_date_obj:
                return True

    return invoice_due_date_validation


def check_finance_request_date(request_data):
    finance_request_date_val_resp = {
        "requestId": request_data.get('requestId'),
        **ErrorCodes.get_error_response(200)
    }
    for request_datas in request_data.get('ledgerData'):
        if request_datas.get('financeRequestDate'):
            invoice_date_obj = datetime.strptime(request_datas.get('invoiceDate'), "%d/%m/%Y")
            finance_request_date = datetime.strptime(request_datas.get('financeRequestDate'), "%d/%m/%Y")
            # Check if invoice due date is greater than invoice date
            if finance_request_date < invoice_date_obj:
                return {
                    "requestId": request_data.get('requestId'),
                    **ErrorCodes.get_error_response(1037)
                }
                # invoice_due_date_validation = True

            current_date = datetime.now()
            if finance_request_date > current_date:
                return {
                    "requestId": request_data.get('requestId'),
                    **ErrorCodes.get_error_response(1072)
                }

    return finance_request_date_val_resp


def validate_ledger_date(request_data):
    from datetime import datetime
    current_date = datetime.now()
    for ledger in request_data.get('ledgerData'):
        if ledger.get('invoiceDate'):
            invoice_date = datetime.strptime(ledger.get('invoiceDate'), "%d/%m/%Y")
            if invoice_date > current_date:
                return {
                    "requestId": request_data.get('requestId'),
                    **ErrorCodes.get_error_response(1016)
                }

        if ledger.get('financeRequestDate'):
            invoice_date = datetime.strptime(ledger.get('invoiceDate'), "%d/%m/%Y")
            finance_request_date = datetime.strptime(ledger.get('financeRequestDate'), "%d/%m/%Y")
            invoice_due_date = datetime.strptime(ledger.get('dueDate'), "%d/%m/%Y")
            # Check if financeRequestDate is greater than invoice date
            if finance_request_date < invoice_date:
                return {
                    "requestId": request_data.get('requestId'),
                    **ErrorCodes.get_error_response(1037)
                }
            elif finance_request_date > current_date:
                return {
                    "requestId": request_data.get('requestId'),
                    **ErrorCodes.get_error_response(1072)
                }
            elif invoice_due_date < finance_request_date:
                return {
                    "requestId": request_data.get('requestId'),
                    **ErrorCodes.get_error_response(1080)
                }
            fin_req_amt = ledger.get('financeRequestAmt', '0')
            inv_amt = ledger.get('invoiceAmt', '0')
            if float(fin_req_amt) > float(inv_amt):
                return {
                    "requestId": request_data.get('requestId'),
                    **ErrorCodes.get_error_response(1094)
                }

            adjustment_type = ledger.get('adjustmentType', '')
            adjustment_amt = ledger.get('adjustmentAmt', '0')
            if adjustment_type.lower() == 'none' and float(adjustment_amt) != float(0):
                return {
                    "requestId": request_data.get('requestId'),
                    **ErrorCodes.get_error_response(1098)
                }

        if ledger.get('dueDate'):
            invoice_date = datetime.strptime(ledger.get('invoiceDate'), "%d/%m/%Y")
            invoice_due_date = datetime.strptime(ledger.get('dueDate'), "%d/%m/%Y")

            # Check if invoice due date is greater than invoice date
            if invoice_due_date < invoice_date:
                return {
                    "requestId": request_data.get('requestId'),
                    **ErrorCodes.get_error_response(1025)
                }

        if ledger.get('disbursedDate'):
            invoice_date = datetime.strptime(ledger.get('invoiceDate'), "%d/%m/%Y")
            disbursed_date = datetime.strptime(ledger.get('disbursedDate'), "%d/%m/%Y")
            due_date = datetime.strptime(ledger.get('dueDate'), "%d/%m/%Y")
            disbursed_amt = ledger.get('disbursedAmt', '0')

            # Check if disbursed date is greater than invoice date
            if disbursed_date < invoice_date:
                return {
                    "requestId": request_data.get('requestId'),
                    **ErrorCodes.get_error_response(1039)
                }
            # Due date should be greater than Disburse date
            elif disbursed_date > due_date:
                return {
                    "requestId": request_data.get('requestId'),
                    **ErrorCodes.get_error_response(1040)
                }
            elif disbursed_date > current_date:
                return {
                    "requestId": request_data.get('requestId'),
                    **ErrorCodes.get_error_response(1073)
                }
            elif float(disbursed_amt) <= float(0):
                return {
                    "requestId": request_data.get('requestId'),
                    **ErrorCodes.get_error_response(1112)
                }

        if ledger.get('repaymentDate'):
            invoice_date = datetime.strptime(ledger.get('invoiceDate'), "%d/%m/%Y")
            repayment_date = datetime.strptime(ledger.get('repaymentDate'), "%d/%m/%Y")
            invoice_due_date = datetime.strptime(ledger.get('dueDate'), "%d/%m/%Y")
            repayment_amt = ledger.get('repaymentAmt', '0')
            # Check if repayment date is greater than invoice date
            if repayment_date < invoice_date:
                return {
                    "requestId": request_data.get('requestId'),
                    **ErrorCodes.get_error_response(1041)
                }
            elif repayment_date > current_date:
                return {
                    "requestId": request_data.get('requestId'),
                    **ErrorCodes.get_error_response(1074)
                }
            elif invoice_due_date < repayment_date:
                return {
                    "requestId": request_data.get('requestId'),
                    **ErrorCodes.get_error_response(1079)
                }
            elif float(repayment_amt) <= float(0):
                return {
                    "requestId": request_data.get('requestId'),
                    **ErrorCodes.get_error_response(1113)
                }
    return {
        "requestId": request_data.get('requestId'),
        **ErrorCodes.get_error_response(200)
    }


def check_ledger(db, request_data, merchant_obj):
    logger.info(f"getting ledger check {request_data.get('ledgerNo')}")
    ledger_data = db.query(models.Ledger).filter(
        models.Ledger.ledger_id == request_data.get('ledgerNo'),
        models.Ledger.merchant_id == merchant_obj.id
    ).first()
    logger.info(f"getting ledger data {ledger_data}")
    if ledger_data:
        return {'requestId': request_data.get('requestId'), **ErrorCodes.get_error_response(200)}
    else:
        return {'requestId': request_data.get('requestId'), **ErrorCodes.get_error_response(1007)}


def update_cached_invoice_list(invoices_list):
    invoice_cache = r.get('invoices')
    ast.literal_eval(invoice_cache)
    new_invoice = [i for i in ast.literal_eval(invoice_cache) if i not in invoices_list]
    r.set('invoices', str(new_invoice))
    invoice_cache = r.get('invoices')
    logger.info(f"updated redis cached invoice list.......:: {invoice_cache}")


def update_cached_invoice_list(invoices_list):
    invoice_cache = r.get('invoices')
    ast.literal_eval(invoice_cache)
    new_invoice = [i for i in ast.literal_eval(invoice_cache) if i not in invoices_list]
    r.set('invoices', str(new_invoice))
    invoice_cache = r.get('invoices')
    logger.info(f"updated redis cached invoice list.......:: {invoice_cache}")


def validate_pan_gst_pan(request_data):
    logger.info(request_data)
    for data in request_data.get('entityRegisterData'):
        gst_filtered_obj = filter(lambda entry: entry.get("entityIdType").lower() == "gstin",
                                  data.get("entityIdentifierData", []))
        gst_obj = next(gst_filtered_obj, None)
        pan_filtered_obj = filter(lambda entry: entry.get("entityIdType").lower() == "pan",
                                  data.get("entityIdentifierData", []))
        pan_obj = next(pan_filtered_obj, None)
        if pan_obj and gst_obj:
            derived_pan = gst_obj.get('entityIdNo')[2:12]
            if derived_pan != pan_obj.get('entityIdNo'):
                return True
            else:
                return False
        return False


def validate_seller_invoice_pan_gst_pan(request_data):
    logger.info(f"seller data {request_data} >>>>>>>>>>>>>>>>>>>>>>>")
    if request_data.get("sellerIdentifierData"):
        gst_filtered_obj = filter(lambda entry: entry.get("sellerIdType").lower() == "gstin",
                                  request_data.get("sellerIdentifierData", []))
        gst_obj = next(gst_filtered_obj, None)
        pan_filtered_obj = filter(lambda entry: entry.get("sellerIdType").lower() == "pan",
                                  request_data.get("sellerIdentifierData", []))
        pan_obj = next(pan_filtered_obj, None)
        if pan_obj and gst_obj:
            derived_pan = gst_obj.get('sellerIdNo')[2:12]
            if derived_pan != pan_obj.get('sellerIdNo'):
                return True
            else:
                return False
    return False


def validate_buyer_invoice_pan_gst_pan(request_data):
    logger.info(f"buyer  data{request_data} >>>>>>>>>>>>>>>>>>>>>>>")
    if request_data.get("buyerIdentifierData"):
        gst_filtered_obj = filter(lambda entry: entry.get("buyerIdType").lower() == "gstin",
                                  request_data.get("buyerIdentifierData", []))
        gst_obj = next(gst_filtered_obj, None)
        pan_filtered_obj = filter(lambda entry: entry.get("buyerIdType").lower() == "pan",
                                  request_data.get("buyerIdentifierData", []))
        pan_obj = next(pan_filtered_obj, None)
        if pan_obj and gst_obj:
            derived_pan = gst_obj.get('buyerIdNo')[2:12]
            if derived_pan != pan_obj.get('buyerIdNo'):
                return True
            else:
                return False
    return False


def pan_exist(data):
    logger.info(data)
    gst_filtered_obj = filter(lambda entry: entry.get("entityIdType").lower() == "gstin",
                              data.get("entityIdentifierData", []))
    gst_obj = next(gst_filtered_obj, None)
    pan_filtered_obj = filter(lambda entry: entry.get("entityIdType").lower() == "pan",
                              data.get("entityIdentifierData", []))
    pan_obj = next(pan_filtered_obj, None)
    if not gst_obj and not pan_obj:
        return True, ''
    if pan_obj:
        return True, ''
    else:
        derived_pan = gst_obj.get('entityIdNo')[2:12]
        return False, derived_pan
    # logger.info(f"getting data {gst_obj}")
    # logger.info(f"getting data {pan_obj}")


def buyer_pan_exist(data):
    logger.info(data)
    if data.get("buyerIdentifierData"):
        gst_filtered_obj = filter(lambda entry: entry.get("buyerIdType").lower() == "gstin",
                                  data.get("buyerIdentifierData", []))
        gst_obj = next(gst_filtered_obj, None)
        pan_filtered_obj = filter(lambda entry: entry.get("buyerIdType").lower() == "pan",
                                  data.get("buyerIdentifierData", []))
        pan_obj = next(pan_filtered_obj, None)
        if not gst_obj and not pan_obj:
            return True, ''
        if pan_obj:
            return True, ''
        else:
            derived_pan = gst_obj.get('buyerIdNo')[2:12]
            return False, derived_pan
    return True, ''


def seller_pan_exist(data):
    logger.info(data)
    if data.get("sellerIdentifierData"):
        gst_filtered_obj = filter(lambda entry: entry.get("sellerIdType").lower() == "gstin",
                                  data.get("sellerIdentifierData", []))
        gst_obj = next(gst_filtered_obj, None)
        pan_filtered_obj = filter(lambda entry: entry.get("sellerIdType").lower() == "pan",
                                  data.get("sellerIdentifierData", []))
        pan_obj = next(pan_filtered_obj, None)
        if not gst_obj and not pan_obj:
            return True, ''
        if pan_obj:
            return True, ''
        else:
            derived_pan = gst_obj.get('sellerIdNo')[2:12]
            return False, derived_pan
    return True, ''


# identifier data duplicate check
def check_for_duplicate_pan_values(json_list):
    seller_id_no = ""
    if json_list.get('sellerIdentifierData'):
        for seller_data in json_list.get('sellerIdentifierData'):
            if seller_data.get('sellerIdType').lower() == "pan":
                seller_id_no = seller_data.get('sellerIdNo')

    if json_list.get('buyerIdentifierData'):
        for buyer_data in json_list.get('buyerIdentifierData'):
            if buyer_data.get('buyerIdType').lower() == "pan":
                buyer_id_no = buyer_data.get('buyerIdNo')
                if seller_id_no == buyer_id_no:
                    return True
    return False


def check_for_duplicate_lei_values(json_list):
    seller_id_no = ""
    if json_list.get('sellerIdentifierData'):
        for seller_data in json_list.get('sellerIdentifierData'):
            if seller_data.get('sellerIdType').lower() == "lei":
                seller_id_no = seller_data.get('sellerIdNo')

    if json_list.get('buyerIdentifierData'):
        for buyer_data in json_list.get('buyerIdentifierData'):
            if buyer_data.get('buyerIdType').lower() == "lei":
                buyer_id_no = buyer_data.get('buyerIdNo')
                if seller_id_no == buyer_id_no:
                    return True
    return False


def check_for_duplicate_cin_values(json_list):
    seller_id_no = ""
    if json_list.get('sellerIdentifierData'):
        for seller_data in json_list.get('sellerIdentifierData'):
            if seller_data.get('sellerIdType').lower() == "cin":
                seller_id_no = seller_data.get('sellerIdNo')

    if json_list.get('buyerIdentifierData'):
        for buyer_data in json_list.get('buyerIdentifierData'):
            if buyer_data.get('buyerIdType').lower() == "cin":
                buyer_id_no = buyer_data.get('buyerIdNo')
                if seller_id_no == buyer_id_no:
                    return True
    return False


def check_for_duplicate_tax_no_values(json_list):
    seller_id_no = ""
    if json_list.get('sellerIdentifierData'):
        for seller_data in json_list.get('sellerIdentifierData'):
            if seller_data.get('sellerIdType').lower() == "tax_no":
                seller_id_no = seller_data.get('sellerIdNo')

    if json_list.get('buyerIdentifierData'):
        for buyer_data in json_list.get('buyerIdentifierData'):
            if buyer_data.get('buyerIdType').lower() == "tax_no":
                buyer_id_no = buyer_data.get('buyerIdNo')
                if seller_id_no == buyer_id_no:
                    return True
    return False


def days_to_past_date(number_of_days):
    # Get the current date
    # current_date = datetime.now()
    current_date = dt.datetime.now(asia_kolkata)

    # Calculate the timedelta for the given number of days
    delta = timedelta(days=number_of_days)

    # Subtract the delta from the current date to get the result date
    result_date = current_date - delta

    return result_date


def generate_aes_key(password, salt=b'salt', iterations=100000):
    # Convert password to bytes
    password = password.encode('utf-8')

    # Derive a key using PBKDF2 with HMAC and SHA256
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,  # 256-bit key for AES-256
        salt=salt,
        iterations=iterations,
        backend=default_backend()
    )

    # Generate the key
    key = kdf.derive(password)
    return key


def extract_json_value(input_string):
    # Define the regular expression pattern
    pattern = r'\{.*\}'

    # Use re.search to find the first match of the pattern in the input string
    match = re.search(pattern, input_string)

    # Check if a match is found
    if match:
        # Extract the matched substring
        json_string = match.group()

        # Parse the JSON string to a Python dictionary
        try:
            json_value = json.loads(json_string)
            return json_value
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON: {e}")
            return None
    else:
        print("No JSON value found in the input string")
        return None


def encrypt_aes_256(key: bytes, data: bytes):
    data = json.dumps(data)
    data = data.encode('utf-8')
    padder = padding.PKCS7(128).padder()
    padded_data = padder.update(data) + padder.finalize()

    iv = os.urandom(16)  # Generate a random IV (Initialization Vector)
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    encrypted_data = encryptor.update(padded_data) + encryptor.finalize()

    encrypted_data = iv + encrypted_data
    encrypted_data = base64.b64encode(encrypted_data)
    encrypted_data = encrypted_data.decode('utf-8')

    return encrypted_data.strip()


def decrypt_aes_256(key: bytes, encrypted_data: bytes):
    encrypted_data = base64.b64decode(encrypted_data)
    iv = encrypted_data[:16]
    encrypted_data = encrypted_data[16:]
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    decrypted_data = decryptor.update(encrypted_data) + decryptor.finalize()
    logger.info(f"decrypted_data {decrypted_data}")
    # decrypted_data = ''.join(char for char in decrypted_data.decode('utf-8') if char in
    # '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ!"#$%&\'()*+,-./:;<=>?@[\\]^_`{|}~ ')
    # return json.loads(decrypted_data.decode('utf-8'))
    # return json.loads(decrypted_data.decode('utf-8').rstrip('\x06').rstrip('\x0e').strip())
    decrypted_data = decrypted_data.decode('utf-8').strip()
    decrypted_data = extract_json_value(decrypted_data)
    return decrypted_data

    # from utils import encrypt_aes_256, decrypt_aes_256, generate_aes_key
    # password = "6CLKp-iDUG_dSp5BC_jBqx6INMs1KNfZe0SJbNuGOsg" # merchant secret
    # key = generate_aes_key(password)
    # print(key)
    # key = b"\xca\x178\x92\x83v\x95\x9a\x8a\xbd\x04\xdb\x85\xdcXE\x81\x8f\x86h<\xf0\xb9\xc9'\xe9\x86f\xee6\x7f\x8c"
    #
    # data = {
    #     "requestId": "fin1000",
    #     "ledgerNo": "000117012410211000002000000000000012",
    #     "ledgerAmtFlag": "Full",
    #     "lenderCategory": "TReDSBanksNBFCsOthers",
    #     "lenderName": "RXIL",
    #     "lenderCode": "101",
    #     "borrowerCategory": "LMScorporate",
    #     "signature": "cf9d6931a98eeea7b1f7ab6d5fd761e935f693b7737c670334ebcb6d963ac020",
    #     "ledgerData": [
    #         {
    #             "invoiceNo": "INV-AIRWC-101",
    #             "financeRequestAmt": "10",
    #             "financeRequestDate": "18/01/2024",
    #             "dueDate": "20/02/2024",
    #             "fundingAmtFlag": "Full",
    #             "adjustmentType": "Advance",
    #             "adjustmentAmt": "0",
    #             "invoiceDate": "18/01/2024",
    #             "invoiceAmt": "10"
    #         },
    #         {
    #             "invoiceNo": "INV-AIRWC-102",
    #             "financeRequestAmt": "20",
    #             "financeRequestDate": "18/01/2024",
    #             "dueDate": "21/02/2024",
    #             "fundingAmtFlag": "Full",
    #             "adjustmentType": "Advance",
    #             "adjustmentAmt": "0",
    #             "invoiceDate": "18/01/2024",
    #             "invoiceAmt": "20"
    #         },
    #         {
    #             "invoiceNo": "INV-AIRWC-103",
    #             "financeRequestAmt": "30",
    #             "financeRequestDate": "18/01/2024",
    #             "dueDate": "20/02/2024",
    #             "fundingAmtFlag": "Full",
    #             "adjustmentType": "Advance",
    #             "adjustmentAmt": "0",
    #             "invoiceDate": "18/01/2024",
    #             "invoiceAmt": "30"
    #         }
    #     ]
    # }
    # import json
    # enc = encrypt_aes_256(key, data)
    # print(enc)
    # dec = decrypt_aes_256(key, enc)
    # print(dec)
    # # data = json.dumps(dec).encode('utf-8')
    # # print(data)


def create_hub_signature(data, hub_secret_key):
    logger.info(f"getting signature data >>>>>>>>>>>>>>>> {data}")
    logger.info(f"getting hub secret key >>>>>>>>>>>>>>>> {hub_secret_key}")

    final_string = '%s%s' % (data, hub_secret_key)
    signature = hashlib.sha256(final_string.encode()).hexdigest()
    logger.info(f"getting signature {signature}")
    # add this signature to the request body and post
    return signature


def validate_hub_signature(db, request_data, hub_key):
    logger.info(f"...inside validate_hub_signature...request :: {request_data}")

    hub_obj = db.query(Hub).filter(Hub.hub_key == hub_key).first()
    request_data_copy = request_data.copy()
    # request_data.pop('signature')
    # request_data.pop('encryptData')

    if hub_obj:
        data = request_data.get('txnCode') + request_data.get('correlationId')
        created_hub_sign = create_hub_signature(data, hub_obj.hub_secret)
        logger.info(f"create hub signature :: {created_hub_sign}")
        logger.info(f"requested hub signature :: {request_data_copy.get('signature')}")
        if request_data_copy.get('signature') == created_hub_sign:
            return {
                "hub_obj": hub_obj,
                **ErrorCodes.get_error_response(200)
            }
        else:
            return {**ErrorCodes.get_error_response(1001), "hub_obj": hub_obj}
    return {**ErrorCodes.get_error_response(1002)}


def create_hub_request_log(db, request_id, request_data, response_data, flag, api_url='', hub_id='', merchant_id='',
                           merchant_key=None):
    try:
        logger.info(f"... inside create_hub_request_log... ")
        hub_request_obj = db.query(
            models.HubRequestLog
        ).filter(
            models.HubRequestLog.request_id == request_id
        ).first()
        logger.info(f"fetch hub api request log data :: {hub_request_obj}")
        if flag == 'request':
            if hub_request_obj:
                return {"requestId": request_id, **ErrorCodes.get_error_response(1070)}
            # merchant_details = db.query(MerchantDetails).filter(MerchantDetails.merchant_key == merchant_key).first()
            # if not merchant_details:
            #     return {
            #         "requestId": request_data.get('requestId'),
            #         **ErrorCodes.get_error_response(1002)
            #     }
            # merchant_id_obj = merchant_details.id if merchant_details.id else ''
            # merchant_id = str(merchant_id_obj).zfill(4)
            # logger.info(f"merchant_id request log >>>>>>>>>>>>>>>>>>>>>> {merchant_id}")
            request_created = models.HubRequestLog(
                request_id=request_id,
                request_data=request_data,
                api_url=api_url,
                hub_id=hub_id,
                merchant_id=merchant_id
                # merchant_id=merchant_id
            )
            db.add(request_created)
            db.commit()
            db.refresh(request_created)
            return {"requestId": request_id, **ErrorCodes.get_error_response(200)}
        else:
            hub_request_obj.response_data = response_data
            db.commit()
            db.refresh(hub_request_obj)
    except Exception as e:
        logger.error(f"getting error while creating hub request log :: {e}")
        return {**ErrorCodes.get_error_response(500)}


def validate_idp_gst(db, request_data):
    query = """
        SELECT 
            md.extra_data->>'IdpGst' AS IdpGst
        FROM 
            merchant_details md 
        WHERE 
            md.extra_data->>'IdpGst' = :idp_gst 
    ;
    """

    merchant_gst_data = db.execute(text(query), {
        'idp_gst': request_data.get('IdpGst')
    }).first()

    request_gst = request_data.get('IdpGst') if request_data.get('IdpGst') else ''
    if merchant_gst_data and merchant_gst_data[0]:
        # merchant_exit_gst = merchant_gst_data.get('IdpGst')
        merchant_exit_gst = merchant_gst_data[0]
    elif merchant_gst_data is None:
        merchant_exit_gst = merchant_gst_data
    else:
        merchant_exit_gst = ""

    if merchant_exit_gst == request_gst:
        return True
    else:
        return False


def validate_idp_pan(db, request_data):
    query = """
        SELECT 
            md.extra_data->>'IdpPan' AS IdpPan
        FROM 
            merchant_details md 
        WHERE 
            md.extra_data->>'IdpPan' = :idp_pan 
    ;
    """

    merchant_pan_data = db.execute(text(query), {
        'idp_pan': request_data.get('IdpPan')
    }).first()

    request_pan = request_data.get('IdpPan') if request_data.get('IdpPan') else ''
    if merchant_pan_data and merchant_pan_data[0]:
        merchant_exit_pan = merchant_pan_data[0]
    elif merchant_pan_data is None:
        merchant_exit_pan = merchant_pan_data
    else:
        merchant_exit_pan = ""

    if merchant_exit_pan == request_pan:
        return True
    else:
        return False


def read_csv_reg_finance():
    invoice_obj = {}
    ledger_data = []
    finance_ledger_data = []
    seller_identifier_data = []
    buyer_identifier_data = []
    request_packet = []
    finance_request_packet = []
    total_row_invoices = 0
    total_invoice_request_count = 0
    seller_identifier_rows = 0
    seller_identifier_request_count = 0
    buyer_identifier_rows = 0
    buyer_identifier_request_count = 0

    file_path = "/home/akhilesh/Downloads/dev%%abc%invoice_reg_without_entity_code_finance%0015%veena%001%07032024%122000%3.csv"
    # file_path = "/home/akhilesh/Documents/Incoming/Invoice_Reg_Without_EC_Financing.csv"
    # file_path = "/home/django/incoming/Invoice_Reg_Without_EC_Financing.csv"
    try:
        df = pd.read_csv(file_path, delimiter="|", dtype=str, na_values='')
        df = df.replace(np.nan, '')
        df = df.dropna(how='all')
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")

    request_packet_validation = True
    for index, row in df.iterrows():
        ledger_datas = ""
        finance_ledger_datas = ""

        if not invoice_obj:
            invoice_obj = {"requestId": str(row.requestID),
                           "sellerGst": str(row.sellerGst),
                           "buyerGst": str(row.buyerGst),
                           "channel": row.channel,
                           "hubId": row.hubId,
                           "idpId": row.idpId,
                           "groupingId": str(row.groupingId),
                           "total_invoice": row.noOfInvoices if row.noOfInvoices and row.noOfInvoices.isnumeric() else 0,
                           "total_buyer_identifier_request": row.buyerDataNo if row.buyerDataNo and row.buyerDataNo.isnumeric() else 0,
                           "total_buyer_identifier_count": 0,
                           "total_seller_identifier_request": row.sellerDataNo if row.sellerDataNo and row.sellerDataNo.isnumeric() else 0,
                           "total_seller_identifier_count": 0
                           }
            finance_obj = {
                "requestId": 'finance_' + str(row.requestID),
                "ledgerNo": "",
                "ledgerAmtFlag": str(row.ledgerAmtFlag),
                "lenderCategory": str(row.lenderCategory),
                "lenderName": str(row.lenderName),
                "lenderCode": str(row.lenderCode),
                "borrowerCategory": str(row.borrowerCategory)
            }
        else:
            if str(invoice_obj.get('requestId')) != str(row.requestID):
                if request_packet_validation:
                    request_packet.append(invoice_obj)
                    finance_request_packet.append(finance_obj)
                request_packet_validation = True
                invoice_obj = {
                    "requestId": str(row.requestID),
                    "sellerGst": str(row.sellerGst),
                    "buyerGst": str(row.buyerGst),
                    "channel": row.channel,
                    "hubId": row.hubId,
                    "idpId": row.idpId,
                    "groupingId": str(row.groupingId),
                    "total_invoice": row.noOfInvoices if row.noOfInvoices and row.noOfInvoices.isnumeric() else 0,
                    "total_buyer_identifier_request": row.buyerDataNo if row.buyerDataNo and row.buyerDataNo.isnumeric() else 0,
                    "total_buyer_identifier_count": 0,
                    "total_seller_identifier_request": row.sellerDataNo if row.sellerDataNo and row.sellerDataNo.isnumeric() else 0,
                    "total_seller_identifier_count": 0
                }

                finance_obj = {
                    "requestId": 'finance_' + str(row.requestID),
                    "ledgerNo": "",
                    "ledgerAmtFlag": str(row.ledgerAmtFlag),
                    "lenderCategory": str(row.lenderCategory),
                    "lenderName": str(row.lenderName),
                    "lenderCode": str(row.lenderCode),
                    "borrowerCategory": str(row.borrowerCategory),
                }

                ledger_data = []
                finance_ledger_data = []
                seller_identifier_data = []
                buyer_identifier_data = []
                total_row_invoices = 0
                # total_invoice_request_count = 0
                seller_identifier_rows = 0
                # seller_identifier_request_count = 0
                buyer_identifier_rows = 0
                # buyer_identifier_request_count = 0

            # request_packet.append(invoice_obj)
            # finance_request_packet.append(finance_obj)

        gst_status = row.verifyGSTNFlag
        if row.verifyGSTNFlag == str(1):
            gst_status = True
        if row.verifyGSTNFlag == str(0):
            gst_status = False

        if str(row.invoiceNo) or row.invoiceDate or str(row.invoiceAmt) or gst_status or row.invoiceDueDate:
            ledger_datas = {
                "invoiceNo": str(row.invoiceNo),
                "invoiceDate": row.invoiceDate,
                "invoiceAmt": str(row.invoiceAmt),
                "verifyGSTNFlag": gst_status,
                "invoiceDueDate": row.invoiceDueDate,
            }

            finance_ledger_datas = {
                "invoiceNo": str(row.invoiceNo),
                "financeRequestAmt": str(row.financeRequestAmt),
                "financeRequestDate": str(row.financeRequestDate),
                "dueDate": str(row.dueDate),
                "fundingAmtFlag": str(row.fundingAmtFlag),
                "adjustmentType": str(row.adjustmentType),
                "adjustmentAmt": str(row.adjustmentAmt),
                "invoiceDate": str(row.invoiceDate),
                "invoiceAmt": str(row.invoiceAmt)
            }
            total_row_invoices = total_row_invoices + 1

        if str(row.sellerIdType) or str(row.sellerIdNo) or str(row.sellerIdName) or str(row.sellerIfsc):
            seller_identifier_rows = seller_identifier_rows + 1
            invoice_obj.update({"total_seller_identifier_count": str(seller_identifier_rows)})

        seller_identifier_datas = {
            "sellerIdType": row.sellerIdType,
            "sellerIdNo": row.sellerIdNo,
            "sellerIdName": row.sellerIdName,
            "ifsc": row.sellerIfsc
        }

        if str(row.buyerIdType) or str(row.buyerIdNo) or str(row.buyerIdName) or str(row.buyerIfsc):
            buyer_identifier_rows = buyer_identifier_rows + 1
            invoice_obj.update({"total_buyer_identifier_count": str(buyer_identifier_rows)})

        buyer_identifier_datas = {
            "buyerIdType": str(row.buyerIdType),
            "buyerIdNo": str(row.buyerIdNo),
            "buyerIdName": str(row.buyerIdName),
            "ifsc": row.buyerIfsc
        }
        # if invoice_no !=
        if ledger_datas:
            ledger_data.append(ledger_datas)
            finance_ledger_data.append(finance_ledger_datas)

        if seller_identifier_datas:
            seller_identifier_data.append(seller_identifier_datas)

        if buyer_identifier_datas:
            buyer_identifier_data.append(buyer_identifier_datas)

        if ledger_datas:
            finance_obj.update({"ledgerData": finance_ledger_data})
            invoice_obj.update({
                "ledgerData": ledger_data,
                "sellerIdentifierData": seller_identifier_data,
                "buyerIdentifierData": buyer_identifier_data,
                "financeData": [finance_obj]
            })

        if (invoice_obj.get('channel').lower() != row.channel.lower().strip() or invoice_obj.get('hubId').strip()
                != row.hubId.strip() or invoice_obj.get('idpId') != row.idpId.strip() or invoice_obj.get('sellerGst')
                != row.sellerGst.strip() or invoice_obj.get('buyerGst')
                != row.buyerGst.strip()
        ):
            request_packet_validation = False

        if index == df.shape[0] - 1 and str(invoice_obj.get('requestId')) == str(row.requestID):
            if request_packet_validation:
                if invoice_obj.get('ledgerData', ''):
                    request_packet.append(invoice_obj)
                finance_request_packet.append(finance_obj)
            request_packet_validation = True

    logger.info(f"getting request packet {request_packet}")
    return request_packet


def validate_seller_identifier(invoice_data):
    if not invoice_data.get('sellerGst'):
        for seller_identifier_data in invoice_data.get('sellerIdentifierData'):
            if seller_identifier_data.get('sellerIdType'):
                return True
        return False
    return True


def validate_buyer_identifier(invoice_data):
    if not invoice_data.get('buyerGst'):
        for buyer_identifier_data in invoice_data.get('buyerIdentifierData'):
            if buyer_identifier_data.get('buyerIdType'):
                return True
        return False
    return True


def validate_pan_gst_relationship(pan, gst):
    # logger.info(f"seller data {pan}>>>>{gst} >>>>>>>>>>>>>>>>>>>>>>>")
    if pan and gst:
        derived_pan = gst[2:12]
        if derived_pan == pan:
            return True
        else:
            return False
    return False


def create_csv_response_file(field_name, file_path, response_csv_data):
    try:
        logger.info(f"getting inside create csv file >>>>>>>>>>> {response_csv_data}")
        csv_data = io.StringIO()
        csv_writer = csv.DictWriter(csv_data, fieldnames=field_name, delimiter="|")
        csv_writer.writeheader()
        csv_writer.writerows(response_csv_data)

        # This code for create file and write the csv data

        with open(file_path, 'w', encoding='utf-8') as file:
            # file.write('"' + csv_data.getvalue().replace('"', '""') + '"')
            file.write(csv_data.getvalue())

        # Get the CSV string and encode it to bytes
        csv_bytes = csv_data.getvalue().encode("utf-8")

        # Set headers for download
        response = Response(content=csv_bytes)
        response.headers["Content-Disposition"] = 'attachment; filename="data.csv"'
        response.headers["Content-Type"] = "text/csv"
        return response
    except Exception as e:
        logger.error(f"getting error while creating csv file {e}")
        return {**ErrorCodes.get_error_response(500)}


def cast_to_int_or_zero(value):
    try:
        return int(value)
    except ValueError:
        return 0


def dis_read_csv_file():
    invoice_obj = {}
    ledger_data = []
    request_packet = []
    total_row_invoices = 0
    total_invoice_request_count = 0

    file_path = "/home/lalita/Documents/A1SFTP/3_Disbursement.csv"
    try:
        df = pd.read_csv(file_path, delimiter="|", dtype=str, na_values='')
        df = df.replace(np.nan, '')
        # print(df.to_string())
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")

    for index, row in df.iterrows():
        if row.noOfInvoices:
            if total_row_invoices and total_row_invoices != total_invoice_request_count:
                return {"message": "invalid no of invoices count"}

            total_invoice_request_count = row.noOfInvoices

        ######
        if not invoice_obj:
            invoice_obj = {"requestId": str(row.requestID),
                           "ledgerNo": str(row.ledgerNo),
                           "lenderCategory": str(row.lenderCategory),
                           "lenderName": str(row.lenderName),
                           "lenderCode": str(row.lenderCode)
                           }
        else:
            if str(invoice_obj.get('requestId')) != str(row.requestID):
                request_packet.append(invoice_obj)
                invoice_obj = {"requestId": str(row.requestID),
                               "ledgerNo": str(row.ledgerNo),
                               "lenderCategory": str(row.lenderCategory),
                               "lenderName": str(row.lenderName),
                               "lenderCode": str(row.lenderCode)
                               }
                ledger_data = []
                total_row_invoices = 0
                total_invoice_request_count = 0
        #####
        if index == df.shape[0] - 1 and str(invoice_obj.get('requestId')) == str(row.requestID):
            request_packet.append(invoice_obj)
        # invoice_obj = {"requestId": row.requestID,
        #                "ledgerNo": row.ledgerNo,
        #                "lenderCategory": row.lenderCategory,
        #                "lenderName": row.lenderName,
        #                "lenderCode": row.lenderCode
        #                }
        # logger.info(f"getting request packet {invoice_obj}")
        if row.invoiceNo:
            ledger_datas = {
                "invoiceNo": str(row.invoiceNo),
                "disbursedFlag": str(row.disbursedFlag),
                "disbursedAmt": str(row.disbursedAmt),
                "disbursedDate": str(row.disbursedDate),
                "dueAmt": str(row.dueAmt),
                "dueDate": str(row.dueDate),
                "invoiceDate": row.invoiceDate,
                "invoiceAmt": str(row.invoiceAmt),
            }
            total_row_invoices = total_row_invoices + 1
            logger.info(f"getting ledger_datas request packet {ledger_datas}")

        if ledger_datas:
            ledger_data.append(ledger_datas)

        if ledger_datas:
            invoice_obj.update({
                "ledgerData": ledger_data,
                "channel": row.channel,
                "hubId": row.hubId,
                "idpId": row.idpId,
            })

    logger.info(f"getting request packet {request_packet}")
    return request_packet


def repay_read_csv_file():
    invoice_obj = {}
    repayment_ledger_data = []
    request_packet = []
    total_row_invoices = 0
    total_invoice_request_count = 0

    file_path = "/home/lalita/Documents/A1SFTP/repayment.csv"
    try:
        df = pd.read_csv(file_path, delimiter="|", dtype=str, na_values='')
        df = df.replace(np.nan, '')
        # print(df.to_string())
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")

    for index, row in df.iterrows():
        repayment_ledger_datas = ""
        if row.noOfInvoices:
            if total_row_invoices and total_row_invoices != total_invoice_request_count:
                return {"message": "invalid no of invoices count"}

            total_invoice_request_count = row.noOfInvoices

        if not invoice_obj:
            invoice_obj = {"requestId": str(row.requestID),
                           "ledgerNo": str(row.ledgerNo),
                           "borrowerCategory": str(row.borrowerCategory),
                           }
        else:
            if str(invoice_obj.get('requestId')) != str(row.requestID):
                request_packet.append(invoice_obj)
                invoice_obj = {"requestId": str(row.requestID),
                               "ledgerNo": str(row.ledgerNo),
                               "borrowerCategory": str(row.borrowerCategory),
                               }
                repayment_ledger_data = []
                total_row_invoices = 0
                total_invoice_request_count = 0

        if index == df.shape[0] - 1 and str(invoice_obj.get('requestId')) == str(row.requestID):
            request_packet.append(invoice_obj)

        if row.invoiceNo:
            repayment_ledger_datas = {
                "invoiceNo": str(row.invoiceNo),
                "assetClassification": str(row.assetClassification),
                "dueAmt": str(row.dueAmt),
                "dueDate": str(row.dueDate),
                "repaymentType": str(row.repaymentType),
                "repaymentFlag": str(row.repaymentFlag),
                "repaymentAmt": str(row.repaymentAmt),
                "repaymentDate": str(row.repaymentDate),
                "pendingDueAmt": str(row.pendingDueAmt),
                "dpd": str(row.dpd),
                "invoiceDate": row.invoiceDate,
                "invoiceAmt": str(row.invoiceAmt)
            }
            total_row_invoices = total_row_invoices + 1
            logger.info(f"getting request packet {repayment_ledger_datas}")

        if repayment_ledger_datas:
            repayment_ledger_data.append(repayment_ledger_datas)

        if repayment_ledger_datas:
            invoice_obj.update({
                "ledgerData": repayment_ledger_data,
                "channel": str(row.channel),
                "hubId": str(row.hubId),
                "idpId": str(row.idpId),
            })

    logger.info(f"getting repayment request packet {request_packet}")
    return request_packet


# READ CSV FILE REGISTRATION WITHOUT CODE
def read_csv_reg_without_ec():
    invoice_obj = {}
    ledger_data = []
    seller_identifier_data = []
    buyer_identifier_data = []
    request_packet = []
    total_row_invoices = 0
    seller_identifier_rows = 0
    buyer_identifier_rows = 0
    error_response = {"code": "", "message": ""}

    file_path = "/home/akhilesh/Downloads/dev%%abc%invoice_reg_without_entity_code%0015%veena%001%07032024%122000%3_1.csv"
    try:
        df = pd.read_csv(file_path, delimiter="|", dtype=str, na_values='')
        df = df.replace(np.nan, '')
        df = df.dropna(how='all')
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")

    request_packet_validation = True
    for index, row in df.iterrows():
        ledger_datas = ""

        if not invoice_obj:
            invoice_obj = {"requestId": str(row.requestID),
                           "sellerGst": str(row.sellerGst),
                           "buyerGst": str(row.buyerGst),
                           "channel": row.channel,
                           "hubId": row.hubId,
                           "idpId": row.idpId,
                           "groupingId": str(row.groupingId),
                           "total_invoice": row.noOfInvoices if row.noOfInvoices and row.noOfInvoices.isnumeric() else 0,
                           "total_buyer_identifier_request": row.buyerDataNo if row.buyerDataNo and row.buyerDataNo.isnumeric() else 0,
                           "total_buyer_identifier_count": 0,
                           "total_seller_identifier_request": row.sellerDataNo if row.sellerDataNo and row.sellerDataNo.isnumeric() else 0,
                           "total_seller_identifier_count": 0
                           }
        else:
            if str(invoice_obj.get('requestId')) != str(row.requestID):
                if request_packet_validation:
                    request_packet.append(invoice_obj)
                request_packet_validation = True
                invoice_obj = {
                    "requestId": str(row.requestID),
                    "sellerGst": str(row.sellerGst),
                    "buyerGst": str(row.buyerGst),
                    "groupingId": str(row.groupingId),
                    "channel": row.channel,
                    "hubId": row.hubId,
                    "idpId": row.idpId,
                    "total_invoice": row.noOfInvoices if row.noOfInvoices and row.noOfInvoices.isnumeric() else 0,
                    "total_buyer_identifier_request": row.buyerDataNo if row.buyerDataNo and row.buyerDataNo.isnumeric() else 0,
                    "total_buyer_identifier_count": 0,
                    "total_seller_identifier_request": row.sellerDataNo if row.sellerDataNo and row.sellerDataNo.isnumeric() else 0,
                    "total_seller_identifier_count": 0
                }

                ledger_data = []
                seller_identifier_data = []
                buyer_identifier_data = []
                total_row_invoices = 0
                seller_identifier_rows = 0
                buyer_identifier_rows = 0

        gst_status = row.verifyGSTNFlag
        if row.verifyGSTNFlag == str(1):
            gst_status = True
        if row.verifyGSTNFlag == str(0):
            gst_status = False

        if str(row.invoiceNo) or row.invoiceDate or str(row.invoiceAmt) or gst_status or row.invoiceDueDate:
            ledger_datas = {
                "invoiceNo": str(row.invoiceNo),
                "invoiceDate": row.invoiceDate,
                "invoiceAmt": str(row.invoiceAmt),
                "verifyGSTNFlag": gst_status,
                "invoiceDueDate": row.invoiceDueDate,
            }

            total_row_invoices = total_row_invoices + 1

        if str(row.sellerIdType) or str(row.sellerIdNo) or str(row.sellerIdName) or str(row.sellerIfsc):
            seller_identifier_rows = seller_identifier_rows + 1
            invoice_obj.update({"total_seller_identifier_count": str(seller_identifier_rows)})

        seller_identifier_datas = {
            "sellerIdType": row.sellerIdType,
            "sellerIdNo": row.sellerIdNo,
            "sellerIdName": row.sellerIdName,
            "ifsc": row.sellerIfsc
        }

        if str(row.buyerIdType) or str(row.buyerIdNo) or str(row.buyerIdName) or str(row.buyerIfsc):
            buyer_identifier_rows = buyer_identifier_rows + 1
            invoice_obj.update({"total_buyer_identifier_count": str(buyer_identifier_rows)})

        buyer_identifier_datas = {
            "buyerIdType": str(row.buyerIdType),
            "buyerIdNo": str(row.buyerIdNo),
            "buyerIdName": str(row.buyerIdName),
            "ifsc": row.buyerIfsc
        }
        # if invoice_no !=
        if ledger_datas:
            ledger_data.append(ledger_datas)

        if seller_identifier_datas:
            seller_identifier_data.append(seller_identifier_datas)

        if buyer_identifier_datas:
            buyer_identifier_data.append(buyer_identifier_datas)

        if ledger_datas:
            invoice_obj.update({
                "ledgerData": ledger_data,
                "sellerIdentifierData": seller_identifier_data,
                "buyerIdentifierData": buyer_identifier_data
            })

        if (invoice_obj.get('channel').lower() != row.channel.lower().strip() or invoice_obj.get('hubId').strip()
                != row.hubId.strip() or invoice_obj.get('idpId') != row.idpId.strip() or invoice_obj.get('sellerGst')
                != row.sellerGst.strip() or invoice_obj.get('buyerGst')
                != row.buyerGst.strip()
        ):
            request_packet_validation = False

        if index == df.shape[0] - 1 and str(invoice_obj.get('requestId')) == str(row.requestID):
            if request_packet_validation:
                if invoice_obj.get('ledgerData'):
                    request_packet.append(invoice_obj)
            request_packet_validation = True

    logger.info(f"getting request packet {request_packet}")
    return request_packet


# READ CSV ENTITY REGISTRATION
def read_csv_entity_reg():
    entity_obj = {}
    entity_register_data = {}
    request_packet = []
    entity_code = ""
    no_of_entity = 0
    no_of_identifiers = 0
    error_response = {"code": "", "message": ""}
    file_path = "/home/akhilesh/Downloads/dev%%abc%invoice_reg_without_entity_code%0015%veena%001%07032024%122000%3_1.csv"
    try:
        # df = pd.read_csv(file_path, delimiter="|", dtype={'lenderCode': str})
        df = pd.read_csv(file_path, delimiter="|", dtype=str, na_values='')
        df = df.replace(np.nan, '')
        df = df.dropna(how='all')
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")

    request_packet_validation = True
    for index, row in df.iterrows():
        if entity_code != row.entityCode:
            if entity_code and entity_code != str(row.entityCode).strip() or len(entity_obj) != 0:
                entity_obj.update({'totalEntityCount': no_of_entity})
                entity_obj.get('entityRegisterData').append(entity_register_data)

            entity_code = str(row.entityCode).strip()

        if not entity_obj:
            entity_obj = {
                "requestId": str(row.requestID).strip(),
                "channel": str(row.channel).strip(),
                "hubId": str(row.hubId).strip(),
                "idpId": str(row.idpId).strip(),
                "totalEntityRequest": row.noOfEntities if row.noOfEntities and row.noOfEntities.isnumeric() else "0",
                "totalIdentifiersRequest": row.noOfIdentifiers if row.noOfIdentifiers else "0",
                "totalEntityCount": 0,
                "totalIdentifiersCount": 0,
                "entityRegisterData": []
            }
        else:
            if str(entity_obj.get('requestId')) != str(row.requestID).strip():
                if request_packet_validation:
                    request_packet.append(entity_obj)
                request_packet_validation = True
                entity_obj = {
                    "requestId": str(row.requestID).strip(),
                    "channel": str(row.channel).strip(),
                    "hubId": str(row.hubId).strip(),
                    "idpId": str(row.idpId).strip(),
                    "totalEntityRequest": row.noOfEntities if row.noOfEntities and row.noOfEntities.isnumeric() else "0",
                    "totalIdentifiersRequest": row.noOfIdentifiers if row.noOfIdentifiers else "0",
                    "totalEntityCount": 0,
                    "totalIdentifiersCount": 0,
                    "entityRegisterData": []
                }
                entity_register_data = {}
                no_of_entity = 0
                no_of_identifiers = 0

        if str(row.entityCode).strip() and entity_register_data.get('entityCode', '') != str(
                row.entityCode).strip() or len(entity_register_data) == 0:
            entity_register_data = {
                "entityCode": str(row.entityCode).strip(),
                "totalIdentifiersRequest": 0,
                "entityIdentifierData": []
            }
            no_of_entity = no_of_entity + 1
            identifier_request = row.noOfIdentifiers if row.noOfIdentifiers and row.noOfIdentifiers.isnumeric() else 0
            total_identifier = entity_register_data.get('totalIdentifiersRequest') + int(identifier_request)
            entity_register_data.update({"totalIdentifiersRequest": total_identifier})

        if str(row.entityIdType).strip() or str(row.entityIdNo).strip() or str(row.entityIdName).strip() or str(
                row.ifsc):
            entity_identifier_data = {
                "entityIdType": str(row.entityIdType).strip(),
                "entityIdNo": str(row.entityIdNo).strip(),
                "entityIdName": str(row.entityIdName).strip(),
                "ifsc": str(row.ifsc).strip() if str(row.ifsc) else ""
            }
            entity_register_data.get('entityIdentifierData').append(entity_identifier_data)
            no_of_identifiers = no_of_identifiers + 1
            entity_obj.update({'totalIdentifiersCount': no_of_identifiers})

        if (entity_obj.get('channel').lower() != row.channel.lower().strip() or entity_obj.get('hubId').strip() !=
                row.hubId.strip() or entity_obj.get('idpId') != row.idpId.strip()):
            request_packet_validation = False

        if index == df.shape[0] - 1 and str(entity_obj.get('requestId')) == str(row.requestID).strip():
            if request_packet_validation:
                entity_obj.update({'totalEntityCount': no_of_entity})
                entity_obj.get('entityRegisterData').append(entity_register_data)
                request_packet.append(entity_obj)

            request_packet_validation = True

    logger.info(f"getting request packet {request_packet}")
    return request_packet


# READ CSV REGISTRATION WITH CODE
def read_csv_reg_with_ec():
    invoice_obj = {}
    ledger_data = []
    request_packet = []
    total_row_invoices = 0

    file_path = "/home/akhilesh/Downloads/dev%%abc%invoice_reg_with_entity_code%0015%veena%001%07032024%122000%3.csv"
    try:
        df = pd.read_csv(file_path, delimiter="|", dtype={'lenderCode': str})
        df = df.dropna(how='all')
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")

    hub_validation = True
    for index, row in df.iterrows():
        ledger_datas = ""
        if not invoice_obj:
            invoice_obj = {"requestId": str(row.requestID).strip(),
                           "sellerCode": str(row.sellerCode).strip(),
                           "buyerCode": str(row.buyerCode).strip(),
                           "sellerGst": str(row.sellerGst).strip(),
                           "buyerGst": str(row.buyerGst).strip(),
                           "groupingId": str(row.groupingId).strip(),
                           "total_invoice": row.noOfInvoices.strip() if row.noOfInvoices and row.noOfInvoices.isnumeric() else 0,
                           "channel": row.channel.strip(),
                           "hubId": row.hubId.strip(),
                           "idpId": row.idpId.strip()
                           }
        else:
            if str(invoice_obj.get('requestId')) != str(row.requestID).strip():
                if hub_validation:
                    request_packet.append(invoice_obj)
                hub_validation = True

                invoice_obj = {
                    "requestId": str(row.requestID).strip(),
                    "sellerCode": str(row.sellerCode).strip(),
                    "buyerCode": str(row.buyerCode).strip(),
                    "sellerGst": str(row.sellerGst).strip(),
                    "buyerGst": str(row.buyerGst).strip(),
                    "groupingId": str(row.groupingId).strip(),
                    "total_invoice": row.noOfInvoices.strip() if row.noOfInvoices and row.noOfInvoices.isnumeric() else 0,
                    "channel": row.channel.strip(),
                    "hubId": row.hubId.strip(),
                    "idpId": row.idpId.strip()
                }

                ledger_data = []
                total_row_invoices = 0

        gst_status = row.verifyGSTNFlag
        if row.verifyGSTNFlag == str(1):
            gst_status = True
        if row.verifyGSTNFlag == str(0):
            gst_status = False

        if str(row.invoiceNo).strip() or row.invoiceDate.strip() or str(
                row.invoiceAmt).strip() or gst_status or row.invoiceDueDate.strip():
            ledger_datas = {
                "invoiceNo": str(row.invoiceNo).strip(),
                "invoiceDate": row.invoiceDate.strip(),
                "invoiceAmt": str(row.invoiceAmt).strip(),
                "verifyGSTNFlag": gst_status,
                "invoiceDueDate": row.invoiceDueDate.strip(),
            }

            total_row_invoices = total_row_invoices + 1

        if ledger_datas:
            ledger_data.append(ledger_datas)

        if ledger_datas:
            invoice_obj.update({
                "ledgerData": ledger_data
            })
            if (invoice_obj.get('channel').lower() != row.channel.lower().strip() or invoice_obj.get(
                    'hubId').strip() != row.hubId.strip() or invoice_obj.get(
                'idpId') != row.idpId.strip() or invoice_obj.get('sellerCode').strip() != row.sellerCode.strip()
                    or invoice_obj.get('buyerCode').strip() != row.buyerCode.strip() or
                    invoice_obj.get('sellerGst').strip() != row.sellerGst.strip() or invoice_obj.get(
                        'buyerGst').strip() != row.buyerGst.strip()):
                hub_validation = False

            if index == df.shape[0] - 1 and str(invoice_obj.get('requestId')) == str(row.requestID):
                if hub_validation:
                    request_packet.append(invoice_obj)
                hub_validation = True

    logger.info(f"getting request packet {request_packet}")
    return request_packet


# READ CSV REGISTRATION WITH CODE AND FINANCING
def read_csv_reg_with_ec():
    invoice_obj = {}
    ledger_data = []
    finance_ledger_data = []
    request_packet = []
    total_row_invoices = 0
    total_invoice_request_count = 0

    file_path = "/home/akhilesh/Downloads/dev%%abc%invoice_reg_with_entity_code%0015%veena%001%07032024%122000%3.csv"
    try:
        df = pd.read_csv(file_path, delimiter="|", dtype=str, na_values='')
        df = df.replace(np.nan, '')
        # df = pd.read_csv(file_path, delimiter="|", dtype={'lenderCode': str})
        df = df.dropna(how='all')
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")

    hub_validation = True
    for index, row in df.iterrows():
        ledger_datas = ""
        if not invoice_obj:
            invoice_obj = {"requestId": str(row.requestID).strip(),
                           "sellerCode": str(row.sellerCode).strip(),
                           "buyerCode": str(row.buyerCode).strip(),
                           "sellerGst": str(row.sellerGst).strip(),
                           "buyerGst": str(row.buyerGst).strip(),
                           "groupingId": str(row.groupingId).strip(),
                           "total_invoice": row.noOfInvoices.strip() if row.noOfInvoices and row.noOfInvoices.isnumeric() else 0,
                           "channel": row.channel.strip(),
                           "hubId": row.hubId.strip(),
                           "idpId": row.idpId.strip()
                           }
        else:
            if str(invoice_obj.get('requestId')) != str(row.requestID).strip():
                if hub_validation:
                    request_packet.append(invoice_obj)
                hub_validation = True

                invoice_obj = {
                    "requestId": str(row.requestID).strip(),
                    "sellerCode": str(row.sellerCode).strip(),
                    "buyerCode": str(row.buyerCode).strip(),
                    "sellerGst": str(row.sellerGst).strip(),
                    "buyerGst": str(row.buyerGst).strip(),
                    "groupingId": str(row.groupingId).strip(),
                    "total_invoice": row.noOfInvoices.strip() if row.noOfInvoices and row.noOfInvoices.isnumeric() else 0,
                    "channel": row.channel.strip(),
                    "hubId": row.hubId.strip(),
                    "idpId": row.idpId.strip()
                }

                ledger_data = []
                total_row_invoices = 0

        gst_status = row.verifyGSTNFlag
        if row.verifyGSTNFlag == str(1):
            gst_status = True
        if row.verifyGSTNFlag == str(0):
            gst_status = False

        if str(row.invoiceNo).strip() or row.invoiceDate.strip() or str(
                row.invoiceAmt).strip() or gst_status or row.invoiceDueDate.strip():
            ledger_datas = {
                "invoiceNo": str(row.invoiceNo).strip(),
                "invoiceDate": row.invoiceDate.strip(),
                "invoiceAmt": str(row.invoiceAmt).strip(),
                "verifyGSTNFlag": gst_status,
                "invoiceDueDate": row.invoiceDueDate.strip(),
            }

            total_row_invoices = total_row_invoices + 1

        if ledger_datas:
            ledger_data.append(ledger_datas)

        if ledger_datas:
            invoice_obj.update({
                "ledgerData": ledger_data
            })
            if (invoice_obj.get('channel').lower() != row.channel.lower().strip() or invoice_obj.get(
                    'hubId').strip() != row.hubId.strip() or invoice_obj.get(
                'idpId') != row.idpId.strip() or invoice_obj.get('sellerCode').strip() != row.sellerCode.strip()
                    or invoice_obj.get('buyerCode').strip() != row.buyerCode.strip() or
                    invoice_obj.get('sellerGst').strip() != row.sellerGst.strip() or invoice_obj.get(
                        'buyerGst').strip() != row.buyerGst.strip()):
                hub_validation = False

            if index == df.shape[0] - 1 and str(invoice_obj.get('requestId')) == str(row.requestID):
                if hub_validation:
                    request_packet.append(invoice_obj)
                hub_validation = True

    logger.info(f"getting request packet {request_packet}")
    return request_packet


def cancel_read_csv():
    invoice_obj = {}
    request_packet = []

    file_path = "/home/lalita/Documents/A1SFTP/FTP/cancel.csv"
    try:
        df = pd.read_csv(file_path, delimiter="|", dtype=str, na_values='')
        df = df.replace(np.nan, '')
        print(df.to_string())
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")

    for index, row in df.iterrows():
        ######
        if not invoice_obj:
            invoice_obj = {"requestId": str(row.requestID),
                           "ledgerNo": str(row.ledgerNo),
                           "cancellationReason": str(row.cancellationReason),
                           }
        else:
            if str(invoice_obj.get('requestId')) != str(row.requestID):
                request_packet.append(invoice_obj)
                invoice_obj = {"requestId": str(row.requestID),
                               "ledgerNo": str(row.ledgerNo),
                               "cancellationReason": str(row.cancellationReason),
                               }
        #####
        if index == df.shape[0] - 1 and str(invoice_obj.get('requestId')) == str(row.requestID):
            request_packet.append(invoice_obj)

        invoice_obj.update({
            "channel": row.channel,
            "hubId": row.hubId,
            "idpId": row.idpId,
        })
        # logger.info(f" cancel data -------{invoice_obj}")

    logger.info(f"getting cancellation request packet {request_packet}")
    return request_packet


def create_bulk_request_log(db, request_id, request_data, response_data, flag, api_url='', merchant_key=None):
    try:
        api_request_obj = db.query(
            models.BulkAPIRequestLog
        ).filter(
            models.BulkAPIRequestLog.request_id == request_id
        ).first()
        logger.info(f"getting data iof api request log ################### {api_request_obj}")
        if flag == 'request':
            if api_request_obj:
                return {"requestId": request_id, **ErrorCodes.get_error_response(1009)}
            merchant_details = db.query(MerchantDetails).filter(MerchantDetails.merchant_key == merchant_key).first()
            if not merchant_details:
                return {
                    "requestId": request_data.get('requestId'),
                    **ErrorCodes.get_error_response(1002)
                }
            merchant_id = merchant_details.id if merchant_details else ''
            logger.info(f"merchant_id request log >>>>>>>>>>>>>>>>>>>>>> {merchant_id}")
            request_created = models.BulkAPIRequestLog(
                request_id=request_data.get('requestId'),
                request_data=request_data,
                api_url=api_url,
                merchant_id=str(merchant_id)
            )
            db.add(request_created)
            db.commit()
            db.refresh(request_created)
            return {"requestId": request_id, **ErrorCodes.get_error_response(200)}
        elif flag == 'response':
            api_request_obj.response_data = response_data
            api_request_obj.updated_at = datetime.now()
            db.commit()
            db.refresh(api_request_obj)
        else:
            api_request_obj.webhook_response = response_data
            api_request_obj.updated_at = datetime.now()
            db.commit()
            db.refresh(api_request_obj)
    except Exception as e:
        logger.error(f"getting error while creating request log >>>>>>>>>>>>>>> {e}")
        return {**ErrorCodes.get_error_response(500)}


def generate_encoded_rek():

    public_key_str = '''-----BEGIN PUBLIC KEY-----
    MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA6egQhYzgpuaJVu/USqAH
    5j8Zl1630uOlV2VcSeF3N567VFzDj2gf7FuSINHBNljPZW0PlUtnSoKRnhJTSZlS
    qyKO5gET6g5z3+LPflOVaPvi3l9GOgMawZnhRt4/Qx+xZwSgOZkPbfqoEnZuo26p
    B26BW+69IF9ITfLy/4eP2RHuORVs6qz/vZvCSGm+PpgfjcXIHkw8I0I4Ejc/7Eny
    UWWPOme5Q+BtmHhdJAFWULq1y5wLvBOJA2SCuD53lDN3S/6+jLZLpGrsPX463/dz
    mzu0wy/svAVQOwDwoxDqCGeTeXQCMUq9lNvZNPwymjUOoL3bhN8PPNUSDQPEysPM
    ewIDAQAB
    -----END PUBLIC KEY-----'''

    public_key = serialization.load_pem_public_key(public_key_str.encode(), backend=default_backend())

    rek = get_random_string()

    # Convert the string to bytes
    data = rek.encode('utf-8')

    # Load or generate your RSA public key
    # Example loading from a PEM file
    # with open("public_key.pem", "rb") as key_file:
    #     public_key = serialization.load_pem_public_key(
    #         key_file.read(),
    #         backend=default_backend()
    #     )

    # PKCS7 Padding
    padder = padding.PKCS7(256).padder()
    padded_data = padder.update(data) + padder.finalize()

    # Perform RSA encryption
    encrypted_data = public_key.encrypt(
        padded_data,
        asymmetric_padding.OAEP(
            mgf=asymmetric_padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )

    # Base64 encode the encrypted data for easier transport
    encrypted_data_base64 = base64.b64encode(encrypted_data).decode('utf-8')

    print("Encrypted Data (Base64):", encrypted_data_base64)

    return encrypted_data_base64


def aes_ecb_encrypt_password(key, plaintext):
    backend = default_backend()
    cipher = Cipher(algorithms.AES(key), modes.ECB(), backend=backend)
    encryptor = cipher.encryptor()
    padder = PKCS7(algorithms.AES.block_size).padder()
    padded_data = padder.update(plaintext) + padder.finalize()
    ciphertext = encryptor.update(padded_data) + encryptor.finalize()
    return base64.b64encode(ciphertext)


# validation service for invoice, invoice date, amount
def remove_numbers(invoice_number):
    # Use regular expression to remove numeric characters
    return re.sub(r'\d', '', invoice_number)


def check_invoice_suffix(invoice_data):
    # from datetime import datetime
    invoice_suffix_num = [sub['invoiceNo'] for sub in invoice_data.get('ledgerData')]
    invoice_suffix_number = sorted(invoice_suffix_num)
    logger.info(f"invoice_suffix_number >>>>> {invoice_suffix_number}")
    if len(invoice_suffix_number) == 1:
        logger.info(f"only one data here")
        return True

    first_invoice_suffix = remove_numbers(invoice_suffix_number[0])
    for invoice_number in invoice_suffix_number[1:]:
        suffix = remove_numbers(invoice_number)
        if suffix != first_invoice_suffix:
            logger.info(f"suffix must be start with >>>> {first_invoice_suffix}")
            return False
    return True

def check_inv_date(data):
    date_list = [sub['invoiceDate'] for sub in data.get('ledgerData')]
    dates = [datetime.strptime(date, '%d/%m/%Y') for date in date_list]
    if len(dates) == 1:
        logger.info(f"only one invoice date here")
        return True

    print(f"getting date list >>>>>>>>>>>>>>>>>>{dates}")
    previous_date = dates[0]

    for date in dates[1:]:
        # if date <= previous_date:
        if previous_date > date:
            return False
        else:
            return True
        previous_date = date


# check invoice number remove special character
# def invoice_number_remove_spcl_chr(invoice_data):
#     import re
#     pattern = re.compile(r'[^\w\s]')
#     invoice_num = [sub['invoiceNo'] for sub in invoice_data.get('ledgerData')]
#     cleaned_invoice_num = [pattern.sub('', value) for value in invoice_num]
#     print(f"invoice number ---- {cleaned_invoice_num}")
#
#     return cleaned_invoice_num


def duplicate_inv_no(db, invoice_data):
    # from datetime import datetime
    invoice_num = [sub['invoiceNo'] for sub in invoice_data.get('ledgerData')]
    invoice_number = sorted(invoice_num)

    # first_invoice_suffix = remove_numbers(invoice_number[0])
    for invoice_no in invoice_number:
        # suffix = remove_numbers(invoice_number)
        invoice_obj = db.query(models.Invoice).filter(
            models.Invoice.extra_data.contains({"seller_gst": invoice_data.get('sellerGst')}),
            models.Invoice.invoice_no == invoice_no
        ).first()
        if invoice_obj:
            # return True, invoice_obj.invoice_no
            return True
        else:
            return False


# def special_chr_remove_inv_no(db, invoice_data):
#     import re
#     pattern = re.compile(r'[^\w\s]')
#     invoice_num = [sub['invoiceNo'] for sub in invoice_data.get('ledgerData')]
#     cleaned_invoice_num = [pattern.sub('', value) for value in invoice_num]
#     print(f"invoice number ---- {cleaned_invoice_num}")
#
#     invoice_obj = db.query(models.Invoice).all()
#     if invoice_obj:
#
#         invoice = []
#         for invoice_num in invoice_obj:
#             print(f"invoice number >>>>> --- {invoice_num.invoice_no}")
#             # update_data = {
#             #     "invoice_number": invoice_num.invoice_no,
#             #     "invoice_amt": invoice_num.invoice_amt,
#             #     "spcl_rem_invoice_no": pattern.sub('', invoice_num.invoice_no)
#             # }
#             # invoice.append(pattern.sub('', invoice_num.invoice_no))
#             invoice.append(invoice_num.invoice_no)
#         logger.info(f"invoice_num --- {invoice}")
#     # ------count and remove special character
#     from collections import Counter
#     element_counts = Counter([pattern.sub('', string) for string in invoice])
#
#     # Filter elements with counts greater than 1 (duplicates)
#     duplicates = {key: value for key, value in element_counts.items() if value > 1}
#
#     def check_key_in_list(duplicates, lst):
#         for key in dictionary.keys():
#             if key in lst:
#                 return True
#         return False
#
#     # if duplicates:
#     #     return True
#     # return False
#
#     print("Duplicate elements and their counts:")
#     print(duplicates)
#     # -----------------------
#     request_inv_no = list(set(cleaned_invoice_num))
#     record_inv_no = invoice
#
#     request_packat = {
#         'disburse_request_packet': list(set(cleaned_invoice_num)),
#         'repayment_request_packet': invoice
#     }
#     logger.info(f"request_packat request_packatrequest_packa --- {request_packat}")
#


class SpecialCharRemove:

    @staticmethod
    def special_chr_remove_inv_no(db, invoice_data, merchant_key=None):
        merchant_obj = db.query(models.MerchantDetails).filter(
            models.MerchantDetails.merchant_key == merchant_key).first()

        import re
        # pattern = re.compile(r'[^\w\s]')
        pattern = re.compile(r'[-_!@#$%^&*()+={}[\]:;"\'|<,>.?/\\\s]')
        invoice_num = [sub['invoiceNo'] for sub in invoice_data.get('ledgerData')]
        cleaned_invoice_num = [pattern.sub('', value) for value in invoice_num]
        logger.info(f"invoice number ---- {cleaned_invoice_num}")

        invoice_obj = (db.query(models.Invoice).filter(
            models.Invoice.extra_data.contains({"seller_gst": invoice_data.get('sellerGst')}),
        ).all())
        if invoice_obj:
            invoice = []
            for invoice_num in invoice_obj:
                if merchant_obj.id in invoice_num.extra_data.get('register_merchant_id'):
                    invoice.append(invoice_num.invoice_no)

        else:
            # return_response = {**ErrorCodes.get_error_response(1043)}
            return_response = {"requestId": invoice_data.get('requestId'), **ErrorCodes.get_error_response(200)}
            return return_response
        # count and remove special character
        from collections import Counter
        element_counts = Counter([pattern.sub('', string) for string in invoice])

        logger.info(f"element_counts >>>> {element_counts}")

        # Filter elements with counts greater than 1 (duplicates)
        duplicates = {key: value for key, value in element_counts.items() if value > 1}
        clean_invoice_num = list(set(cleaned_invoice_num))

        logger.info(f"duplicates >>>> {duplicates}")

        # check duplicate from invoice present in db
        check_invoice_number_response = SpecialCharRemove.check_key_in_list(invoice_data, duplicates, clean_invoice_num)
        if check_invoice_number_response:
            # return {"requestId": invoice_data.get('requestId'), **ErrorCodes.get_error_response(1141)}
            return_response = {**ErrorCodes.get_error_response(1141)}

        else:
            logger.info("another operation perform >>>>")
            check_invoice_amount_response = SpecialCharRemove.check_invoice_amount(db, duplicates, invoice_data, merchant_obj)
            if not check_invoice_amount_response:
                return_response = {**ErrorCodes.get_error_response(1142)}
            else:
                return_response = {**ErrorCodes.get_error_response(200)}

        return return_response

    @staticmethod
    def check_key_in_list(request_data, duplicates, lst):
        for key in duplicates.keys():
            if key in lst:
                return True
        return False


# old one amount check case with sellergst below
    # @staticmethod
    # def check_invoice_amount(db, invoice_data, merchant_obj):
    #     from decimal import Decimal
    #     import re
    #     # pattern = re.compile(r'[^\w\s]')
    #     pattern = re.compile(r'[-_!@#$%^&*()+={}[\]:;"\'|<,>.?/\\\s]')
    #
    #     for request_datas in invoice_data.get('ledgerData'):
    #         invoice_amt_obj = (db.query(models.Invoice).filter(
    #             # models.Invoice.extra_data.contains({"seller_gst": invoice_data.get('sellerGst')}),
    #             models.Invoice.invoice_no == request_datas.get('invoiceNo')
    #         ).first())
    #
    #         if invoice_amt_obj:
    #             logger.info(f"invoice number get{invoice_amt_obj.invoice_no}>>>>{invoice_amt_obj.invoice_amt}")
    #             # check invoice amount with record invoice amount
    #             if merchant_obj.id in invoice_amt_obj.extra_data.get('register_merchant_id'):
    #                 record_amount = invoice_amt_obj.invoice_amt
    #                 # if request_datas.get('invoiceNo') == invoice_amt_obj.invoice_no:  #old one
    #                 # special chr remove from number
    #                 requested_inv = pattern.sub('', request_datas.get('invoiceNo'))
    #                 recorded_inv = pattern.sub('', invoice_amt_obj.invoice_no)
    #                 if requested_inv == recorded_inv:
    #                     if Decimal(request_datas.get('invoiceAmt')) >= record_amount:
    #                         logger.info(f"amount >>>> {request_datas.get('invoiceAmt')} >>>> {record_amount}")
    #                         return True
    #                     else:
    #                         logger.info(f"amount not correct >>>> {request_datas.get('invoiceAmt')} >>>> {record_amount}")
    #                         return False
    #                 #not match invoice case
    #                 else:
    #                     return True
    #         else:
    #             return True
    #     return False

    @staticmethod
    def check_invoice_amount(db, duplicate_data, invoice_data, merchant_obj):
        from decimal import Decimal
        import re
        # pattern = re.compile(r'[^\w\s]')
        pattern = re.compile(r'[-_!@#$%^&*()+={}[\]:;"\'|<,>.?/\\\s]')

        for request_datas in invoice_data.get('ledgerData'):
            invoice_amt_obj = (db.query(models.Invoice).filter(
                models.Invoice.extra_data.contains({"seller_gst": invoice_data.get('sellerGst')}),
                # models.Invoice.invoice_no == request_datas.get('invoiceNo')
            ).order_by(
                desc(models.Invoice.id)
            ).first())

            # new invoice number check with duplicate_data invoice no is present or not
            value_to_match = request_datas.get('invoiceNo')
            for key, value in duplicate_data.items():
                if key != value_to_match:
                    logger.info(f"Key '{key}' matches the value {value_to_match}")
                    return True

            if invoice_amt_obj:
                logger.info(f"invoice number get{invoice_amt_obj.invoice_no}>>>>{invoice_amt_obj.invoice_amt}")
                # check invoice amount with record invoice amount
                if merchant_obj.id in invoice_amt_obj.extra_data.get('register_merchant_id'):
                    record_amount = invoice_amt_obj.invoice_amt
                    # if request_datas.get('invoiceNo') == invoice_amt_obj.invoice_no:  #old one
                    # special chr remove from number
                    # requested_inv = pattern.sub('', request_datas.get('invoiceNo'))
                    # recorded_inv = pattern.sub('', invoice_amt_obj.invoice_no)
                    # if requested_inv == recorded_inv:
                    if Decimal(request_datas.get('invoiceAmt')) >= record_amount:
                        logger.info(f"amount >>>> {request_datas.get('invoiceAmt')} >>>> {record_amount}")
                        return True
                    else:
                        logger.info(f"amount not correct >>>> {request_datas.get('invoiceAmt')} >>>> {record_amount}")
                        return False
                    #not match invoice case
                    # else:
                    #     return True
            else:
                return True
        return True


def check_bulk_inv_date(data):
    invoice_dates = []
    for group in data['groupData']:
        for ledger in group['ledgerData']:
            invoice_dates.append(ledger['invoiceDate'])
            logger.info(f"bulk invoice date >>>> {invoice_dates}")

    dates = [datetime.strptime(date, '%d/%m/%Y') for date in invoice_dates]
    if len(dates) == 1:
        logger.info(f"only one invoice date here")
        return True

    previous_date = dates[0]

    for date in dates[1:]:
        # if date <= previous_date:
        if previous_date > date:
            return False
        else:
            return True
        previous_date = date


def generate_unique_string(length=40):
    # Define the character set (alphanumeric)
    characters = string.ascii_letters + string.digits

    # Generate a random string
    random_string = ''.join(secrets.choice(characters) for _ in range(length))

    # Append a timestamp to ensure uniqueness
    timestamp = str(int(time.time()))  # Current Unix timestamp as string
    unique_string = random_string[:length - len(timestamp)] + timestamp

    return unique_string[:length]  # Trim to desired length (max 40)


# Generate Reference id for otp
class GeneratetransactionRef:

    def random_with_N_digits(self, n=5):
        """Generate random no"""
        range_start = 10 ** (n - 1)
        range_end = (10 ** n) - 1
        return randint(range_start, range_end)

    def get_transaction_ref(self, dev_id="", dev_type=""):
        """Calculate transaction Reference"""

        ref = hex(int(1000 * (time.time() - 10 ** 9)))[-10:]
        random_ref = hex(self.random_with_N_digits(3))[-3:]

        # EnsureDevice Id to be numberic in requests
        device_ref = str(dev_id).encode('utf-8').hex().zfill(6)[-6:]

        transaction_ref = ref + random_ref + device_ref
        return transaction_ref


class OTPGenerateVerify:

    @staticmethod
    def verify_otp(mobile, reference_id, otp):
        logger.info("***** Inside the verify OTP *****")
        otp_cache_obj = OTPCache(mobile_no=mobile, reference_id=reference_id)
        otp_validation_resp = otp_cache_obj.validate_otp(otp_to_validate=otp)
        if otp_validation_resp.get('responseCode') == 200:
            otp_cache_obj.delete()
        logger.info(f"********* getting response from verify otp {otp_validation_resp} **********")
        return otp_validation_resp

    @staticmethod
    def delete_otp(mobile, reference_id, otp):
        logger.info("***** Inside the delete OTP *****")
        otp_cache_obj = OTPCache(mobile_no=mobile, reference_id=reference_id)
        otp_del_resp = otp_cache_obj.delete()
        logger.info(f"********* getting response from delete otp {otp_del_resp} **********")



class OTPCache:
    # from fastapi_cache.decorator import cache
    PREFIX = "OTP"
    TTL = 60 * 5  # 5 minutes

    def __init__(self, mobile_no: str, reference_id: str, otp_to_send: str = None):
        self.mobile_no = mobile_no
        self.reference_id = reference_id
        self.otp_to_send = otp_to_send

    @property
    def key(self):
        return ":".join([self.PREFIX, self.mobile_no, self.reference_id])

    def set(self):
        assert self.otp_to_send, "Attribute `otp_to_send` must be provided when setting the OTP."
        r.set(self.key, self.otp_to_send, self.TTL)

    def get(self):
        return r.get(self.key)

    def delete(self):
        return r.delete(self.key)

    def validate_otp(self, otp_to_validate: str):
        cached_otp = self.get()
        if cached_otp and cached_otp != otp_to_validate:
            return ErrorCodes.get_error_response(1143)
        elif not cached_otp:
            return ErrorCodes.get_error_response(1144)
        else:
            return ErrorCodes.get_error_response(200)


class GenerateToken:
    @staticmethod
    def generate_unique_str(username):
        token19 = GeneratetransactionRef().get_transaction_ref(username)
        token16 = GeneratetransactionRef().random_with_N_digits(16)
        token = str(token19)+str(token16)
        return token

    @staticmethod
    def create_token(db, username):
        token = GenerateToken.generate_unique_str(username)
        try:

            user_set = db.query(models.UserAuth).filter(
                models.UserAuth.user_id == str(username)).first()
            if user_set:
                user = user_set
                user.user_token = token
                db.commit()
                db.refresh(user)
                return user.user_token
            else:
                user = models.UserAuth(
                    user_id=username,
                    user_token=token
                )
                db.add(user)
                db.commit()
                db.refresh(user)
                return user.user_token
        except Exception as e:
            logger.info("Token Creation Failed Due to===>{}".format(e))
            return False


def validate_gst_pan(request_data):
    logger.info(request_data)
    gst_data = request_data.get('gstin')
    pan_data = request_data.get('pan')
    if pan_data and gst_data:
        derived_pan = gst_data[2:12]
        if derived_pan != pan_data:
            return True
        else:
            return False

    return False

def generate_voucher_code(length=12):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

# Create Vouchers
def create_vouchers(db: Session, user_id: str, quantity: int, value: float):
    vouchers = []
    for _ in range(quantity):
        voucher_code = generate_voucher_code()
        voucher = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "code": voucher_code,
            "value": value,
            "created_at": datetime.now(),
            "is_used": False
        }
        vouchers.append(voucher)
        # Saves voucher to the database
        db.execute(
            models.Voucher.__table__.insert(),
            voucher
        )
    
    db.commit()
    
    # Check if user has fewer than 10 vouchers left after creating new ones
    voucher_count = db.query(models.Voucher).filter(
        models.Voucher.user_id == user_id,
        models.Voucher.is_used == False
    ).count()
    
    if voucher_count < 10:
        # Notify the user
        # Here you could add the code to send a notification, e.g., email, SMS, etc.
        logger.info(f"User {user_id} has fewer than 10 vouchers left.")
    
    return vouchers

# Use Vouchers
def use_vouchers(db: Session, user_id: str, amount: float):
    # Fetch available vouchers for the user
    vouchers = db.query(models.Voucher).filter(
        models.Voucher.user_id == user_id,
        models.Voucher.is_used == False
    ).order_by(models.Voucher.created_at.asc()).all()
    
    if not vouchers:
        raise HTTPException(status_code=400, detail="No vouchers available.")
    
    total_value = sum(voucher.value for voucher in vouchers)
    
    if total_value < amount:
        raise HTTPException(status_code=400, detail="Not enough voucher value available.")
    
    used_vouchers = []
    remaining_amount = amount
    
    for voucher in vouchers:
        if remaining_amount <= 0:
            break
        
        if voucher.value <= remaining_amount:
            remaining_amount -= voucher.value
            voucher.is_used = True
            used_vouchers.append(voucher)
        else:
            voucher.value -= remaining_amount
            remaining_amount = 0
            used_vouchers.append(voucher)
    
    # Update vouchers in the database
    for voucher in used_vouchers:
        db.query(models.Voucher).filter(models.Voucher.id == voucher.id).update({"is_used": voucher.is_used, "value": voucher.value})
    
    db.commit()
    
    # Check if user has fewer than 10 vouchers left after using some
    voucher_count = db.query(models.Voucher).filter(
        models.Voucher.user_id == user_id,
        models.Voucher.is_used == False
    ).count()
    
    if voucher_count < 10:
        # Notify the user
        logger.info(f"User {user_id} has fewer than 10 vouchers left.")
    
    return used_vouchers

# gsp user duplicate corporate name and phone number check
def gsp_user_name_phone_no(db, request_data):
    gsp_name = db.query(
        models.GSPUserDetails
    ).filter(
        models.GSPUserDetails.name == request_data.get('name')
    ).first()

    derived_pan = request_data.get('gstin')[2:12]
    if gsp_name and str(gsp_name.pan) != derived_pan:
        response_data = {
            **ErrorCodes.get_error_response(1147)
        }
        return response_data
    logger.info(f"duplcate name not found")

    gsp_phone_obj = db.query(
        models.GSPUserDetails
    ).filter(
        models.GSPUserDetails.mobile_number == request_data.get('mobileNumber')
    ).first()
    if gsp_phone_obj and str(gsp_phone_obj.gstin) != request_data.get('gstin'):
        response_data = {
            **ErrorCodes.get_error_response(1148)
        }
        return response_data
    logger.info(f"duplicate number not found")
    response_data = {**ErrorCodes.get_error_response(200)}
    return response_data
