import logging
import traceback

import redis
import ast
import datetime
import pytz
import hashlib
import copy

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from decouple import config as dconfig
from sqlalchemy import text
import models
import utils
from errors import ErrorCodes
from models import LenderInvoiceAssociation
from utils import InvoiceStatus

# logging.basicConfig('logging.conf')
logger = logging.getLogger(__name__)
r = redis.Redis(host=dconfig('REDIS_HOST'), port=6379, decode_responses=True)


class Registration:
    @staticmethod
    def create_invoice(db, invoice, merchant_obj, financial_year):
        try:
            logger.info(f"getting invoice data @@@@@@@@@@ {invoice}")
            ledger_create = models.Ledger(
                merchant_id=merchant_obj.id,
                invoice_count=len(invoice.get('ledgerData')),
            )
            db.add(ledger_create)
            db.commit()
            db.refresh(ledger_create)
            asia_kolkata = pytz.timezone('Asia/Kolkata')
            today_date = datetime.datetime.now(asia_kolkata).strftime("%d%m%Y%H%M%S")
            ledger_id = str(merchant_obj.id) + str(today_date) + str(ledger_create.id)

            # Update Ledger for ledger id
            ledger_create.ledger_id = ledger_id,
            db.commit()
            db.refresh(ledger_create)

            logger.info(f"getting ledger created id >>>>>>>>>>>>>>>>>>>.. {ledger_create.id}")

            # Add Invoices Get Invoice All Invoice Ids Return
            invoice_id_response = Registration.get_invoice_ids(
                db,
                invoice.get('ledgerData'),
                ledger_create,
                merchant_obj.merchant_secret,
                financial_year
            )
            # invoice_id_response = invoice_id_unsorted
            logger.info(f"getting invoice ids @@@@@@@@@@@@@ {invoice_id_response}")

            # Join Ids with pip and create ledger hash
            con_invoice_ids = '|'.join(invoice_id_response)
            ledger_hash = utils.create_ledger_hash(con_invoice_ids, merchant_obj.merchant_secret)
            logger.info(f"Ledger Hash Data :: \n {ledger_hash}")

            # Validate Ledger Hash
            validate_response = Registration.validate_ledger_hash(db, ledger_hash)
            logger.info(f"getting ************ {validate_response}")
            if not validate_response:
                ledger_create.ledger_hash = ledger_hash,
                db.commit()
                db.refresh(ledger_create)
                return_response = {
                    "requestId": invoice.get('requestId'),
                    "ledgerNo": ledger_create.ledger_id,
                    **ErrorCodes.get_error_response(200)
                }
            else:
                ledger_query = db.query(models.Ledger).filter(
                    models.Ledger.ledger_id == ledger_create.ledger_id
                ).first()
                db.delete(ledger_query)
                db.commit()
                return_response = {
                    "requestId": invoice.get('requestId'),
                    "ledgerNo": "",
                    **ErrorCodes.get_error_response(1003)
                }
            response_hash = utils.create_ledger_hash(return_response, merchant_obj.merchant_secret)
            return_response.update({"signature": response_hash})
            return return_response

        except Exception as e:
            logger.info(f"getting error >>>>>>>>>>>>>>. {e}")
            raise HTTPException(
                status_code=500,
                detail=f"getting error while create student {e}"
            )

    @staticmethod
    def get_invoice_ids(db, invoice_data, ledger_obj, merchant_key, financial_year):
        logger.info(f"getting invoice data >>>>>>>>>>>>>>>>>>>.. {invoice_data}")
        invoice_ids = []
        for invoice_datas in invoice_data:
            parsed_date = datetime.datetime.strptime(invoice_datas.get('invoiceDate'), '%d/%m/%Y')
            logger.info(f"getting parsed date {parsed_date}")
            # invoices = db.query(models.Invoice).filter(
            #     models.Invoice.invoice_no == invoice_datas.get('invoiceNo'),
            #     models.Invoice.invoice_date == invoice_datas.get('invoiceDate'),
            #     models.Invoice.invoice_amt == invoice_datas.get('invoiceAmt'),
            #     # models.Invoice.buyer_gst == invoice_datas.get('buyerGST'),
            #     # models.Invoice.seller_gst == invoice_datas.get('sellerGST')
            # ).first()
            seller_id_no = ''
            buyer_id_no = ''
            for seller_data in invoice_datas.get('selleridentifierdata'):
                if not seller_id_no and seller_data.get('sellerIdType') == 'GSTIN':
                    seller_id_no = seller_data.get('sellerIdNo')

            for buyer_data in invoice_datas.get('buyeridentifierdata'):
                if not buyer_id_no and buyer_data.get('buyerIdType') == 'GSTIN':
                    buyer_id_no = buyer_data.get('buyerIdNo')

            logger.info(f"getting seller id ????????????? {seller_id_no}")
            logger.info(f"getting buyer id ????????????????????? {buyer_id_no}")
            query = """
                        select
                        i.id
                    from
                        invoice i ,
                        lateral jsonb_to_recordset(extra_data->'buyerIdentifierData') as x("buyerIdNo" text,
                        "buyerIdType" text),
                        lateral jsonb_to_recordset(extra_data->'sellerIdentifierData') as y("sellerIdNo" text,
                        "sellerIdType" text)
                    where
                        i.invoice_no = :invoice_no
                        and y."sellerIdNo" = :seller_id_no
                        and x."buyerIdNo" = :buyer_id_no'
                        and x."buyerIdType" = 'GSTN'
                        and y."sellerIdType" = 'GSTIN'
                        and i.invoice_date = :parsed_date
                        and i.invoice_amt = :invoice_amt 
                        and (i.financial_year = :financial_year 
                        or i.time_created >= NOW() - INTERVAL '180 days' AND i.invoice_date::timestamp <= NOW());
                       """
            invoices = db.execute(text(query),
                                  [{'invoice_no': invoice_datas.get('invoiceNo'),
                                    'seller_id_no': seller_id_no,
                                    'buyer_id_no': buyer_id_no,
                                    'parsed_date': parsed_date,
                                    'invoice_amt': invoice_datas.get('invoiceAmt'),
                                    'financial_year': financial_year
                                    }]
                                  ).first()
            logger.info(f"getting invoices $$$$$$$$$$$$$$$$$$$$ {invoices}")
            if not invoices:
                logger.info(f">>>>>>>>>>>>>>>>> getting inside if means invoice not found <<<<<<<<<<<<< ")
                extra_data = {
                    "sellerIdentifierData": invoice_datas.get('selleridentifierdata'),
                    "buyerIdentifierData": invoice_datas.get('buyeridentifierdata')
                }
                invoice_hash = utils.create_signature(invoice_datas, merchant_key)
                invoice_create = models.Invoice(
                    invoice_no=invoice_datas.get('invoiceNo'),
                    invoice_date=parsed_date,
                    invoice_amt=invoice_datas.get('invoiceAmt'),
                    invoice_hash=invoice_hash,
                    financial_year=financial_year,
                    extra_data=extra_data
                )
                db.add(invoice_create)
                db.commit()
                db.refresh(invoice_create)
                invoice_ids.append(str(invoice_create.id))

                invoice_create.ledger.append(ledger_obj)

                db.commit()
                db.refresh(invoice_create)
            else:
                logger.info(f"getting inside else means invoice found >>>>>>>>>>>>>> <<<<<<<<<<<<< {invoices.id}")
                invoice_query = db.query(models.Invoice).filter(
                    models.Invoice.id == invoices.id
                ).first()

                query = """
                            select
                                 ila.*
                            from
                                invoice_ledger_association ila
                            where
                                ila.ledger_id = :ledger_id and ila.invoice_id = :inv_id
                            ;
                        """
                invoice_ledger_data = db.execute(text(query),
                                                 [{'ledger_id': ledger_obj.id, 'inv_id': invoices.id}]
                                                 ).first()
                if not invoice_ledger_data:
                    invoice_query.ledger.append(ledger_obj)
                    db.commit()
                    db.refresh(invoice_query)

                logger.info(f"getting {type(invoices.id)}")
                invoice_ids.append(str(invoices.id))

        return invoice_ids

    @staticmethod
    def validate_ledger_hash(db, ledger_hash):
        logger.info(f"getting leder hash $$$$$$$$$$$$$ {ledger_hash}")
        ledger_obj = db.query(models.Ledger).filter(
            models.Ledger.ledger_hash == ledger_hash
        ).first()
        logger.info(f"getting ledger hash {ledger_obj}")
        if ledger_obj:
            return True
        else:
            return False


