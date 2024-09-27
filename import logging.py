import logging
import time
import copy
import json
from itertools import chain
import redis
import ast
import requests
import datetime
import traceback
import pytz
import pandas as pd
from typing import Annotated
from io import BytesIO
from fastapi import FastAPI, Response
from datetime import datetime as dt
from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from decouple import config as dconfig
from sqlalchemy import text, desc
from dateutil.relativedelta import relativedelta
import config
import models

from database import SessionLocal
from sqlalchemy.orm import Session

import utils
# from invoice_registry_app.routers.ledger import get_cache
# from invoice_registry_app.views import check_ledger
from models import MerchantDetails, LenderDetails, LenderInvoiceAssociation, InvoiceEncryptedData, Ledger, \
    DisbursedHistory, RepaymentHistory
from routers.auth import get_current_merchant_active_user, User
from routers.ledger import get_cache
from schema import InvoiceRequestSchema, FinanceSchema, CancelLedgerSchema, CheckStatusSchema, AsyncFinanceSchema, \
    GetInvoiceHubMisReportSchema, GetUserMisReportSchema
import views
from errors import ErrorCodes
from utils import get_financial_year, check_invoice_date, create_post_processing, InvoiceStatus, validate_signature
from views import check_ledger
from database import get_db
# logging.config.fileConfig('logging.conf', disable_existing_loggers=False)
logger = logging.getLogger(__name__)

router = APIRouter()
r = redis.Redis(host=dconfig('REDIS_HOST'), port=6379, decode_responses=True)
asia_kolkata = pytz.timezone('Asia/Kolkata')

class MisReport:

    def __init__(self, from_date=False, to_date=False):
        self.from_date = from_date
        self.to_date = to_date
        self.view_query = ''

    def create_all_materialized_view(self):
        try:
            logger.info(f"::: create_all_materialized_view....in one go..:::")
            self.financing_api_materialized_view()
            self.registration_api_materialized_view()
            self.disbursement_api_materialized_view()
            self.cancellation_api_materialized_view()
            self.repayment_api_materialized_view()
            self.status_check_api_materialized_view()
            self.total_calls_for_all_api_materialized_view()
            return True
        except Exception as e:
            logger.error(f"Error while creating Materialized View : {e}")
            return False