class StatusCheck:
    @staticmethod
    def ledger_status(db, ledger_parm, merchant_obj):
        try:
            check_response = check_ledger(db, ledger_parm.ledgerNo, ledger_parm.requestId, merchant_obj.id)
            logger.info(f"getting ledger data check response {check_response}")
            if check_response.get('code') == 200:

                query = """
                                select
                                array_agg(i.fund_status) as fund_stat
                            from
                                invoice_ledger_association ila
                            inner join ledger l on
                                ila.ledger_id = l.id
                            inner join invoice i on
                                ila.invoice_id = i.id
                            where
                                l.ledger_id = :ledger_no
                            """
                invoice_status = db.execute(text(query), [{'ledger_no': ledger_parm.ledgerNo}]).first()
                logger.info(f"getting all status >>>>>>>>>>>>>>>>. {invoice_status[0]}")
                # status = []
                # for invoice_status in all_data:
                #     status.append(invoice_status.fund_status)

                # logger.info(f"%%%%%%%%%%%%%%%%%%%%%%% {status}")
                if True in invoice_status[0]:
                    return_response = {
                        "requestId": ledger_parm.requestId,
                        "ledgerNo": ledger_parm.ledgerNo,
                        **ErrorCodes.get_error_response(1004)
                    }
                else:
                    return_response = {
                        "requestId": ledger_parm.requestId,
                        "ledgerNo": ledger_parm.ledgerNo,
                        **ErrorCodes.get_error_response(1005)
                    }
            else:
                return_response = check_response

            response_hash = utils.create_ledger_hash(return_response, merchant_obj.merchant_secret)
            return_response.update({"signature": response_hash})
            return return_response
        except Exception as e:
            print(f"getting error while create student {e}")


class Financing:
    @staticmethod
    def check_invoice(db, request_data, financial_year):
        logger.info(f" >>>>>>>>>>>>>> getting inside check invoice >>>>>>>>>>>>>>>>> ")
        json_request = jsonable_encoder(request_data)
        query = """
                                select
                                array_agg(i.fund_status) as fund_stat, count(i.id) as invoice_count
                            from
                                invoice_ledger_association ila
                            inner join ledger l on
                                ila.ledger_id = l.id
                            inner join invoice i on
                                ila.invoice_id = i.id
                            where
                                l.ledger_id = :ledger_no
                            """
        invoice_data_status = db.execute(text(query), [{'ledger_no': json_request.get('ledgerNo')}]).first()

        logger.info(f" >>>>>>>>> ledger request length &&&& {len(json_request.get('ledgerData'))} >>>>>>>> ")
        logger.info(f" >>>>>>>>>>>>>> getting invoice count for ledger &&&&& {invoice_data_status.invoice_count}>>>>>>>>>>>>>>>>> ")
        if len(json_request.get('ledgerData')) == invoice_data_status.invoice_count:
            # all_datas = db.query(
            #     models.Invoice
            # ).join(models.Ledger).where(
            #     models.Invoice.ledger_id == json_request.get('ledgerNo')
            # ).all()

            query = """
                        select
                        array_agg(i.fund_status) as fund_stat
                    from
                        invoice_ledger_association ila
                    inner join ledger l on
                        ila.ledger_id = l.id
                    inner join invoice i on
                        ila.invoice_id = i.id
                    where
                        l.ledger_id = :ledger_no
                    ;
                    """
            invoice_status = db.execute(text(query), [{'ledger_no': json_request.get('ledgerNo')}]).first()
            logger.info(f"getting all status >>>>>>>>>>>>>>>>. {invoice_status.fund_stat}")

            # print(f"getting all_data >>>>>>>>>>>>>>>>>>>> {all_datas}")
            # status = []
            for ledger_data in json_request.get('ledgerData'):
                logger.info(f"getting data >>>>>>>>>>>. {json_request.get('ledgerNo')} >>>>>>>>>>> "
                            f"{ledger_data.get('invoiceNo')} >>>>>>>>>>>>>. {ledger_data.get('fundingAmt')}")
                # all_data = db.query(
                #     models.Invoice
                # ).filter(
                #     models.Invoice.ledger_id == json_request.get('ledgerNo'),
                #     models.Invoice.invoice_no == ledger_data.get('invoiceNo'),
                #     models.Invoice.invoice_amt == ledger_data.get('fundingAmt')
                # ).first()
                query = """
                            select
                                i.*
                            from
                                invoice_ledger_association ila
                            inner join ledger l on
                                ila.ledger_id = l.id
                            inner join invoice i on
                                ila.invoice_id = i.id
                            where
                                l.ledger_id  = :ledger_no and
                                i.invoice_no = :invoice_no and 
                                i.invoice_amt = :funding_amt and 
                                (i.financial_year = :financial_year 
                                or i.time_created >= NOW() - INTERVAL '180 days' AND i.invoice_date <= NOW());
                        """

                invoice_data = db.execute(text(query),
                                          [{'ledger_no': json_request.get('ledgerNo'),
                                            'invoice_no': ledger_data.get('invoiceNo'),
                                            'funding_amt': ledger_data.get('fundingAmt'),
                                            'financial_year': financial_year
                                            }]
                                          ).first()
                logger.info(f" >>>>> getting all data for {ledger_data.get('invoiceNo')} >>>> {invoice_data}")
                if not invoice_data:
                    return {"requestId": json_request.get('requestId'), **ErrorCodes.get_error_response(1011)}

            # for invoice_status in all_datas:
            #     status.append(invoice_status.fund_status)

            if True in invoice_data_status[0]:
                return {"requestId": json_request.get('requestId'), **ErrorCodes.get_error_response(1004)}

            for ledger_data in json_request.get('ledgerData'):
                # all_datas = db.query(
                #     models.Invoice
                # ).filter(
                #     models.Invoice.ledger_id == json_request.get('ledgerNo'),
                #     models.Invoice.invoice_no == ledger_data.get('invoiceNo'),
                #     models.Invoice.invoice_amt == ledger_data.get('fundingAmt'),
                # ).first()

                query = """
                        select
                            i.*
                        from
                            invoice_ledger_association ila
                        inner join ledger l on
                            ila.ledger_id = l.id
                        inner join invoice i on
                            ila.invoice_id = i.id
                        where
                            l.ledger_id  = :ledger_no and
                            i.invoice_no = :invoice_no and 
                            i.invoice_amt = :funding_amt
                        ;
                        """

                invoice_data = db.execute(text(query),
                                          [{'ledger_no': json_request.get('ledgerNo'),
                                            'invoice_no': ledger_data.get('invoiceNo'),
                                            'funding_amt': ledger_data.get('fundingAmt')
                                            }]
                                          ).first()
                logger.info(f"getting id {invoice_data.id}")
                fund_status = True
                update_query = "UPDATE invoice SET fund_status = :fund_status, funded_amt = :funding_amt WHERE id = :inv_id;"
                print(update_query)
                db.execute(text(update_query),
                           [{'fund_status': fund_status,
                             'funding_amt': ledger_data.get('fundingAmt'),
                             'inv_id': invoice_data.id
                             }]
                           )
                db.commit()
                # all_datas.fund_status = True
                # all_datas.funded_amt = ledger_data.get('fundingAmt'),
                # all_datas.extra_data = all_datas.extra_data.update({"financeData": ledger_data})
                # db.commit()
                # db.refresh(all_data)

            return {"code": 200}
        else:
            return {"requestId": json_request.get('requestId'), **ErrorCodes.get_error_response(1010)}

    @staticmethod
    def fund_ledger(db, ledger_parm, merchant_obj, invoices_list, financial_year):
        try:
            check_response = check_ledger(db, ledger_parm.ledgerNo, ledger_parm.requestId, merchant_obj.id)
            if check_response.get('code') == 200:
                check_invoice_response = Financing.check_invoice(db, ledger_parm, financial_year)
                if check_invoice_response.get('code') == 200:
                    json_request = jsonable_encoder(ledger_parm)
                    # invoices_cache = r.get('invoices')
                    # invoices_list = [ledger_data.get('invoiceNo') for ledger_data in json_request.get('ledgerData')]
                    # new_cache_list = invoices_list + ast.literal_eval(invoices_cache)
                    # r.set('invoices', str(new_cache_list))
                    # invoice_cache = r.get('invoices')
                    # logger.info(f"final invoice caches>>>>>>>>>>>. {invoice_cache}")
                    # all_data = db.query(
                    #     models.Invoice
                    # ).join(models.Ledger).where(
                    #     models.Invoice.ledger_id == ledger_parm.ledgerNo
                    # ).all()
                    #
                    # status = []
                    # for invoice_status in all_data:
                    #     status.append(invoice_status.fund_status)
                    #
                    # logger.info(f"getting status >>>>>>>>>> {status}")
                    # if True in status:
                    #     return_response = {"requestId": ledger_parm.requestId, **ErrorCodes.get_error_response(1004)}
                    # else:
                    #     fund_status = True
                    #     update_query = f"UPDATE invoice SET fund_status = {fund_status} WHERE ledger_id =" \
                    #                    f" {ledger_parm.ledgerNo};"
                    #     db.execute(text(update_query))
                    #     db.commit()
                    #     return_response = {"requestId": ledger_parm.requestId, **ErrorCodes.get_error_response(1005)}

                    return_response = {"requestId": ledger_parm.requestId, **ErrorCodes.get_error_response(1013)}
                    response_hash = utils.create_ledger_hash(return_response, merchant_obj.merchant_secret)
                    return_response.update({"signature": response_hash})
                    invoice_cache = r.get('invoices')
                    ast.literal_eval(invoice_cache)
                    new_invoice = [i for i in ast.literal_eval(invoice_cache) if i not in invoices_list]
                    r.set('invoices', str(new_invoice))
                    invoice_cache = r.get('invoices')
                    logger.info(f"final invoice caches>>>>>>>>>>>. {invoice_cache}")
                    return return_response
                else:
                    response_hash = utils.create_ledger_hash(check_invoice_response, merchant_obj.merchant_secret)
                    check_invoice_response.update({"signature": response_hash})
                    invoice_cache = r.get('invoices')
                    ast.literal_eval(invoice_cache)
                    new_invoice = [i for i in ast.literal_eval(invoice_cache) if i not in invoices_list]
                    r.set('invoices', str(new_invoice))
                    invoice_cache = r.get('invoices')
                    logger.info(f"final invoice caches>>>>>>>>>>>. {invoice_cache}")
                    return check_invoice_response
            else:
                response_hash = utils.create_ledger_hash(check_response, merchant_obj.merchant_secret)
                check_response.update({"signature": response_hash})
                invoice_cache = r.get('invoices')
                ast.literal_eval(invoice_cache)
                new_invoice = [i for i in ast.literal_eval(invoice_cache) if i not in invoices_list]
                r.set('invoices', str(new_invoice))
                invoice_cache = r.get('invoices')
                logger.info(f"final invoice caches>>>>>>>>>>>. {invoice_cache}")
                return check_response

        except Exception as e:
            invoice_cache = r.get('invoices')
            ast.literal_eval(invoice_cache)
            new_invoice = [i for i in ast.literal_eval(invoice_cache) if i not in invoices_list]
            r.set('invoices', str(new_invoice))
            logger.error(f"getting error while create student {e}")


class CancelLedger:
    @staticmethod
    def cancel(db, ledger_parm, merchant_obj):
        try:
            check_ledger_response = check_ledger(db, ledger_parm.ledgerNo, ledger_parm.requestId, merchant_obj.id)
            logger.info(check_ledger_response.get('code'))
            if check_ledger_response.get('code') == 200:
                logger.info(f"getting if condition {check_ledger_response}")
                all_fund_status, all_inv_list, live_inv_ids, old_inv_ids = CancelLedger.cancel_ledger(db, ledger_parm.ledgerNo)
                logger.info(f"getting fund status ///////// {all_fund_status} invoice no ////////// {all_inv_list}")
                if True in all_fund_status:
                    invoice_cache = r.get('invoices')
                    ast.literal_eval(invoice_cache)
                    new_invoice = [i for i in ast.literal_eval(invoice_cache) if i not in all_inv_list]
                    r.set('invoices', str(new_invoice))
                    invoice_cache = r.get('invoices')
                    logger.info(f"final invoice caches>>>>>>>>>>>. {invoice_cache}")
                    extra_data = dict({"cancellationMessage": ledger_parm.cancellationReason})
                    # update_query = (
                    #     f"UPDATE invoice SET extra_data = extra_data || '{{\"financierMerchantId\": \"\"}}'::jsonb, "
                    #     f"fund_status = False, status = '{InvoiceStatus.NON_FUNDED}', funded_amt = '' "
                    #     f"WHERE id IN {tuple_invoice_no}"
                    # )
                    # update_query = """UPDATE invoice SET extra_data = extra_data || '{"financierMerchantId": \"\"}'::jsonb, fund_status = False, status = :inv_status, funded_amt = '' WHERE id IN :tuple_invoice_no"""
                    # query_parma = {'inv_status': InvoiceStatus.NON_FUNDED, 'tuple_invoice_no': tuple_invoice_no}
                    # db.execute(text(update_query), query_parma)
                    # db.commit()

                    if live_inv_ids:
                        for live_inv_id in live_inv_ids:
                            live_invoice_obj = db.query(
                                models.Invoice
                            ).filter(
                                models.Invoice.id == live_inv_id
                            ).first()

                            live_invoice_obj.fund_status = False
                            live_invoice_obj.status = InvoiceStatus.NON_FUNDED

                            data = copy.deepcopy(live_invoice_obj.extra_data)
                            if data.get('financierHistory', []):
                                if merchant_obj.id in data.get('financierHistory', ''):
                                    data.get('financierHistory').remove(merchant_obj.id)
                            else:
                                inv_extra_data = {
                                    'financierHistory': []
                                }
                                data.update(inv_extra_data)
                            data.update({'financierMerchantId': ''})

                            live_invoice_obj.extra_data = data
                            db.commit()
                            db.refresh(live_invoice_obj)

                    if old_inv_ids:
                        for old_inv_id in old_inv_ids:
                            old_invoice_obj = db.query(
                                models.OldInvoice
                            ).filter(
                                models.OldInvoice.id == old_inv_id
                            ).first()

                            # old_invoice_obj.fund_status = False
                            # old_invoice_obj.status = InvoiceStatus.NON_FUNDED

                            # data = copy.deepcopy(old_invoice_obj.extra_data)
                            #
                            # if data.get('financierHistory', ''):
                            #     if merchant_obj.id in data.get('financierHistory', ''):
                            #         data.get('financierHistory').remove(merchant_obj.id)
                            # else:
                            #     inv_extra_data = {
                            #         'financierHistory': []
                            #     }
                            #     data.update(inv_extra_data)
                            # data.update({'financierMerchantId': ''})
                            #
                            # old_invoice_obj.extra_data = data
                            # db.commit()
                            # db.refresh(old_invoice_obj)

                            ###
                            try:
                                # transfer old invoice to live invoice table
                                inv_obj = models.Invoice(
                                    invoice_no=old_invoice_obj.invoice_no,
                                    invoice_date=old_invoice_obj.invoice_date,
                                    invoice_due_date=old_invoice_obj.invoice_due_date,
                                    invoice_amt=old_invoice_obj.invoice_amt,
                                    invoice_hash=old_invoice_obj.invoice_hash,
                                    funded_amt=old_invoice_obj.funded_amt,
                                    gst_status=bool(old_invoice_obj.gst_status),
                                    fund_status=old_invoice_obj.fund_status,
                                    financial_year=old_invoice_obj.financial_year,
                                    status=old_invoice_obj.status,
                                    extra_data=old_invoice_obj.extra_data,
                                    is_active=old_invoice_obj.is_active,
                                    created_at=old_invoice_obj.created_at,
                                    updated_at=old_invoice_obj.updated_at
                                )
                                db.add(inv_obj)
                                db.commit()
                                db.refresh(inv_obj)

                                for led_obj in old_invoice_obj.ledger:
                                    # create invoice_ledger_association
                                    inv_obj.ledger.append(led_obj)
                                    db.commit()
                                    db.refresh(old_invoice_obj)

                                # delink old inv, link inv
                                inv_enc_data_obj = db.query(
                                    models.InvoiceEncryptedData
                                ).filter(
                                    models.InvoiceEncryptedData.old_invoice_id == old_invoice_obj.id
                                ).first()

                                inv_enc_data_obj.invoice_id = inv_obj.id
                                inv_enc_data_obj.old_invoice_id = None
                                db.commit()
                                db.refresh(inv_enc_data_obj)

                                try:
                                    # delink old inv, link inv to lenInvAss
                                    len_inv_ass_obj = db.query(
                                        models.LenderInvoiceAssociation
                                    ).filter(
                                        # models.LenderInvoiceAssociation.lender_id == lender_obj.id,
                                        models.LenderInvoiceAssociation.old_invoice_id == old_invoice_obj.id
                                    ).first()

                                    if len_inv_ass_obj:
                                        len_inv_ass_obj.invoice_id = inv_obj.id
                                        len_inv_ass_obj.old_invoice_id = None
                                        db.commit()
                                        db.refresh(len_inv_ass_obj)

                                    if not len_inv_ass_obj:
                                        len_inv_ass_obj = LenderInvoiceAssociation(
                                            # lender_id=lender_obj.id,
                                            invoice_id=inv_obj.id
                                        )
                                        db.add(len_inv_ass_obj)
                                        db.commit()
                                        db.refresh(len_inv_ass_obj)
                                except Exception as e:
                                    logger.info(f"LenderInvoiceAssociation :: {e}")
                                    pass

                                inv_obj.fund_status = False
                                inv_obj.status = InvoiceStatus.NON_FUNDED

                                data = copy.deepcopy(old_invoice_obj.extra_data)
                                if data.get('financierHistory', ''):
                                    if merchant_obj.id in data.get('financierHistory', ''):
                                        data.get('financierHistory').remove(merchant_obj.id)
                                else:
                                    inv_extra_data = {
                                        'financierHistory': []
                                    }
                                    data.update(inv_extra_data)
                                data.update({'financierMerchantId': ''})

                                inv_obj.extra_data = data
                                db.commit()
                                db.refresh(inv_obj)

                                # after moved, delete old inv obj from OldInvoice table
                                db.delete(old_invoice_obj)
                                db.commit()
                                # db.refresh(old_invoice_data)
                            except Exception as e:
                                logger.error(f"Error financing :: move old_inv to inv {traceback.format_exc()}")
                                pass
                            ###

                    ledger_obj = db.query(models.Ledger).filter(models.Ledger.ledger_id == ledger_parm.ledgerNo).first()
                    ledger_obj.extra_data = extra_data
                    ledger_obj.status = InvoiceStatus.NON_FUNDED
                    logger.info(f"getting data >>>>>>>>>>>>>>>. {ledger_obj.id}")
                    db.commit()
                    db.refresh(ledger_obj)
                    return_response = {"requestId": ledger_parm.requestId, **ErrorCodes.get_error_response(200)}
                    response_hash = utils.create_ledger_hash(return_response, merchant_obj.merchant_secret)
                    return_response.update({"signature": response_hash})
                    invoice_cache = r.get('invoices')
                    logger.info(f"final invoice caches>>>>>>>>>>>. {invoice_cache}")
                    return return_response
                else:
                    return_response = {"requestId": ledger_parm.requestId, **ErrorCodes.get_error_response(1006)}
                    response_hash = utils.create_ledger_hash(return_response, merchant_obj.merchant_secret)
                    return_response.update({"signature": response_hash})
                    return return_response
            else:
                response_hash = utils.create_ledger_hash(check_ledger_response, merchant_obj.merchant_secret)
                check_ledger_response.update({"signature": response_hash})
                return check_ledger_response
        except Exception as e:
            print(f"getting error while create student {e}")
            logger.info(f"CancelLedger cancel :: {traceback.format_exc()}")

    @staticmethod
    def cancel_ledger(db, ledger_id):
        logger.info(f"getting ledger check {ledger_id}")

        query = """
            select 
                array_remove( array_agg(i.fund_status), null ) || array_remove( array_agg(oi.fund_status), null ) as all_fund_status,
                array_remove(array_agg(coalesce(i.invoice_no , ''::text)), '') || array_remove(array_agg(coalesce(oi.invoice_no, ''::text)), '') as all_inv_list,
                array_remove(array_agg(coalesce(ila.invoice_id , 0)), 0) as live_inv_id,
                array_remove(array_agg(coalesce(oila.invoice_id , 0)), 0) as old_inv_id
            from 
                invoice_encrypted_data ied
            full join invoice_ledger_association ila on ila.invoice_id = ied.invoice_id
            full join invoice i on i.id = ila.invoice_id
            full join old_invoice_ledger_association oila on oila.invoice_id = ied.old_invoice_id 
            full join old_invoice oi on oi.id = oila.invoice_id
            inner join ledger l on l.id = ila.ledger_id or l.id =oila.ledger_id 
            where 
                l.ledger_id = :ledger_id
                and l.status in ('funded')
            ;
        """
        invoice_data = db.execute(text(query), [{'ledger_id': ledger_id}]).first()
        all_fund_status, all_inv_list, live_inv_ids, old_inv_ids = [False], [], [], []
        if invoice_data and invoice_data[0]:
            all_fund_status = invoice_data.all_fund_status
            all_inv_list = invoice_data.all_inv_list
            live_inv_ids = invoice_data.live_inv_id
            old_inv_ids = invoice_data.old_inv_id
        return all_fund_status, all_inv_list, live_inv_ids, old_inv_ids


    @staticmethod
    def cancel_ledger1(db, ledger_id):
        logger.info(f"getting ledger check {ledger_id}")
        # all_data = db.query(
        #     models.Invoice
        # ).join(models.Ledger).where(
        #     models.Invoice.ledger_id == ledger_id
        # ).all()

        query = """
                    select
                        array_agg(i.id::varchar) as str_invoice_id, array_agg(i.fund_status) as fund_status, 
                        array_agg(i.id) as invoice_id
                    from
                        invoice_ledger_association ila
                    inner join ledger l on
                        ila.ledger_id = l.id
                    inner join invoice i on
                        ila.invoice_id = i.id
                    where
                        l.ledger_id  = :ledger_id
                        and l.status in ('funded');
                """
        invoice_data = db.execute(text(query), [{'ledger_id': ledger_id}]).first()

        if invoice_data and invoice_data[0] == None:
            return [False], [], tuple()
        # status = []
        # invoice_number = []
        # for invoice_status in all_data:
        #     status.append(invoice_status.fund_status)
        #     invoice_number.append(str(invoice_status.invoice_no))
        # logger.info(f"getting status %%%%%%%%%%%%%%%%%%%%%%%%%%% {status}")
        if len(invoice_data.invoice_id) == 1:
            invoice_data.invoice_id.append("0")
        return invoice_data.fund_status, invoice_data.str_invoice_id, tuple(invoice_data.invoice_id)


def check_ledger(db, ledger_id, request_id, merchant_id, grouping_id=None):
    logger.info(f"getting ledger check {ledger_id}")
    if grouping_id:
        ledger_data = db.query(models.Ledger).filter(
            models.Ledger.ledger_id == ledger_id,
            models.Ledger.merchant_id == merchant_id
        ).filter(
            models.Ledger.extra_data.contains({"groupingId": grouping_id})
        ).first()
        if ledger_data:
            return {'ledgerStatus': ledger_data.status, **ErrorCodes.get_error_response(200)}
        else:
            return {'requestId': request_id, **ErrorCodes.get_error_response(1119)}
    else:
        ledger_data = db.query(models.Ledger).filter(
            models.Ledger.ledger_id == ledger_id,
            models.Ledger.merchant_id == merchant_id
        ).first()
        logger.info(f"getting ledger data {ledger_data}")
        if ledger_data:
            return {'ledgerStatus': ledger_data.status, **ErrorCodes.get_error_response(200)}
        else:
            return {'requestId': request_id, **ErrorCodes.get_error_response(1007)}


def webhook_data(db, ledger_parm):
    query = """
                select
                    jsonb_agg(jsonb_build_object(
                    'invoiceId', i.id,
                    'invoiceNo', invoice_no,
                    'invoiceStatus', CASE WHEN fund_status = True then 'Funded' ELSE 'Non Funded' END,
                    'invoiceAmt', invoice_amt,
                    'invoiceDate', invoice_date,
                    'gstVerificationStatus', COALESCE(gst_status, 'false'),
                    'fundedAmt', COALESCE(funded_amt, ''),
                    'buyerIdentifierData', cast(i.extra_data->>'buyerIdentifierData' as json),
                    'sellerIdentifierData', cast(i.extra_data->>'sellerIdentifierData' as json))) as webhook_data
                from
                    invoice i
                inner join invoice_ledger_association ila
                    on i.id = ila.invoice_id 
                inner join ledger l
                    on l.id = ila.ledger_id
                where
                    l.ledger_id  = :ledger_no; 
            """
    invoice_obj = db.execute(text(query), [{'ledger_no': ledger_parm.ledgerNo}]).first()
    logger.info(f"getting response >>>>>>>>>>>>>>>> {invoice_obj}")
    return {"requestId": ledger_parm.requestId,
            "ledgerNo": ledger_parm.ledgerNo,
            "ledgerData": invoice_obj.webhook_data if invoice_obj.webhook_data else []
            }


def create_request_log(db, request_id, request_data, response_data, flag, api_url='', merchant_key=None):
    try:
        # merchant_details = db.query(models.MerchantDetails).filter(models.MerchantDetails.merchant_key == merchant_key).first()
        # if not merchant_details:
        #     return {
        #         "requestId": request_data.get('requestId'),
        #         **ErrorCodes.get_error_response(1002)
        #     }
        # merchant_id_obj = merchant_details.id if merchant_details.id else ''
        # merchant_id = str(merchant_id_obj).zfill(4)
        # logger.info(f"merchant id create request log >>>>>>>>>>>>>>>>>>>>>> {merchant_id}")
        api_request_obj = db.query(
            models.APIRequestLog
        ).filter(
            models.APIRequestLog.request_id == request_id
        ).first()
        logger.info(f"getting data iof api request log ################### {api_request_obj}")
        if flag == 'request':
            if api_request_obj:
                return {**ErrorCodes.get_error_response(1009)}
            merchant_details = db.query(models.MerchantDetails).filter(models.MerchantDetails.merchant_key == merchant_key).first()
            if not merchant_details:
                return {
                    "requestId": request_data.get('requestId'),
                    **ErrorCodes.get_error_response(1002)
                }
            merchant_id = merchant_details.id if merchant_details else ''
            logger.info(f"merchant id create request log >>>>>>>>>>>>>>>>>>>>>> {merchant_id}")
            request_created = models.APIRequestLog(
                request_id=request_data.get('requestId'),
                request_data=request_data,
                api_url=api_url,
                merchant_id=merchant_id
            )
            db.add(request_created)
            db.commit()
            db.refresh(request_created)
            return {**ErrorCodes.get_error_response(200)}
        else:
            api_request_obj.response_data = response_data
            api_request_obj.updated_at = datetime.datetime.now()
            db.commit()
            db.refresh(api_request_obj)
    except Exception as e:
        logger.error(f"getting error while creating request log >>>>>>>>>>>>>>> {e}")
        return {**ErrorCodes.get_error_response(500)}


# sftp user info requestlog
def create_request_log_sftpuser(db, request_id, request_data, response_data, flag, api_url='', merchant_key=None):
    try:
        api_request_obj = db.query(
            models.APIRequestLog
        ).filter(
            models.APIRequestLog.request_id == request_id
        ).first()
        logger.info(f"getting data iof api request log ################### {api_request_obj}")
        if flag == 'request':
            if api_request_obj:
                return {"requestId": request_id, **ErrorCodes.get_error_response(1009)}
            # merchant_details = merchant_key
            # if not merchant_details:
            #     return {
            #         "requestId": request_data.get('requestId'),
            #         **ErrorCodes.get_error_response(1002)
            #     }
            # merchant_id = merchant_details
            # logger.info(f"merchant_id request log >>>>>>>>>>>>>>>>>>>>>> {merchant_id}")
            request_created = models.APIRequestLog(
                request_id=request_data.get('requestId'),
                request_data=request_data,
                api_url=api_url,
                merchant_id=merchant_key
            )
            db.add(request_created)
            db.commit()
            db.refresh(request_created)
            return {"requestId": request_id, **ErrorCodes.get_error_response(200)}
        else:
            api_request_obj.response_data = response_data
            api_request_obj.updated_at = datetime.datetime.now()
            db.commit()
            db.refresh(api_request_obj)
    except Exception as e:
        logger.error(f"getting error while creating request log >>>>>>>>>>>>>>> {e}")
        return {**ErrorCodes.get_error_response(500)}
