import logging
from pydantic import BaseModel, Field, field_validator, model_validator
from fastapi.encoders import jsonable_encoder
from typing import List, Optional, Any
from enum import Enum
from datetime import date
from fastapi import HTTPException, Response
import re
from datetime import datetime
from identifier_validation import ValidationCheck
from errors import ErrorCodes


logger = logging.getLogger(__name__)


# special_char_regex = '[.-@!#$%^&*()<>?/\|}{~:\b\s]'
special_char_regex = '[.-@!#$%^&*()<>?/\|}{~:\b\s]'
regex = "^(?=.*[a-zA-Z])(?=.*[0-9])[A-Za-z0-9]+$"
validate_value = re.compile(regex)
special_char_pattern = re.compile(r'^[a-zA-Z0-9_]*$')
date_special_char_pattern = re.compile(r'^[a-zA-Z0-9/]+$')
amount_special_char_pattern = re.compile(r'^[a-zA-Z0-9.-]*$')
amt_regex_pattern =  r'^[0-9]+(\.[0-9]+)?$'
# invoice_number_pattern = re.compile(r'^[a-zA-Z0-9_#\/|]+$')
invoice_number_pattern = r'^[-_/\#a-zA-Z0-9\s]+$'
validation_ref_no_pattern = r'^[-_/\#a-zA-Z0-9\s]+$'
seller_buyer_id_name_pattern = r'^[-&a-zA-Z0-9\s]+$'
lender_name_pattern = re.compile(r'^[a-zA-Z0-9_ ]*$')
# username_special_char_pattern = re.compile(r'^[@a-zA-Z0-9_]*$')
username_special_char_pattern = re.compile(r'[/<[^>]*>?/]')
number_pattern = re.compile(r'^[0-9]*$')

def check_decimal_precision(param_name, param_value):
    try:
        float(param_value)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid {param_name}:{param_value}")

    if not amount_special_char_pattern.match(str(param_value)):
        raise HTTPException(status_code=400, detail=f"{param_name} can not accept special character:{param_value} ")
    if float(param_value) < float(0) or str(float(param_value)) == '-0.0':
        raise HTTPException(status_code=400, detail=f"{param_name} should not be less than zero:{param_value}")

    parts = str(param_value).split('.')

    if len(parts) == 2 and len(parts[1]) > 2:
        raise HTTPException(status_code=400, detail=f"{param_name} can not have more than two decimal places:{param_value}")


class FundingType(str, Enum):
    Full = "Full"
    Partial = "Partial"


class InvoiceStatus(str, Enum):
    Funded = "Funded"
    NonFunded = "Non-Funded"
    PartialDisbursed = "Partial-Disbursed"
    FullDisbursed = "Full-Disbursed"
    PartialPaid = "Partial-Paid"
    FullyPaid = "Fully-Paid"


class LedgerStatus(str, Enum):
    Funded = "Funded"
    NonFunded = "Non-Funded"


class BaseSchema(BaseModel):
    requestId: str
    signature: str

    @field_validator('requestId')
    def validate_request_id(cls, value: str):
        if not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"request id can not accept special character {value}")
        if value == '':
            raise HTTPException(status_code=400, detail=f"request id can not be blank")
        elif len(value) > 30:
            raise HTTPException(status_code=400, detail=f"request id can not be greater than 30 {value}")
        return value

    @field_validator('signature')
    def validate_signature(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="signature can not be blank")
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail="signature can not accept special character")
        elif len(value) > 500:
            raise HTTPException(status_code=400, detail="signature can not be greater than 500")
        return value


class APIRequestLogSchema(BaseSchema):
    request_id: str
    api_url: str
    txn_type: str


class SellerData(BaseModel):
    sellerIdType: str
    sellerIdNo: str
    sellerIdName: str
    ifsc: str

    @model_validator(mode='after')
    def validate_field(self):
        if self.sellerIdType and len(self.sellerIdType) > 50:
            raise HTTPException(status_code=400, detail=f"Seller id type can not be greater than 50 {self.sellerIdType}")
        if self.sellerIdType and self.sellerIdType.lower() not in ['lei', 'gstin', 'pan', 'cin', 'tax_no', 'accountnumber']:
            raise HTTPException(status_code=400, detail=f"Invalid entity type:{self.sellerIdType}")
        # if not self.sellerIdName:
        #     raise HTTPException(status_code=400, detail="Seller id name can not be blank")
        # if self.sellerIdName and not special_char_pattern.match(self.sellerIdName):
        if self.sellerIdName and not re.match(seller_buyer_id_name_pattern, self.sellerIdName):
            raise HTTPException(status_code=400, detail=f"Seller id name can not accept special character {self.sellerIdName}")
        if self.sellerIdName and len(self.sellerIdName) > 50:
            raise HTTPException(status_code=400, detail=f"Seller id name can not be greater than 50 {self.sellerIdName}")
        if self.sellerIdType and self.sellerIdType.lower() == "accountnumber":
            if self.ifsc == "":
                raise HTTPException(status_code=400, detail=f"IFSC can not be blank in seller data {self.ifsc}")
            elif not special_char_pattern.match(self.ifsc):
                raise HTTPException(status_code=400, detail=f"IFSC can not accept special character {self.ifsc}")
            elif len(self.ifsc) > 16:
                raise HTTPException(status_code=400, detail=f"IFSC can not be greater than 16 {self.ifsc}")
            elif self.sellerIdType.lower() != "accountnumber":
                raise HTTPException(status_code=400, detail=f"Entity id type should be 'Account Number' for ifsc in "
                                                            f"seller data {self.sellerIdType}")
        else:
            if self.ifsc != "":
                raise HTTPException(status_code=400,
                                    detail=f"Entity id type should be 'Account Number' for ifsc in seller data {self.ifsc}")
        return self

    @model_validator(mode='after')
    def identifier_field(self):
        if self.sellerIdType.lower():
            if not self.sellerIdNo:
                raise HTTPException(status_code=400, detail=f"Seller id no can not be blank {self.sellerIdNo}")
        if self.sellerIdType.lower() == "gstin":
            gst_value = ValidationCheck.validate_gst(self.sellerIdNo)
            if not gst_value:
                raise HTTPException(status_code=400, detail=f"seller id no for GST is not valid {self.sellerIdNo}")
        elif self.sellerIdType.lower() == 'lei':
            lei_value = ValidationCheck.validate_lei(self.sellerIdNo)
            if not lei_value:
                raise HTTPException(status_code=400, detail=f"seller id no for LEI is not valid {self.sellerIdNo}")
        elif self.sellerIdType.lower() == 'pan':
            pan_value = ValidationCheck.validate_pan_card(self.sellerIdNo)
            if not pan_value:
                raise HTTPException(status_code=400, detail=f"seller id no for PAN Number is not valid {self.sellerIdNo}")
        elif self.sellerIdType.lower() == 'cin':
            cin_value = ValidationCheck.validate_cin(self.sellerIdNo)
            if not cin_value:
                raise HTTPException(status_code=400, detail=f"seller id no for CIN is not valid {self.sellerIdNo}")
        elif self.sellerIdType.lower() == 'tax_no':
            pt_value = ValidationCheck.validate_pt(self.sellerIdNo)
            if not pt_value:
                raise HTTPException(status_code=400, detail=f"seller id no for TAX NO is not valid {self.sellerIdNo}")
        return self

    @field_validator('sellerIdNo')
    def validate_seller_id_no(cls, value: str):
        # if value == "":
        #     raise HTTPException(status_code=400, detail="Seller id no can not be left blank")
        if value and not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"Seller id no can not accept special character {value}")
        elif value and len(value) > 50:
            raise HTTPException(status_code=400, detail=f"Seller id no can not be greater than 50 {value}")
        return value


class BuyerData(BaseModel):
    buyerIdType: str
    buyerIdNo: str
    buyerIdName: str
    ifsc: str

    @model_validator(mode='after')
    def validate_field(self):
        if self.buyerIdType.lower():
            if not self.buyerIdNo:
                raise HTTPException(status_code=400, detail="Buyer id no can not be blank")
        if self.buyerIdType and len(self.buyerIdType) > 50:
            raise HTTPException(status_code=400, detail=f"Buyer id type can not be greater than 50 {self.buyerIdType}")
        if self.buyerIdType and self.buyerIdType.lower() not in ['lei', 'gstin', 'pan', 'cin', 'tax_no', 'accountnumber']:
            raise HTTPException(status_code=400, detail=f"Invalid entity type {self.buyerIdType}")
        # if not self.buyerIdName:
        #     raise HTTPException(status_code=400, detail="Buyer id name can not be blank")
        # if self.buyerIdType and not special_char_pattern.match(self.buyerIdName):
        if self.buyerIdName and not re.match(seller_buyer_id_name_pattern, self.buyerIdName):
            raise HTTPException(status_code=400, detail=f"Buyer id name can not accept special character {self.buyerIdName}")
        # if len(self.buyerIdName) > 50:
        #     raise HTTPException(status_code=400, detail=f"Buyer id name can not be greater than 50 {self.buyerIdName}")
        if self.buyerIdName and len(self.buyerIdName) > 50:
            raise HTTPException(status_code=400, detail=f"Buyer id name can not be greater than 50 {self.buyerIdName}")
        if self.buyerIdType and self.buyerIdType.lower() == "accountnumber":
            if self.ifsc == "":
                raise HTTPException(status_code=400, detail=f"IFSC can not be blank in buyer data {self.ifsc}")
            elif not special_char_pattern.match(self.ifsc):
                raise HTTPException(status_code=400, detail=f"IFSC can not accept special character {self.ifsc}")
            elif len(self.ifsc) > 16:
                raise HTTPException(status_code=400, detail=f"IFSC can not be greater than 16 {self.ifsc}")
            elif self.buyerIdType.lower() != "accountnumber":
                raise HTTPException(status_code=400, detail=f"Entity id type should be 'Account Number' for ifsc in "
                                                            f"buyer data  {self.buyerIdType}")
        else:
            if self.ifsc != "":
                raise HTTPException(status_code=400, detail=f"Entity id type should be 'Account Number' for ifsc in buyer data {self.buyerIdType}")
        return self

    # all identifier validation check schema -['lei', 'gst', 'pan', 'cin', 'tax_no']
    @model_validator(mode='after')
    def identifier_field(self):
        if self.buyerIdType.lower() == "gstin":
            gst_value = ValidationCheck.validate_gst(self.buyerIdNo)
            if not gst_value:
                raise HTTPException(status_code=400, detail=f"buyer gst is not valid {self.buyerIdNo}")
        elif self.buyerIdType.lower() == 'lei':
            lei_value = ValidationCheck.validate_lei(self.buyerIdNo)
            if not lei_value:
                raise HTTPException(status_code=400, detail=f"buyer lei is not valid {self.buyerIdNo}")
        elif self.buyerIdType.lower() == 'pan':
            pan_value = ValidationCheck.validate_pan_card(self.buyerIdNo)
            if not pan_value:
                raise HTTPException(status_code=400, detail=f"buyer pan number is not valid {self.buyerIdNo}")
        elif self.buyerIdType.lower() == 'cin':
            cin_value = ValidationCheck.validate_cin(self.buyerIdNo)
            if not cin_value:
                raise HTTPException(status_code=400, detail=f"buyer cin is not valid {self.buyerIdNo}")
        elif self.buyerIdType.lower() == 'tax_no':
            pt_value = ValidationCheck.validate_pt(self.buyerIdNo)
            if not pt_value:
                raise HTTPException(status_code=400, detail=f"buyer tax no is not valid {self.buyerIdNo}")
        return self

    @field_validator('buyerIdNo')
    def validate_buyer_id_no(cls, value: str):
        # if value == "":
        #     raise HTTPException(status_code=400, detail="Buyer id no can not be left blank")
        if value and not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"Buyer id no can not accept special character {value}")
        elif value and len(value) > 50:
            raise HTTPException(status_code=400, detail=f"Buyer id no can not be greater than 50 {value}")
        return value


class InvoiceSchema(BaseModel):
    validationType: str
    validationRefNo: str
    invoiceNo: str
    invoiceDate: str = Field(default='01/06/1989')
    invoiceAmt: str
    verifyGSTNFlag: bool
    invoiceDueDate: str = Field(default='01/06/1989')

    @field_validator('invoiceNo')
    def validate_invoice_no(cls, value: str):
        logger.info(f"getting data {re.match(invoice_number_pattern, value)}")
        if value == '':
            raise HTTPException(status_code=400, detail="Invoice no can not be blank")
        elif len(value) > 100:
            raise HTTPException(status_code=400, detail=f"Invoice number can not be greater than 100 {value}")
        elif not re.match(invoice_number_pattern, value):
            raise HTTPException(status_code=400, detail=f"Invalid invoice number format. Use only letters, numbers, spaces, and symbols: '-', '_', '/', '#'. Please check your input.")
        # elif value != "":
        #     cleaned_string = re.sub(r'[^a-zA-Z0-9\s]', '', value)
        #     if cleaned_string:
        #         cleaned_string = re.sub(r'\s+', ' ', cleaned_string)
        #         if not cleaned_string:
        #             raise HTTPException(status_code=400, detail="Invoice no can not accept only special character")
        #     else:
        #         raise HTTPException(status_code=400, detail="Invoice no can not accept only special character")
        return value

    @field_validator('invoiceDate')
    def validate_invoice_date(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="Invoice date can not be blank")
        elif len(value) > 10:
            raise HTTPException(status_code=400, detail=f"Invoice date can not be greater than 10 {value}")
        return value

    @field_validator('invoiceDate')
    def validate_invoice_dates(cls, value: date) -> date:
        from datetime import datetime
        try:
            dd = datetime.strptime(value, "%d/%m/%Y")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"date format except d/m/Y format  {value}")
        return value

    @field_validator('invoiceAmt')
    def validate_invoice_amount(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail=f"Invoice amount can not be blank  {value}")
        if value == '0':
            raise HTTPException(status_code=400, detail=f"Invoice amount should be greater than 0 {value}")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"Invoice number can not be greater than 20 {value}")
        elif not bool(re.match(amt_regex_pattern, value)):
            raise HTTPException(status_code=400, detail=f"Invalid invoice amount {value}")
        if '.' in value:
            amount_list = value.split('.')
            if len(amount_list) > 2:
                raise HTTPException(status_code=400, detail=f"Invalid invoice amount  {value}")
            elif len(amount_list[1]) > 2:
                raise HTTPException(status_code=400, detail=f"Invoice amount can not accept more than two digit value {value}")
        return value

    @field_validator('verifyGSTNFlag')
    def validate_verify_gst_flag(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="Verify gst flag can not be blank")
        elif value not in [True, False]:
            raise HTTPException(status_code=400, detail=f"Verify gst flag either True or False {value}")
        return value

    @field_validator('invoiceDueDate')
    def validate_invoice_due_date(cls, value: date) -> date:
        from datetime import datetime
        if len(value) > 10:
            raise HTTPException(status_code=400, detail=f"Invoice due date can not be greater than 10  {value}")
        elif value != "":
            try:
                dd = datetime.strptime(value, "%d/%m/%Y")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invoice due date format except d/m/Y format {value}")
            return value
        else:
            return value

    @model_validator(mode='after')
    def validate_field(self):
        if self.validationRefNo != "":
            validate_string = re.search(validation_ref_no_pattern, self.validationRefNo)
            if not validate_string:
                raise HTTPException(status_code=400, detail=f"validation Ref No can not accept special character {self.validationRefNo}")
            if self.validationType.lower() not in ['einvoice', 'ewaybill', 'gstfiling']:
                raise HTTPException(status_code=400, detail=f"validation type should be eInvoice, eWayBill, "
                                                            f"gstFiling {self.validationType}")
        if self.verifyGSTNFlag:
            if self.validationType.lower() not in ['einvoice', 'ewaybill', 'gstfiling']:
                raise HTTPException(status_code=400, detail=f"validation type should be eInvoice, eWayBill, gstFiling {self.validationType}")
            if not self.validationRefNo:
                raise HTTPException(status_code=400, detail="Validation reference no can not be blank")
        if self.validationType:
            if not self.validationRefNo:
                raise HTTPException(status_code=400, detail="Validation reference no can not be blank")
        return self


class BulkInvoiceSchema(BaseModel):
    validationType: str
    validationRefNo: str
    invoiceNo: str
    invoiceDate: str = Field(default='01/06/1989')
    invoiceAmt: str
    verifyGSTNFlag: bool
    invoiceDueDate: str = Field(default='01/06/1989')

    @field_validator('invoiceNo')
    def validate_invoice_no(cls, value: str):
        logger.info(f"getting data {re.match(invoice_number_pattern, value)}")
        if value == '':
            raise HTTPException(status_code=400, detail="Invoice no can not be blank")
        elif len(value) > 100:
            raise HTTPException(status_code=400, detail=f"Invoice number can not be greater than 100 {value}")
        elif not re.match(invoice_number_pattern, value):
            raise HTTPException(status_code=400, detail=f"Invalid invoice number format. Use only letters, numbers, spaces, and symbols: '-', '_', '/', '#'. Please check your input.")
        # elif value != "":
        #     cleaned_string = re.sub(r'[^a-zA-Z0-9\s]', '', value)
        #     if cleaned_string:
        #         cleaned_string = re.sub(r'\s+', ' ', cleaned_string)
        #         if not cleaned_string:
        #             raise HTTPException(status_code=400, detail="Invoice no can not accept only special character")
        #     else:
        #         raise HTTPException(status_code=400, detail="Invoice no can not accept only special character")
        return value

    @field_validator('invoiceDate')
    def validate_invoice_date(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="Invoice date can not be blank")
        elif len(value) > 10:
            raise HTTPException(status_code=400, detail=f"Invoice date can not be greater than 10 {value}")
        return value

    @field_validator('invoiceDate')
    def validate_invoice_dates(cls, value: date) -> date:
        from datetime import datetime
        try:
            dd = datetime.strptime(value, "%d/%m/%Y")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"date format except d/m/Y format  {value}")
        return value

    @field_validator('invoiceAmt')
    def validate_invoice_amount(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail=f"Invoice amount can not be blank  {value}")
        if value == '0':
            raise HTTPException(status_code=400, detail=f"Invoice amount should be greater than 0 {value}")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"Invoice number can not be greater than 20 {value}")
        elif not bool(re.match(amt_regex_pattern, value)):
            raise HTTPException(status_code=400, detail=f"Invalid invoice amount {value}")
        if '.' in value:
            amount_list = value.split('.')
            if len(amount_list) > 2:
                raise HTTPException(status_code=400, detail=f"Invalid invoice amount  {value}")
            elif len(amount_list[1]) > 2:
                raise HTTPException(status_code=400, detail=f"Invoice amount can not accept more than two digit value {value}")
        return value

    @field_validator('verifyGSTNFlag')
    def validate_verify_gst_flag(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="Verify gst flag can not be blank")
        elif value not in [True, False]:
            raise HTTPException(status_code=400, detail=f"Verify gst flag either True or False {value}")
        return value

    @field_validator('invoiceDueDate')
    def validate_invoice_due_date(cls, value: date) -> date:
        from datetime import datetime
        if len(value) > 10:
            raise HTTPException(status_code=400, detail=f"Invoice due date can not be greater than 10  {value}")
        elif value != "":
            try:
                dd = datetime.strptime(value, "%d/%m/%Y")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invoice due date format except d/m/Y format {value}")
            return value
        else:
            return value

    @model_validator(mode='after')
    def validate_field(self):
        if self.validationRefNo != "":
            validate_string = re.search(validation_ref_no_pattern, self.validationRefNo)
            if not validate_string:
                raise HTTPException(status_code=400, detail=f"validation Ref No can not accept special character {self.validationRefNo}")
            if self.validationType.lower() not in ['einvoice', 'ewaybill', 'gstfiling']:
                raise HTTPException(status_code=400, detail=f"validation type should be eInvoice, eWayBill, gstFiling {self.validationType}")
        if self.verifyGSTNFlag:
            if self.validationType.lower() not in ['einvoice', 'ewaybill', 'gstfiling']:
                raise HTTPException(status_code=400, detail=f"validation type should be eInvoice, eWayBill, gstFiling {self.validationType}")
            if not self.validationRefNo:
                raise HTTPException(status_code=400, detail="Validation reference no can not be blank")
        if self.validationType:
            if not self.validationRefNo:
                raise HTTPException(status_code=400, detail="Validation reference no can not be blank")

        return self


class InvoiceRequestSchema(BaseSchema):
    sellerGst: str
    buyerGst: str
    groupingId: Optional[str] = None
    ledgerData: List[InvoiceSchema] = Field(...)
    sellerIdentifierData: Optional[List[SellerData]] = Field(None)
    buyerIdentifierData: Optional[List[BuyerData]] = Field(None)

    @field_validator('groupingId')
    def validate_grouping_id(cls, value: str):
        if not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"grouping id can not accept special character {value}")
        if len(value) > 30:
            raise HTTPException(status_code=400, detail=f"grouping id can not be greater than 30 {value}")
        return value


    @field_validator('sellerGst')
    def validate_seller_gst(cls, value: str):
        if value == '':
            pass
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"seller gst can not accept special character {value}")
        elif len(value) > 20:
            raise HTTPException(status_code=400, detail=f"seller gst can not greater than 20 {value}")
        elif value != "":
            seller_gst_value = ValidationCheck.validate_gst(value)
            if not seller_gst_value:
                raise HTTPException(status_code=400, detail=f"seller gst is not valid {value}")
        return value

    @field_validator('buyerGst')
    def validate_buyer_gst(cls, value: str):
        if value == '':
            pass
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"buyer gst can not accept special character {value}")
        elif len(value) > 20:
            raise HTTPException(status_code=400, detail=f"buyer gst can not greater than 20 {value}")
        elif value != "":
            buyer_gst_value = ValidationCheck.validate_gst(value)
            if not buyer_gst_value:
                raise HTTPException(status_code=400, detail=f"buyer gst is not valid {value}")
        return value

    @model_validator(mode='after')
    def validate_field(self):
        import utils
        json_request_data = jsonable_encoder(self)
        validate_seller_identifier = utils.validate_seller_identifier(json_request_data)
        validate_buyer_identifier = utils.validate_buyer_identifier(json_request_data)
        invoice_date_response = utils.check_invoice_date(json_request_data)
        invoice_due_date_response = utils.check_invoice_due_date(json_request_data)
        duplicates_json_exist = utils.are_duplicates_exist(json_request_data.get('ledgerData'))
        duplicate_identifier_values = utils.check_for_duplicate_values(json_request_data)
        duplicate_pan_value = utils.check_for_duplicate_pan_values(json_request_data)
        duplicate_lei_value = utils.check_for_duplicate_lei_values(json_request_data)
        duplicate_cin_value = utils.check_for_duplicate_cin_values(json_request_data)
        duplicate_tax_no_value = utils.check_for_duplicate_tax_no_values(json_request_data)
        if not validate_seller_identifier:
            raise HTTPException(status_code=400, detail="Seller identifier data can not be blank if seller gst is blank")
        if not validate_buyer_identifier:
            raise HTTPException(status_code=400, detail="Buyer identifier data can not be blank if buyer gst is blank")
        if not invoice_date_response:
            raise HTTPException(status_code=400, detail="Invoice date is greater then current date")
        if invoice_due_date_response:
            raise HTTPException(status_code=400, detail="Invoice due date should be greater than invoice date")
        if duplicates_json_exist:
            raise HTTPException(status_code=400, detail="Duplicate invoice data found")
        if duplicate_identifier_values:
            raise HTTPException(status_code=400, detail="sellerIdNo and buyerIdNo cannot be same.")
        if duplicate_pan_value:
            raise HTTPException(status_code=400, detail="sellerIdNo and buyerIdNo cannot be same.")
        if duplicate_lei_value:
            raise HTTPException(status_code=400, detail="sellerIdNo and buyerIdNo cannot be same.")
        if duplicate_cin_value:
            raise HTTPException(status_code=400, detail="sellerIdNo and buyerIdNo cannot be same.")
        if duplicate_tax_no_value:
            raise HTTPException(status_code=400, detail="sellerIdNo and buyerIdNo cannot be same.")
        return self


class FinanceInvoiceData(BaseModel):
    invoiceNo: str
    fundingAmt: str
    fundingDate: str = Field(min_length=10, default='01/06/1989')
    dueDate: str
    fundingAmtFlag: FundingType
    adjustmentType: str
    adjustmentAmt: str

    # @field_validator('fundingDate')
    # def validate_start_date(cls, value: date) -> date:
    #     from datetime import datetime
    #     try:
    #         datetime.strptime(value, "%d/%m/%Y")
    #     except Exception as e:
    #         raise ValueError("date formate except d/m/Y formate")
    #     return value


class FinanceSchema(BaseSchema):
    requestId: str = Field(..., min_length=1, max_length=30)
    signature: str = Field(min_length=1)
    ledgerNo: str = Field(min_length=1)
    ledgerAmtFlag: FundingType
    ledgerCategory: str
    borrowerCategory: str
    ledgerData: List[FinanceInvoiceData] = Field(...)


class CheckStatusSchema(BaseSchema):
    ledgerNo: str = Field()

    @field_validator('ledgerNo')
    def validate_ledger_no(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="ledger no can not be blank")
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"ledger no can not accept special character {value}")
        elif len(value) > 100:
            raise HTTPException(status_code=400, detail=f"ledger no can not be greater than 100 {value}")
        elif value != "":
            cleaned_string = value.isnumeric()
            if not cleaned_string:
                raise HTTPException(status_code=400, detail=f"ledger no can have only numeric value {value}")
        return value


class CancelLedgerSchema(BaseSchema):
    ledgerNo: str
    cancellationReason: str

    @field_validator('ledgerNo')
    def validate_ledger_no(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="ledger no can not be blank")
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"ledger no can not accept special character {value}")
        elif len(value) >= 100:
            raise HTTPException(status_code=400, detail=f"ledger no can not be greater than 100 {value}")
        return value

    @field_validator('cancellationReason')
    def validate_cancellation_reason(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="cancellation reason can not be blank")
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"cancellation reason can not accept special character {value}")
        elif len(value) >= 250:
            raise HTTPException(status_code=400, detail=f"cancellation reason can not be greater than 250 {value}")
        return value


class EntityIdentifierData(BaseModel):
    entityIdType: str
    entityIdNo: str
    entityIdName: str
    ifsc: str

    @field_validator('entityIdNo')
    def validate_entity_id_no(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail=f"Entity id can not be blank {value}")
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"Entity id can not accept special character {value}")
        elif len(value) > 50:
            raise HTTPException(status_code=400, detail=f"Entity id can not be greater than 50 {value}")
        return value

    @field_validator('entityIdType')
    def validate_entity_id_type(cls, value):
        if value == "":
            raise HTTPException(status_code=400, detail=f"Entity id type can not be blank {value}")
        elif len(value) > 50:
            raise HTTPException(status_code=400, detail=f"Entity id type can not be greater than 50 {value}")
        elif value.lower() not in ['lei', 'gstin', 'pan', 'cin', 'tax_no', 'accountnumber']:
            raise HTTPException(status_code=400, detail=f"Invalid entity type {value}")

        return value

    @field_validator('entityIdName')
    def validate_entity_id_name(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail=f"Invalid entity name {value}")
        # elif not special_char_pattern.match(value):
        elif not re.match(seller_buyer_id_name_pattern, value):
            raise HTTPException(status_code=400, detail=f"Entity name can not accept special character {value}")
        elif len(value) > 50:
            raise HTTPException(status_code=400, detail=f"Entity name can not be greater than 50 {value}")
        return value

    @field_validator('ifsc')
    def validate_entity_ifsc(cls, value, values):
        logger.info(f"getting values {values}")
        if not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"IFSC can not accept special character {value}")
        if len(value) > 16:
            raise HTTPException(status_code=400, detail=f"IFSC can not be greater than 16 {value}")
        if values.data.get('entityIdType').lower() == "accountnumber":
            if value == "":
                raise HTTPException(status_code=400, detail=f"IFSC can not be blank {value}")
            elif values.data.get('entityIdType').lower() != "accountnumber":
                raise HTTPException(status_code=400, detail=f"Entity id type should be 'Account Number' for ifsc{value}")
        else:
            if value != "":
                raise HTTPException(status_code=400, detail=f"Entity id type should be 'Account Number' for ifsc {value}")
        return value

    # all identifier validation
    @model_validator(mode='after')
    def identifier_field(self):
        if self.entityIdType.lower() == "gstin":
            gst_value = ValidationCheck.validate_gst(self.entityIdNo)
            if not gst_value:
                raise HTTPException(status_code=400, detail=f"entity gst is not valid {self.entityIdNo}")
        elif self.entityIdType.lower() == 'lei':
            lei_value = ValidationCheck.validate_lei(self.entityIdNo)
            if not lei_value:
                raise HTTPException(status_code=400, detail=f"entity lei is not valid {self.entityIdNo}")
        elif self.entityIdType.lower() == 'pan':
            pan_value = ValidationCheck.validate_pan_card(self.entityIdNo)
            if not pan_value:
                raise HTTPException(status_code=400, detail=f"entity pan number is not valid {self.entityIdNo}")
        elif self.entityIdType.lower() == 'cin':
            cin_value = ValidationCheck.validate_cin(self.entityIdNo)
            if not cin_value:
                raise HTTPException(status_code=400, detail=f"entity cin is not valid {self.entityIdNo}")
        elif self.entityIdType.lower() == 'tax_no':
            pt_value = ValidationCheck.validate_pt(self.entityIdNo)
            if not pt_value:
                raise HTTPException(status_code=400, detail=f"entity tax no is not valid {self.entityIdNo}")
        return self


class EntityRegisterData(BaseModel):
    entityCode: str
    entityIdentifierData: List[EntityIdentifierData] = Field(...)

    @field_validator('entityCode')
    def validate_entity_code(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail=f"entity code can not be blank {value}")
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"entity code can not accept special character {value}")
        elif len(value) > 20:
            raise HTTPException(status_code=400, detail=f"entity code not be greater than 20 {value}")
        return value


class EntityRegistrationSchema(BaseSchema):
    entityRegisterData: List[EntityRegisterData] = Field(...)


class AsyncInvoiceSchema(BaseModel):
    validationType: str
    validationRefNo: str
    invoiceNo: str = Field()
    invoiceDate: str = Field(default='01/06/1989')
    invoiceAmt: str = Field()
    verifyGSTNFlag: bool
    invoiceDueDate: str = Field(default='01/06/1989')

    @field_validator('invoiceNo')
    def validate_invoice_no(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="Invoice no can not be blank")
        elif len(value) > 100:
            raise HTTPException(status_code=400, detail=f"Invoice no can not be greater than 100 {value}")
        elif not re.match(invoice_number_pattern, value):
            raise HTTPException(status_code=400, detail=f"Invalid invoice number format. Use only letters, numbers, spaces, and symbols: '-', '_', '/', '#'. Please check your input.")
        return value

    @field_validator('invoiceDate')
    def validate_invoice_date(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="invoice date can not be blank")
        elif len(value) > 10:
            raise HTTPException(status_code=400, detail=f"Invoice date can not be greater than 10 {value}")
        return value

    @field_validator('invoiceDate')
    def validate_start_date(cls, value: date) -> date:
        from datetime import datetime
        try:
            dd = datetime.strptime(value, "%d/%m/%Y")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"date format except d/m/Y format {value}")
            # raise ValueError("date formate except d/m/Y formate")
        return value

    @field_validator('invoiceAmt')
    def validate_invoice_amount(cls, value: float):
        if value == '':
            raise HTTPException(status_code=400, detail="invoice amount can not be blank")
        if value == '0':
            raise HTTPException(status_code=400, detail=f"invoice amount should be greater than 0 {value}")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"Invoice amount can not be greater than 20 {value}")
        elif not bool(re.match(amt_regex_pattern, value)):
            raise HTTPException(status_code=400, detail=f"Invalid invoice amount {value}")
        if '.' in value:
            amount_list = value.split('.')
            if len(amount_list) > 2:
                raise HTTPException(status_code=400, detail=f"Invalid invoice amount {value}")
            elif len(amount_list[1]) > 2:
                raise HTTPException(status_code=400, detail=f"Invoice amount can not accept more than two digit value {value}")
        return value

    @field_validator('verifyGSTNFlag')
    def validate_verify_gst_flag(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="verify gst flag can not be blank")
        elif value not in [True, False]:
            raise HTTPException(status_code=400, detail=f"verify gst flag either True or False {value}")
        return value

    @field_validator('invoiceDueDate')
    def validate_invoice_due_date(cls, value: date) -> date:
        from datetime import datetime
        if len(value) > 10:
            raise HTTPException(status_code=400, detail=f"Invoice due date can not be greater than 10 {value}")
        if value != "":
            try:
                dd = datetime.strptime(value, "%d/%m/%Y")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"date format except d/m/Y format {value}")
                # raise ValueError("date formate except d/m/Y formate")
            return value
        else:
            return value

    @model_validator(mode='after')
    def validate_field(self):
        if self.validationRefNo != "":
            validate_string = re.search(validation_ref_no_pattern, self.validationRefNo)
            if not validate_string:
                raise HTTPException(status_code=400, detail=f"validation Ref No can not accept special character {self.validationRefNo}")
            if self.validationType.lower() not in ['einvoice', 'ewaybill', 'gstfiling']:
                raise HTTPException(status_code=400, detail=f"validation type should be eInvoice, eWayBill, gstFiling {self.validationType}")
        if self.verifyGSTNFlag:
            if self.validationType.lower() not in ['einvoice', 'ewaybill', 'gstfiling']:
                raise HTTPException(status_code=400, detail=f"validation type should be eInvoice, eWayBill, gstFiling {self.validationType}")
            if not self.validationRefNo:
                raise HTTPException(status_code=400, detail=f"Validation reference no can not be blank {self.validationRefNo}")
        if self.validationType:
            if not self.validationRefNo:
                raise HTTPException(status_code=400, detail=f"Validation reference no can not be blank {self.validationType}")

        return self


class AsyncInvoiceRegistrationWithCodeSchema(BaseSchema):

    sellerCode: str
    buyerCode: str
    sellerGst: str
    buyerGst: str
    groupingId: Optional[str] = None
    ledgerData: List[AsyncInvoiceSchema] = Field(...)

    @field_validator('groupingId')
    def validate_grouping_id(cls, value: str):
        if not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"grouping id can not accept special character {value}")
        if len(value) > 30:
            raise HTTPException(status_code=400, detail=f"grouping id can not be greater than 30 {value}")
        return value

    @field_validator('sellerCode')
    def validate_seller_code(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="seller code can not be blank")
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"seller code can not accept special character {value}")
        elif len(value) > 20:
            raise HTTPException(status_code=400, detail=f"seller code can not be greater than 20 {value}")
        return value

    @field_validator('buyerCode')
    def validate_buyer_code(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail=f"buyer code can not be blank {value}")
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"buyer code can not accept special character {value}")
        elif len(value) > 20:
            raise HTTPException(status_code=400, detail=f"buyer code can not be greater than 20 {value}")
        return value

    @field_validator('sellerGst')
    def validate_seller_gst(cls, value: str):
        if value == '':
            pass
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"seller gst can not accept special character {value}")
        elif len(value) > 20:
            raise HTTPException(status_code=400, detail=f"seller gst can not be greater than 20 {value}")
        elif value != "":
            seller_gst_value = ValidationCheck.validate_gst(value)
            if not seller_gst_value:
                raise HTTPException(status_code=400, detail=f"seller gst is not valid {value}")
        return value

    @field_validator('buyerGst')
    def validate_buyer_gst(cls, value: str):
        if value == '':
            pass
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"buyer gst can not accept special character {value}")
        elif len(value) > 20:
            raise HTTPException(status_code=400, detail=f"buyer gst can not be greater than 20 {value}")
        elif value != "":
            buyer_gst_value = ValidationCheck.validate_gst(value)
            if not buyer_gst_value:
                raise HTTPException(status_code=400, detail=f"buyer gst is not valid {value}")
        return value

    @model_validator(mode='after')
    def validate_field(self):
        import utils
        json_request_data = jsonable_encoder(self)
        invoice_date_response = utils.check_invoice_date(json_request_data)
        invoice_due_date_response = utils.check_invoice_due_date(json_request_data)
        duplicates_json_exist = utils.are_duplicates_exist(json_request_data.get('ledgerData'))
        if not invoice_date_response:
            raise HTTPException(status_code=400, detail=f"Invoice date is greater then current date")
        if invoice_due_date_response:
            raise HTTPException(status_code=400, detail=f"Invoice due date should be greater than invoice date")
        if duplicates_json_exist:
            raise HTTPException(status_code=400, detail=f"Duplicate invoice data found")
        return self


class CheckEnquirySchema(BaseModel):
    requestId: str
    @field_validator('requestId')
    def validate_request_id(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="request id can not be blank")
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"request id can not accept special character {value}")
        elif len(value) >= 30:
            raise HTTPException(status_code=400, detail=f"request id can not be greater than 30 {value}")
        return value


class AsyncFinanceInvoiceData(BaseModel):
    validationType: str
    validationRefNo: str
    invoiceNo: str
    financeRequestAmt: str
    financeRequestDate: str = Field(default='01/06/1989')
    dueDate: str
    fundingAmtFlag: str
    adjustmentType: str
    adjustmentAmt: str
    invoiceDate: str
    invoiceAmt: str

    @model_validator(mode='after')
    def validate_field(self):
        if not date_special_char_pattern.match(str(self.financeRequestDate)):
            raise HTTPException(status_code=400, detail=f"financeRequestDate can not accept special character {self.financeRequestDate}")
        if not date_special_char_pattern.match(str(self.dueDate)):
            raise HTTPException(status_code=400, detail=f"dueDate can not accept special character {self.dueDate}")
        if not special_char_pattern.match(self.fundingAmtFlag):
            raise HTTPException(status_code=400, detail=f"fundingAmtFlag can not accept special character {self.fundingAmtFlag}")
        if not special_char_pattern.match(str(self.adjustmentType)):
            raise HTTPException(status_code=400, detail=f"adjustmentType can not accept special character {self.adjustmentType}")
        if not date_special_char_pattern.match(str(self.invoiceDate)):
            raise HTTPException(status_code=400, detail=f"invoiceDate can not accept special character  {self.invoiceDate}")
        if str(self.validationType) == '' and str(self.validationRefNo) != '':
            raise HTTPException(status_code=400, detail="validationType should not be blank")
        if str(self.validationRefNo) != '':
            validate_string = re.search(validation_ref_no_pattern, str(self.validationRefNo))
            if not validate_string:
                raise HTTPException(status_code=400, detail=f"validation Ref No can not accept special character  {self.validationRefNo}")
        if str(self.validationRefNo) == '' and str(self.validationType) != '':
            raise HTTPException(status_code=400, detail="validationRefNo should not be blank")

        check_decimal_precision('adjustmentAmt', str(self.adjustmentAmt))
        check_decimal_precision('financeRequestAmt', str(self.financeRequestAmt))
        check_decimal_precision('invoiceAmt', str(self.invoiceAmt))
        return self

    @field_validator('validationType')
    def validate_validation_type(cls, value: str):
        # if value == '':
        #     raise HTTPException(status_code=400, detail="validationType can not be blank")
        # else:
        if value != '':
            if not value.lower() in ('einvoice', 'ewaybill', 'gstfiling'):
                raise HTTPException(status_code=400, detail=f"validationType can be eInvoice, eWayBill or gstFiling {value}")
        return value

    # @field_validator('validationRefNo')
    # def validate_validation_ref_no(cls, value: str):
    #     # if value == '':
    #     #     raise HTTPException(status_code=400, detail="validationRefNo can not be blank")
    #     if value != '':
    #         if len(value) > 100:
    #             raise HTTPException(status_code=400, detail="validationRefNo can not be greater than 100")
    #     return value

    @field_validator('invoiceNo')
    def validate_invoice_no(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="Invoice no can not be blank")
        elif len(value) > 100:
            raise HTTPException(status_code=400, detail=f"Invoice no can not be greater than 100 {value}")
        # elif value != "":
        #     cleaned_string = re.sub(r'[^a-zA-Z0-9\s]', '', value)
        #     if cleaned_string:
        #         cleaned_string = re.sub(r'\s+', ' ', cleaned_string)
        #         if not cleaned_string:
        #             raise HTTPException(status_code=400, detail="Invoice no can not accept only special character")
        #     else:
        #         raise HTTPException(status_code=400, detail="Invoice no can not accept only special character")
        elif not re.match(invoice_number_pattern, value):
            raise HTTPException(status_code=400, detail=f"Invalid invoice number format. Use only letters, numbers, spaces, and symbols: '-', '_', '/', '#'. Please check your input.")
        return value

    @field_validator('financeRequestAmt')
    def validate_finance_request_amount(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="financeRequestAmt can not be blank")
        if value == '0':
            raise HTTPException(status_code=400, detail=f"financeRequestAmt should be greater than 0 {value}")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"financeRequestAmt can not be greater than 20 {value}")
        return value

    @field_validator('financeRequestDate')
    def validate_finance_request_date(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="financeRequest Date can not be blank")
        elif len(value) > 10:
            raise HTTPException(status_code=400, detail=f"financeRequest Date can not be greater than 10 {value}")
        return value

    @field_validator('financeRequestDate')
    def validate_finance_request_dates(cls, value: date) -> date:
        from datetime import datetime
        try:
            dd = datetime.strptime(value, "%d/%m/%Y")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"date format accept d/m/Y format {value}")
        return value

    @field_validator('dueDate')
    def validate_due_date(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="dueDate can not be blank")
        elif len(value) > 10:
            raise HTTPException(status_code=400, detail=f"due Date can not be greater than 10 {value}")
        return value

    @field_validator('dueDate')
    def validate_due_dates(cls, value: date) -> date:
        from datetime import datetime
        try:
            dd = datetime.strptime(value, "%d/%m/%Y")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"date format except d/m/Y format {value}")
            # raise ValueError("date formate except d/m/Y formate")
        return value

    @field_validator('fundingAmtFlag')
    def validate_funding_amt_flag(cls, value: str):
        # if value == '':
        #     raise HTTPException(status_code=400, detail="fundingAmtFlag can not be blank")
        if len(value) > 20:
            raise HTTPException(status_code=400, detail=f"funding amt flag can not be greater than 20 {value}")
        elif value != '':
            if not value.lower() in ('full', 'partial'):
                raise HTTPException(status_code=400, detail=f"Funding amt flag can be full or partial {value}")
        return value

    @field_validator('adjustmentType')
    def validate_adjustment_type(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="adjustmentType can not be blank")
        elif len(value) > 30:
            raise HTTPException(status_code=400, detail=f"adjustmentType can not be greater than 30 {value}")
        else:
            if not value.lower() in ('none', 'advance', 'creditnote'):
                raise HTTPException(status_code=400, detail=f"adjustmentType can be none, advance or creditnote {value}")
        return value

    @field_validator('adjustmentAmt')
    def validate_adjustment_amt(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="adjustmentAmt can not be blank")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"adjustmentAmt can not be greater than 20 {value}")
        return value

    @field_validator('invoiceDate')
    def validate_invoice_date(cls, value: date) -> date:
        if value == '':
            raise HTTPException(status_code=400, detail="Invoice date can not be blank")
        elif len(str(value)) > 10:
            raise HTTPException(status_code=400, detail=f"Invoice date can not be greater than 10 {value}")
        elif value != '':
            from datetime import datetime
            try:
                dd = datetime.strptime(value, "%d/%m/%Y")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"date format except d/m/Y format {value}")
        return value

    @field_validator('invoiceAmt')
    def validate_invoice_amount(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="invoiceAmt can not be blank")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"invoiceAmt can not be greater than 20 digit {value}")
        return value


class AsyncFinanceSchema(BaseSchema):
    ledgerNo: str
    ledgerAmtFlag: str
    lenderCategory: str
    lenderName: str
    lenderCode: str
    borrowerCategory: str
    ledgerData: List[AsyncFinanceInvoiceData] = Field(...)

    @model_validator(mode='after')
    def validate_field(self):
        if not special_char_pattern.match(self.requestId):
            raise HTTPException(status_code=400, detail=f"requestId can not accept special character {self.requestId}")
        if not special_char_pattern.match(str(self.ledgerNo)):
            raise HTTPException(status_code=400, detail=f"ledgerNo can not accept special character {self.ledgerNo}")
        if not special_char_pattern.match(str(self.ledgerAmtFlag)):
            raise HTTPException(status_code=400, detail=f"ledgerAmtFlag can not accept special character {self.ledgerAmtFlag}")
        if not special_char_pattern.match(self.lenderCategory):
            raise HTTPException(status_code=400, detail=f"lenderCategory can not accept special character {self.lenderCategory}")
        if not lender_name_pattern.match(self.lenderName):
            raise HTTPException(status_code=400, detail=f"lenderName can not accept special character {self.lenderName}")
        if not special_char_pattern.match(self.lenderCode):
            raise HTTPException(status_code=400, detail=f"lenderCode can not accept special character {self.lenderCode}")
        if not special_char_pattern.match(self.borrowerCategory):
            raise HTTPException(status_code=400, detail=f"borrowerCategory can not accept special character {self.borrowerCategory}")
        if not special_char_pattern.match(self.signature):
            raise HTTPException(status_code=400, detail=f"signature can not accept special character {self.signature}")
        return self

    @field_validator('ledgerNo')
    def validate_ledger_no(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="ledgerNo can not be blank")
        elif len(value) > 100:
            raise HTTPException(status_code=400, detail=f"ledgerNo can not be greater than 100 {value}")
        elif value != "":
            # cleaned_string = re.sub(r'[^.-@!#$%^&*()<>?/\|}{~:a-zA-Z\b\s]', '', value)
            cleaned_string = value.isnumeric()
            if not cleaned_string:
                raise HTTPException(status_code=400, detail=f"ledger no can have only numeric value {value}")
        return value

    @field_validator('ledgerAmtFlag')
    def validate_ledger_amt_flag(cls, value: str):
        if value != '':
            if not value.lower() in ('full', 'partial'):
                raise HTTPException(status_code=400, detail=f"ledgerAmtFlag can be full or partial {value}")
        return value

    @field_validator('lenderCategory')
    def validate_lender_category(cls, value: str):
        # if value == '':
        #     raise HTTPException(status_code=400, detail="lenderCategory can not be blank")
        if value != '':
            if len(value) > 50:
                raise HTTPException(status_code=400, detail=f"lenderCategory can not be greater than 50 {value}")
        return value

    @field_validator('lenderName')
    def validate_lender_name(cls, value: str):
        if value != "":
            if len(value) > 64:
                raise HTTPException(status_code=400, detail=f"lenderName can not be greater than 64 char {value}")
            # cleaned_string = re.sub(r'[^.-@!#$%^&*()<>?/\|}{~:\s]', '', value) #[.-@!#$%^&*()<>?/\|}{~:\b\s]
            # cleaned_string = value.isalnum()
            # if not cleaned_string:
            #     raise HTTPException(status_code=400, detail="lender name can not have special character")
        return value

    @field_validator('lenderCode')
    def validate_lender_code(cls, value: str):
        if value != "":
            if len(value) > 20:
                raise HTTPException(status_code=400, detail=f"lenderCode can not be greater than 20 {value}")
        return value

    @field_validator('borrowerCategory')
    def validate_borrower_category(cls, value: str):
        if len(value) > 50:
            raise HTTPException(status_code=400, detail=f"borrowerCategory can not be greater than 50 {value}")
        return value


class AsyncBulkFinanceInvoiceData(BaseModel):
    validationType: str
    validationRefNo: str
    invoiceNo: str
    financeRequestAmt: str
    financeRequestDate: str = Field(default='01/06/1989')
    dueDate: str
    fundingAmtFlag: str
    adjustmentType: str
    adjustmentAmt: str
    invoiceDate: str
    invoiceAmt: str

    @model_validator(mode='after')
    def validate_field(self):
        if not date_special_char_pattern.match(str(self.financeRequestDate)):
            raise HTTPException(status_code=400, detail="financeRequestDate can not accept special character")
        if not date_special_char_pattern.match(str(self.dueDate)):
            raise HTTPException(status_code=400, detail="dueDate can not accept special character")
        if not special_char_pattern.match(self.fundingAmtFlag):
            raise HTTPException(status_code=400, detail="fundingAmtFlag can not accept special character")
        if not special_char_pattern.match(str(self.adjustmentType)):
            raise HTTPException(status_code=400, detail="adjustmentType can not accept special character")
        if not date_special_char_pattern.match(str(self.invoiceDate)):
            raise HTTPException(status_code=400, detail="invoiceDate can not accept special character")
        if str(self.validationType) == '' and str(self.validationRefNo) != '':
            raise HTTPException(status_code=400, detail="validationType should not be blank")
        if str(self.validationRefNo) == '' and str(self.validationType) != '':
            raise HTTPException(status_code=400, detail="validationRefNo should not be blank")

        check_decimal_precision('adjustmentAmt', str(self.adjustmentAmt))
        check_decimal_precision('financeRequestAmt', str(self.financeRequestAmt))
        check_decimal_precision('invoiceAmt', str(self.invoiceAmt))
        return self

    @field_validator('validationType')
    def validate_validation_type(cls, value: str):
        # if value == '':
        #     raise HTTPException(status_code=400, detail="validationType can not be blank")
        if value != "":
            if not value.lower() in ('einvoice', 'ewaybill', 'gstfiling'):
                raise HTTPException(status_code=400, detail=f"validationType can be eInvoice, eWayBill or gstFiling {value}")
        return value

    # @field_validator('validationRefNo')
    # def validate_validation_ref_no(cls, value: str):
    #     if value == '':
    #         raise HTTPException(status_code=400, detail="validationRefNo can not be blank")
    #     elif len(value) > 100:
    #         raise HTTPException(status_code=400, detail="validationRefNo can not be greater than 100")
    #     return value

    @field_validator('invoiceNo')
    def validate_invoice_no(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="Invoice no can not be blank")
        elif len(value) > 100:
            raise HTTPException(status_code=400, detail=f"Invoice no can not be greater than 100 {value}")
        # elif value != "":
        #     cleaned_string = re.sub(r'[^a-zA-Z0-9\s]', '', value)
        #     if cleaned_string:
        #         cleaned_string = re.sub(r'\s+', ' ', cleaned_string)
        #         if not cleaned_string:
        #             raise HTTPException(status_code=400, detail="Invoice no can not accept only special character")
        #     else:
        #         raise HTTPException(status_code=400, detail="Invoice no can not accept only special character")
        elif not re.match(invoice_number_pattern, value):
            raise HTTPException(status_code=400, detail="Invalid invoice number format. Use only letters, numbers, spaces, and symbols: '-', '_', '/', '#'. Please check your input.")
        return value

    @field_validator('financeRequestAmt')
    def validate_finance_request_amount(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="financeRequestAmt can not be blank")
        if value == '0':
            raise HTTPException(status_code=400, detail=f"financeRequestAmt should be greater than 0 {value}")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"financeRequestAmt can not be greater than 20 {value}")
        return value

    @field_validator('financeRequestDate')
    def validate_finance_request_date(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="financeRequest Date can not be blank")
        elif len(value) > 10:
            raise HTTPException(status_code=400, detail=f"financeRequest Date can not be greater than 10 {value}")
        return value

    @field_validator('financeRequestDate')
    def validate_finance_request_dates(cls, value: date) -> date:
        from datetime import datetime
        try:
            dd = datetime.strptime(value, "%d/%m/%Y")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"date format accept d/m/Y format {value}")
        return value

    @field_validator('dueDate')
    def validate_due_date(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="dueDate can not be blank")
        elif len(value) > 10:
            raise HTTPException(status_code=400, detail=f"due Date can not be greater than 10 {value}")
        return value

    @field_validator('dueDate')
    def validate_due_dates(cls, value: date) -> date:
        from datetime import datetime
        try:
            dd = datetime.strptime(value, "%d/%m/%Y")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"date format except d/m/Y format {value}")
            # raise ValueError("date formate except d/m/Y formate")
        return value

    @field_validator('fundingAmtFlag')
    def validate_funding_amt_flag(cls, value: str):
        # if value == '':
        #     raise HTTPException(status_code=400, detail="fundingAmtFlag can not be blank")
        if len(value) > 20:
            raise HTTPException(status_code=400, detail=f"funding amt flag can not be greater than 20 {value}")
        elif value != '':
            if not value.lower() in ('full', 'partial'):
                raise HTTPException(status_code=400, detail=f"Funding amt flag can be full or partial {value}")
        return value

    @field_validator('adjustmentType')
    def validate_adjustment_type(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="adjustmentType can not be blank")
        elif len(value) > 30:
            raise HTTPException(status_code=400, detail=f"adjustmentType can not be greater than 30 {value}")
        else:
            if not value.lower() in ('none', 'advance', 'creditnote'):
                raise HTTPException(status_code=400, detail=f"adjustmentType can be none, advance or creditnote {value}")
        return value

    @field_validator('adjustmentAmt')
    def validate_adjustment_amt(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="adjustmentAmt can not be blank")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"adjustmentAmt can not be greater than 20 {value}")
        return value

    @field_validator('invoiceDate')
    def validate_invoice_date(cls, value: date) -> date:
        if value == '':
            raise HTTPException(status_code=400, detail="Invoice date can not be blank")
        elif len(str(value)) > 10:
            raise HTTPException(status_code=400, detail=f"Invoice date can not be greater than 10 {value}")
        elif value != '':
            from datetime import datetime
            try:
                dd = datetime.strptime(value, "%d/%m/%Y")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"date format except d/m/Y format {value}")
        return value

    @field_validator('invoiceAmt')
    def validate_invoice_amount(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="invoiceAmt can not be blank")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"invoiceAmt can not be greater than 20 digit {value}")
        return value


class AsyncBulkFinanceSchema(BaseSchema):
    ledgerNo: str
    ledgerAmtFlag: str
    lenderCategory: str
    lenderName: str
    lenderCode: str
    borrowerCategory: str
    ledgerData: List[AsyncFinanceInvoiceData] = Field(...)

    @model_validator(mode='after')
    def validate_field(self):
        if not special_char_pattern.match(self.requestId):
            raise HTTPException(status_code=400, detail=f"requestId can not accept special character {self.requestId}")
        if not special_char_pattern.match(str(self.ledgerNo)):
            raise HTTPException(status_code=400, detail=f"ledgerNo can not accept special character {self.ledgerNo}")
        if not special_char_pattern.match(str(self.ledgerAmtFlag)):
            raise HTTPException(status_code=400, detail=f"ledgerAmtFlag can not accept special character {self.ledgerAmtFlag}")
        if not special_char_pattern.match(self.lenderCategory):
            raise HTTPException(status_code=400, detail=f"lenderCategory can not accept special character {self.lenderCategory}")
        if not lender_name_pattern.match(self.lenderName):
            raise HTTPException(status_code=400, detail=f"lenderName can not accept special character {self.lenderName}")
        if not special_char_pattern.match(self.lenderCode):
            raise HTTPException(status_code=400, detail=f"lenderCode can not accept special character {self.lenderCode}")
        if not special_char_pattern.match(self.borrowerCategory):
            raise HTTPException(status_code=400, detail=f"borrowerCategory can not accept special character {self.borrowerCategory}")
        if not special_char_pattern.match(self.signature):
            raise HTTPException(status_code=400, detail=f"signature can not accept special character {self.signature}")
        return self

    @field_validator('ledgerNo')
    def validate_ledger_no(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="ledgerNo can not be blank")
        elif len(value) > 100:
            raise HTTPException(status_code=400, detail=f"ledgerNo can not be greater than 100 {value}")
        elif value != "":
            # cleaned_string = re.sub(r'[^.-@!#$%^&*()<>?/\|}{~:a-zA-Z\b\s]', '', value)
            cleaned_string = value.isnumeric()
            if not cleaned_string:
                raise HTTPException(status_code=400, detail=f"ledger no can have only numeric value {value}")
        return value

    @field_validator('ledgerAmtFlag')
    def validate_ledger_amt_flag(cls, value: str):
        if value != '':
            if not value.lower() in ('full', 'partial'):
                raise HTTPException(status_code=400, detail=f"ledgerAmtFlag can be full or partial {value}")
        return value

    @field_validator('lenderCategory')
    def validate_lender_category(cls, value: str):
        # if value == '':
        #     raise HTTPException(status_code=400, detail="lenderCategory can not be blank")
        if value != '':
            if len(value) > 50:
                raise HTTPException(status_code=400, detail=f"lenderCategory can not be greater than 50 {value}")
        return value

    @field_validator('lenderName')
    def validate_lender_name(cls, value: str):
        if value != "":
            if len(value) > 64:
                raise HTTPException(status_code=400, detail=f"lenderName can not be greater than 64 char {value}")
            # cleaned_string = re.sub(r'[^.-@!#$%^&*()<>?/\|}{~:\s]', '', value) #[.-@!#$%^&*()<>?/\|}{~:\b\s]
            # cleaned_string = value.isalnum()
            # if not cleaned_string:
            #     raise HTTPException(status_code=400, detail="lender name can not have special character")
        return value

    @field_validator('lenderCode')
    def validate_lender_code(cls, value: str):
        if value != "":
            if len(value) > 20:
                raise HTTPException(status_code=400, detail=f"lenderCode can not be greater than 20 {value}")
        return value

    @field_validator('borrowerCategory')
    def validate_borrower_category(cls, value: str):
        if len(value) > 50:
            raise HTTPException(status_code=400, detail=f"borrowerCategory can not be greater than 50 {value}")
        return value


class AsyncDisburseInvoiceData(BaseModel):
    validationType: str
    validationRefNo: str
    invoiceNo: str
    disbursedFlag: str
    disbursedAmt: str
    disbursedDate: str
    dueAmt: str
    dueDate: str
    invoiceDate: str
    invoiceAmt: str

    @model_validator(mode='after')
    def validate_field(self):
        if not special_char_pattern.match(str(self.disbursedFlag)):
            raise HTTPException(status_code=400, detail=f"disbursedFlag can not accept special character {self.disbursedFlag}")
        if not date_special_char_pattern.match(self.disbursedDate):
            raise HTTPException(status_code=400, detail=f"disbursedDate can not accept special character {self.disbursedDate}")
        if not date_special_char_pattern.match(self.dueDate):
            raise HTTPException(status_code=400, detail=f"dueDate can not accept special character {self.dueDate}")
        if not date_special_char_pattern.match(self.invoiceDate):
            raise HTTPException(status_code=400, detail=f"invoiceDate can not accept special character {self.invoiceDate}")
        if str(self.validationType) == '' and str(self.validationRefNo) != '':
            raise HTTPException(status_code=400, detail="validationType should not be blank")
        if str(self.validationRefNo) != '':
            validate_string = re.search(validation_ref_no_pattern, str(self.validationRefNo))
            if not validate_string:
                raise HTTPException(status_code=400, detail=f"validation Ref No can not accept special character {self.validationRefNo}")
        if str(self.validationRefNo) == '' and str(self.validationType) != '':
            raise HTTPException(status_code=400, detail="validationRefNo should not be blank")

        check_decimal_precision('disbursedAmt', str(self.disbursedAmt))
        check_decimal_precision('dueAmt', str(self.dueAmt))
        check_decimal_precision('invoiceAmt', str(self.invoiceAmt))
        return self

    @field_validator('validationType')
    def validate_validation_type(cls, value: str):
        # if value == '':
        #     raise HTTPException(status_code=400, detail="validationType can not be blank")
        # else:
        if value != '':
            if not value.lower() in ('einvoice', 'ewaybill', 'gstfiling'):
                raise HTTPException(status_code=400, detail=f"validationType can be eInvoice, eWayBill or gstFiling {value}")
        return value

    @field_validator('validationRefNo')
    def validate_validation_ref_no(cls, value: str):
        # if value == '':
        #     raise HTTPException(status_code=400, detail="validationRefNo can not be blank")
        if value != '':
            if len(value) > 100:
                raise HTTPException(status_code=400, detail=f"validationRefNo can not be greater than 100 {value}")
        return value

    @field_validator('invoiceNo')
    def validate_invoice_no(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="InvoiceNo can not be blank")
        elif len(value) > 100:
            raise HTTPException(status_code=400, detail=f"InvoiceNo can not be greater than 100 {value}")
        # elif value != "":
        #     cleaned_string = re.sub(r'[^a-zA-Z0-9\s]', '', value)
        #     if cleaned_string:
        #         cleaned_string = re.sub(r'\s+', ' ', cleaned_string)
        #         if not cleaned_string:
        #             raise HTTPException(status_code=400, detail="Invoice no can not accept only special character")
        #     else:
        #         raise HTTPException(status_code=400, detail="Invoice no can not accept only special character")
        elif not re.match(invoice_number_pattern, value):
            raise HTTPException(status_code=400, detail=f"Invalid invoice number format. Use only letters, numbers, spaces, and symbols: '-', '_', '/', '#'. Please check your input.")
        return value

    @field_validator('disbursedFlag')
    def validate_disbursed_flag(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="disbursedFlag can not be blank")
        else:
            if not value.lower() in ('full', 'partial'):
                raise HTTPException(status_code=400, detail=f"disbursedFlag can be full or partial {value}")
        return value

    @field_validator('disbursedAmt')
    def validate_disbursed_amt(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="disbursedAmt can not be blank")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"disbursedAmt can not be greater than 20 digit {value}")
        return value

    @field_validator('disbursedDate')
    def validate_disbursed_date(cls, value: date) -> date:
        if value == '':
            raise HTTPException(status_code=400, detail="disbursed date can not be blank")
        elif len(str(value)) > 10:
            raise HTTPException(status_code=400, detail=f"disbursedDate can not be greater than 10 {value}")
        elif value != '':
            from datetime import datetime
            try:
                dd = datetime.strptime(value, "%d/%m/%Y")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"date format accept d/m/Y format {value}")
        return value

    @field_validator('dueAmt')
    def validate_due_amt(cls, value: int):
        if value == '':
            raise HTTPException(status_code=400, detail="dueAmt can not be blank")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"dueAmt can not be greater than 20 digit {value}")
        return value

    @field_validator('dueDate')
    def validate_due_date(cls, value: date) -> date:
        if value == '':
            raise HTTPException(status_code=400, detail="dueDate can not be blank")
        elif len(str(value)) > 10:
            raise HTTPException(status_code=400, detail=f"dueDate can not be greater than 10 {value}")
        elif value != '':
            from datetime import datetime
            try:
                dd = datetime.strptime(value, "%d/%m/%Y")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"date format except d/m/Y format {value}")
        return value

    @field_validator('invoiceDate')
    def validate_invoice_date(cls, value: date) -> date:
        if value == '':
            raise HTTPException(status_code=400, detail="invoiceDate can not be blank")
        elif len(str(value)) > 10:
            raise HTTPException(status_code=400, detail=f"invoiceDate can not be greater than 10 {value}")
        elif value != '':
            from datetime import datetime
            try:
                dd = datetime.strptime(value, "%d/%m/%Y")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"date format except d/m/Y format {value}")
        return value

    @field_validator('invoiceAmt')
    def validate_invoice_amount(cls, value: int):
        if value == '':
            raise HTTPException(status_code=400, detail="invoiceAmt can not be blank")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"invoiceAmt can not be greater than 20 digit {value}")
        return value


class AsyncDisburseSchema(BaseSchema):
    ledgerNo: str
    lenderCategory: str
    lenderName: str
    lenderCode: str
    ledgerData: List[AsyncDisburseInvoiceData] = Field(...)

    @model_validator(mode='after')
    def validate_field(self):
        if not special_char_pattern.match(self.requestId):
            raise HTTPException(status_code=400, detail=f"requestId can not accept special character {self.requestId}")
        if not special_char_pattern.match(str(self.ledgerNo)):
            raise HTTPException(status_code=400, detail=f"ledgerNo can not accept special character {self.ledgerNo}")
        if not special_char_pattern.match(self.signature):
            raise HTTPException(status_code=400, detail=f"signature can not accept special character {self.signature}")
        if not special_char_pattern.match(str(self.lenderCategory)):
            raise HTTPException(status_code=400, detail=f"lenderCategory can not accept special character {self.lenderCategory}")
        if not lender_name_pattern.match(self.lenderName):
            raise HTTPException(status_code=400, detail=f"lenderName can not accept special character {self.lenderName}")
        if not special_char_pattern.match(str(self.lenderCode)):
            raise HTTPException(status_code=400, detail=f"lenderCode can not accept special character {self.lenderCode}")
        return self

    @field_validator('ledgerNo')
    def validate_ledger_no(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="ledgerNo can not be blank")
        elif len(value) > 100:
            raise HTTPException(status_code=400, detail=f"ledgerNo can not be greater than 100 {value}")
        elif value != "":
            cleaned_string = value.isnumeric()
            if not cleaned_string:
                raise HTTPException(status_code=400, detail=f"ledger no can have only numeric value {value}")
        return value

    @field_validator('lenderCategory')
    def validate_lender_category(cls, value: str):
        # if value == '':
        #     raise HTTPException(status_code=400, detail="lenderCategory can not be blank")
        if value != '':
            if len(value) > 50:
                raise HTTPException(status_code=400, detail=f"lenderCategory can not be greater than 50 {value}")
        return value

    @field_validator('lenderName')
    def validate_lender_name(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="lender name can not be blank")
        elif len(value) > 64:
            raise HTTPException(status_code=400, detail=f"lenderName can not be greater than 64 {value}")
        # elif value != "":
        #     # cleaned_string = re.sub(r'[^.-@!#$%^&*()<>?/\|}{~:\s]', '', value) #[.-@!#$%^&*()<>?/\|}{~:\b\s]
        #     cleaned_string = value.isalnum()
        #     if not cleaned_string:
        #         raise HTTPException(status_code=400, detail="lender name can not have special character")
        return value

    @field_validator('lenderCode')
    def validate_lender_code(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="lenderCode can not be blank")
        if len(value) > 20:
            raise HTTPException(status_code=400, detail=f"lenderCode can not be greater than 20 {value}")
        return value


class AsyncRepaymentInvoiceData(BaseModel):
    validationType: str
    validationRefNo: str
    invoiceNo: str
    assetClassification: str
    dueAmt: str
    dueDate: str
    repaymentType: str
    repaymentFlag: str
    repaymentAmt: str
    repaymentDate: str
    pendingDueAmt: str
    dpd: str
    invoiceDate: str
    invoiceAmt: str

    @model_validator(mode='after')
    def validate_field(self):
        if not special_char_pattern.match(str(self.assetClassification)):
            raise HTTPException(status_code=400, detail=f"assetClassification can not accept special character {self.assetClassification}")
        if not date_special_char_pattern.match(str(self.dueDate)):
            raise HTTPException(status_code=400, detail=f"dueDate can not accept special character {self.dueDate}")
        if not special_char_pattern.match(self.repaymentType):
            raise HTTPException(status_code=400, detail=f"repaymentType can not accept special character {self.repaymentType}")
        if not special_char_pattern.match(str(self.repaymentFlag)):
            raise HTTPException(status_code=400, detail=f"repaymentFlag can not accept special character {self.repaymentFlag}")
        if not date_special_char_pattern.match(str(self.repaymentDate)):
            raise HTTPException(status_code=400, detail=f"repaymentDate can not accept special character {self.repaymentDate}")
        if not special_char_pattern.match(str(self.dpd)):
            raise HTTPException(status_code=400, detail=f"dpd can not accept special character {self.dpd}")
        if not date_special_char_pattern.match(str(self.invoiceDate)):
            raise HTTPException(status_code=400, detail=f"invoiceDate can not accept special character {self.invoiceDate}")
        if str(self.validationType) == '' and str(self.validationRefNo) != '':
            raise HTTPException(status_code=400, detail="validationType should not be blank")
        if str(self.validationRefNo) != '':
            validate_string = re.search(validation_ref_no_pattern, str(self.validationRefNo))
            if not validate_string:
                raise HTTPException(status_code=400, detail=f"validation Ref No can not accept special character {self.validationRefNo}")
        if str(self.validationRefNo) == '' and str(self.validationType) != '':
            raise HTTPException(status_code=400, detail="validationRefNo should not be blank")

        check_decimal_precision('dueAmt', str(self.dueAmt))
        check_decimal_precision('pendingDueAmt', str(self.pendingDueAmt))
        check_decimal_precision('invoiceAmt', str(self.invoiceAmt))
        check_decimal_precision('repaymentAmt', str(self.repaymentAmt))
        return self

    @field_validator('validationType')
    def validate_validation_type(cls, value: str):
        # if value == '':
        #     raise HTTPException(status_code=400, detail="validationType can not be blank")
        # else:
        if value != '':
            if not value.lower() in ('einvoice', 'ewaybill', 'gstfiling'):
                raise HTTPException(status_code=400, detail=f"validationType can be eInvoice, eWayBill or gstFiling {value}")
        return value

    # @field_validator('validationRefNo')
    # def validate_validation_ref_no(cls, value: str):
    #     # if value == '':
    #     #     raise HTTPException(status_code=400, detail="validationRefNo can not be blank")
    #     if value != '':
    #         if len(value) > 100:
    #             raise HTTPException(status_code=400, detail="validationRefNo can not be greater than 100")
    #     return value

    @field_validator('invoiceNo')
    def validate_invoice_no(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="InvoiceNo can not be blank")
        elif len(value) > 100:
            raise HTTPException(status_code=400, detail=f"InvoiceNo can not be greater than 100 {value}")
        # elif value != "":
        #     cleaned_string = re.sub(r'[^a-zA-Z0-9\s]', '', value)
        #     if cleaned_string:
        #         cleaned_string = re.sub(r'\s+', ' ', cleaned_string)
        #         if not cleaned_string:
        #             raise HTTPException(status_code=400, detail="Invoice no can not accept only special character")
        #     else:
        #         raise HTTPException(status_code=400, detail="Invoice no can not accept only special character")
        elif not re.match(invoice_number_pattern, value):
            raise HTTPException(status_code=400, detail=f"Invalid invoice number format. Use only letters, numbers, spaces, and symbols: '-', '_', '/', '#'. Please check your input.")
        return value

    @field_validator('assetClassification')
    def validate_asset_classification(cls, value: str):
        if len(value) > 250:
            raise HTTPException(status_code=400, detail=f"assetClassification can not be greater than 250 {value}")
        return value

    @field_validator('dueAmt')
    def validate_due_amt(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="dueAmt can not be blank")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"dueAmt can not be greater than 20 digit {value}")
        return value

    @field_validator('dueDate')
    def validate_due_date(cls, value: date) -> date:
        if value == '':
            raise HTTPException(status_code=400, detail="dueDate can not be blank")
        elif len(str(value)) > 10:
            raise HTTPException(status_code=400, detail=f"dueDate can not be greater than 10 {value}")
        elif value != '':
            try:
                dd = datetime.strptime(value, "%d/%m/%Y")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"date format except d/m/Y format {value}")
        return value

    @field_validator('repaymentType')
    def validate_repayment_type(cls, value: str):
        if len(value) > 20:
            raise HTTPException(status_code=400, detail=f"repaymentType can not be greater than 20 {value}")
        return value

    @field_validator('repaymentAmt')
    def validate_repayment_amt(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="repaymentAmt can not be blank")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"repaymentAmt can not be greater than 20 digit {value}")
        return value

    @field_validator('repaymentDate')
    def validate_repayment_date(cls, value: date) -> date:
        if value == '':
            raise HTTPException(status_code=400, detail="repaymentDate can not be blank")
        elif len(str(value)) > 10:
            raise HTTPException(status_code=400, detail=f"repaymentDate can not be greater than 10 {value}")
        elif value != '':
            try:
                dd = datetime.strptime(value, "%d/%m/%Y")
            except Exception as e:
                raise HTTPException(status_code=400, detail="date format accept d/m/Y format")
        return value

    @field_validator('repaymentFlag')
    def validate_repayment_flag(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="repaymentFlag can not be blank")
        elif len(value) > 20:
            raise HTTPException(status_code=400, detail=f"repaymentFlag can not be greater than 20 {value}")
        else:
            if not value.lower() in ('full', 'partial'):
                raise HTTPException(status_code=400, detail=f"repayment flag can be full or partial {value}")
        return value

    @field_validator('pendingDueAmt')
    def validate_pending_due_amount(cls, value: int):
        if value == '':
            raise HTTPException(status_code=400, detail="pendingDueAmt can not be blank")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"pendingDueAmt can not be greater than 20 digit {value}")
        return value

    @field_validator('dpd')
    def validate_dpd(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="dpd can not be blank")
        elif len(str(value)) > 10:
            raise HTTPException(status_code=400, detail=f"dpd can not be greater than 10 {value}")
        return value

    @field_validator('invoiceDate')
    def validate_invoice_date(cls, value: date) -> date:
        if value == '':
            raise HTTPException(status_code=400, detail="InvoiceDate can not be blank")
        elif len(str(value)) > 10:
            raise HTTPException(status_code=400, detail=f"InvoiceDate can not be greater than 10 {value}")
        elif value != '':
            try:
                dd = datetime.strptime(value, "%d/%m/%Y")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"date format except d/m/Y format {value}")
        return value

    @field_validator('invoiceAmt')
    def validate_invoice_amount(cls, value: int):
        if value == '':
            raise HTTPException(status_code=400, detail="invoiceAmt can not be blank")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"invoiceAmt can not be greater than 20 digit {value}")
        return value


class AsyncRepaymentSchema(BaseSchema):
    ledgerNo: str
    borrowerCategory: str
    ledgerData: List[AsyncRepaymentInvoiceData] = Field(...)

    @model_validator(mode='after')
    def validate_field(self):
        if not special_char_pattern.match(self.requestId):
            raise HTTPException(status_code=400, detail=f"request id can not accept special character {self.requestId}")
        if not special_char_pattern.match(str(self.ledgerNo)):
            raise HTTPException(status_code=400, detail=f"ledgerNo can not accept special character {self.ledgerNo}")
        if not special_char_pattern.match(str(self.borrowerCategory)):
            raise HTTPException(status_code=400, detail=f"borrowerCategory can not accept special character {self.borrowerCategory}")
        if not date_special_char_pattern.match(str(self.signature)):
            raise HTTPException(status_code=400, detail=f"signature can not accept special character {self.signature}")
        return self

    @field_validator('ledgerNo')
    def validate_ledger_no(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="ledgerNo can not be blank")
        elif len(value) > 100:
            raise HTTPException(status_code=400, detail=f"ledgerNo can not be greater than 100 {value}")
        elif value != "":
            cleaned_string = value.isnumeric()
            if not cleaned_string:
                raise HTTPException(status_code=400, detail=f"ledger no can have only numeric value {value}")
        return value

    @field_validator('borrowerCategory')
    def validate_borrower_category(cls, value: str):
        if len(value) > 50:
            raise HTTPException(status_code=400, detail=f"borrowerCategory can not be greater than 50 {value}")
        return value


class CheckInvoiceStatusSchemaWithCode(BaseSchema):
    validationType: str
    validationRefNo: str
    invoiceNo: str = Field()
    invoiceDate: str = Field(default='01/06/1989')
    invoiceAmt: str = Field()
    sellerCode: str = Field()
    buyerCode: str = Field()
    sellerGst: str = Field()
    buyerGst: str = Field()

    @model_validator(mode='after')
    def validate_field(self):
        if not self.requestId:
            raise HTTPException(status_code=400, detail="request id can not be blank")
        elif not special_char_pattern.match(self.requestId):
            raise HTTPException(status_code=400, detail=f"request id can not accept special character {self.requestId}")
        elif len(self.requestId) >= 30:
            raise HTTPException(status_code=400, detail=f"request id can not be greater than 30 {self.requestId}")
        elif not self.signature:
            raise HTTPException(status_code=400, detail="signature can not be blank")
        elif not special_char_pattern.match(self.signature):
            raise HTTPException(status_code=400, detail=f"signature can not accept special character {self.signature}")
        elif len(self.signature) > 500:
            raise HTTPException(status_code=400, detail=f"signature can not be greater than 500 {self.signature}")
        elif not self.invoiceNo:
            raise HTTPException(status_code=400, detail="Invoice no can not be blank")
        elif len(self.invoiceNo) > 100:
            raise HTTPException(status_code=400, detail=f"Invoice no can not be greater than 100 {self.invoiceNo}")
        elif not self.invoiceDate:
            raise HTTPException(status_code=400, detail="Invoice date can not be blank")
        elif len(self.invoiceDate) > 10:
            raise HTTPException(status_code=400, detail=f"Invoice date can not be greater than 10 {self.invoiceDate}")
        elif not self.invoiceAmt:
            raise HTTPException(status_code=400, detail="Invoice amount can not be blank")
        elif len(str(self.invoiceAmt)) > 20:
            raise HTTPException(status_code=400, detail=f"Invoice amount can not be greater than 20 {self.invoiceAmt}")
        elif not self.sellerCode:
            raise HTTPException(status_code=400, detail="Seller code can not be blank")
        elif not special_char_pattern.match(self.sellerCode):
            raise HTTPException(status_code=400, detail=f"Seller Code can not accept special character {self.sellerCode}")
        elif len(self.sellerCode) > 20:
            raise HTTPException(status_code=400, detail=f"Seller code can not greater than 20 {self.sellerCode}")
        elif not special_char_pattern.match(self.sellerGst):
            raise HTTPException(status_code=400, detail=f"Seller gst can not accept special character {self.sellerGst}")
        elif len(self.sellerGst) > 20:
            raise HTTPException(status_code=400, detail=f"Seller gst can not greater than 20 {self.sellerGst}")
        elif not self.buyerCode:
            raise HTTPException(status_code=400, detail="Buyer code can not be blank")
        elif not special_char_pattern.match(self.buyerCode):
            raise HTTPException(status_code=400, detail=f"Buyer Code can not accept special character {self.buyerCode}")
        elif len(self.buyerCode) > 20:
            raise HTTPException(status_code=400, detail=f"Buyer code can not greater than 20 {self.buyerCode}")
        elif not special_char_pattern.match(self.buyerGst):
            raise HTTPException(status_code=400, detail=f"Buyer gst can not accept special character {self.buyerGst}")
        elif len(self.buyerGst) > 20:
            raise HTTPException(status_code=400, detail=f"Buyer gst can not greater than 20 {self.buyerGst}")
        elif not bool(re.match(amt_regex_pattern, self.invoiceAmt)):
            raise HTTPException(status_code=400, detail=f"Invalid invoice amount {self.invoiceAmt}")
        if '.' in self.invoiceAmt:
            amount_list = self.invoiceAmt.split('.')
            if len(amount_list) > 2:
                raise HTTPException(status_code=400, detail=f"Invalid invoice amount {self.invoiceAmt}")
            elif len(amount_list[1]) > 2:
                raise HTTPException(status_code=400, detail=f"Invoice amount can not accept more than two digit value {self.invoiceAmt}")
        if str(self.validationType) == '' and str(self.validationRefNo) != '':
            raise HTTPException(status_code=400, detail="validationType should not be blank")
        if str(self.validationRefNo) != '':
            validate_string = re.search(validation_ref_no_pattern, str(self.validationRefNo))
            if not validate_string:
                raise HTTPException(status_code=400, detail=f"validation Ref No can not accept special character {self.validationRefNo}")
        if str(self.validationRefNo) == '' and str(self.validationType) != '':
            raise HTTPException(status_code=400, detail="validationRefNo should not be blank")
        return self

    @field_validator('invoiceNo')
    def validate_invoice_no(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="Invoice no can not be blank")
        # elif value != "":
        #     cleaned_string = re.sub(r'[^a-zA-Z0-9\s]', '', value)
        #     if cleaned_string:
        #         cleaned_string = re.sub(r'\s+', ' ', cleaned_string)
        #         if not cleaned_string:
        #             raise HTTPException(status_code=400, detail="Invoice no can not accept only special character")
        #     else:
        #         raise HTTPException(status_code=400, detail="Invoice no can not accept only special character")
        elif not re.match(invoice_number_pattern, value):
            raise HTTPException(status_code=400, detail=f"Invalid invoice number format. Use only letters, numbers, spaces, and symbols: '-', '_', '/', '#'. Please check your input.")
        return value

    @field_validator('invoiceDate')
    def validate_invoice_date(cls, value: date) -> date:
        from datetime import datetime
        try:
            datetime.strptime(value, "%d/%m/%Y")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"date format except d/m/Y format {value}")
        return value

    @field_validator('validationType')
    def validate_validation_type(cls, value: str):
        # if value == '':
        #     raise HTTPException(status_code=400, detail="validationType can not be blank")
        if value != '':
            if not value.lower() in ('einvoice', 'ewaybill', 'gstfiling'):
                raise HTTPException(status_code=400, detail=f"validationType can be eInvoice, eWayBill or gstFiling {value}")
        return value


class CheckInvoiceStatusSchemaWithoutCode(BaseSchema):
    validationType: str
    validationRefNo: str
    invoiceNo: str = Field()
    invoiceDate: str = Field(default='01/06/1989')
    invoiceAmt: str = Field()
    sellerGst: str = Field()
    buyerGst: str = Field()
    sellerIdentifierData: List[SellerData] = Field(...)
    buyerIdentifierData: List[BuyerData] = Field(...)

    @model_validator(mode='after')
    def validate_field(self):
        import utils
        if not self.requestId:
            raise HTTPException(status_code=400, detail="request id can not be blank")
        elif not special_char_pattern.match(self.requestId):
            raise HTTPException(status_code=400, detail=f"Request id can not accept special character {self.requestId}")
        elif len(self.requestId) >= 30:
            raise HTTPException(status_code=400, detail=f"Request id can not be greater than 30 {self.requestId}")
        elif not self.signature:
            raise HTTPException(status_code=400, detail="Signature can not be blank")
        elif not special_char_pattern.match(self.signature):
            raise HTTPException(status_code=400, detail=f"Signature can not accept special character {self.signature}")
        elif len(self.signature) > 500:
            raise HTTPException(status_code=400, detail=f"signature can not be greater than 500 {self.signature}")
        elif not self.invoiceNo:
            raise HTTPException(status_code=400, detail="Invoice no can not be blank")
        elif len(self.invoiceNo) > 100:
            raise HTTPException(status_code=400, detail=f"Invoice can not be greater than 100 {self.invoiceNo}")
        elif not self.invoiceDate:
            raise HTTPException(status_code=400, detail="Invoice date can not be blank")
        elif len(self.invoiceDate) > 10:
            raise HTTPException(status_code=400, detail=f"Invoice date can not be greater than 10 {self.invoiceDate}")
        elif len(str(self.invoiceAmt)) > 20:
            raise HTTPException(status_code=400, detail=f"Invoice amount can not be greater than 20 {self.invoiceAmt}")
        elif not special_char_pattern.match(self.sellerGst):
            raise HTTPException(status_code=400, detail=f"Seller gst can not accept special character {self.sellerGst}")
        elif len(self.sellerGst) > 20:
            raise HTTPException(status_code=400, detail=f"Seller gst can not greater than 20 {self.sellerGst}")
        elif not special_char_pattern.match(self.buyerGst):
            raise HTTPException(status_code=400, detail=f"Buyer gst can not accept special character {self.buyerGst}")
        elif len(self.buyerGst) > 20:
            raise HTTPException(status_code=400, detail=f"Buyer gst can not greater than 20 {self.requestId}")
        elif not bool(re.match(amt_regex_pattern, self.invoiceAmt)):
            raise HTTPException(status_code=400, detail=f"Invalid invoice amount {self.invoiceAmt}")
        if '.' in self.invoiceAmt:
            amount_list = self.invoiceAmt.split('.')
            if len(amount_list) > 2:
                raise HTTPException(status_code=400, detail=f"Invalid invoice amount {self.invoiceAmt}")
            elif len(amount_list[1]) > 2:
                raise HTTPException(status_code=400, detail=f"Invoice amount can not accept more than two digit value {self.invoiceAmt}")
        if str(self.validationType) == '' and str(self.validationRefNo) != '':
            raise HTTPException(status_code=400, detail="validationType should not be blank")
        if str(self.validationRefNo) != '':
            validate_string = re.search(validation_ref_no_pattern, str(self.validationRefNo))
            if not validate_string:
                raise HTTPException(status_code=400, detail=f"validation Ref No can not accept special character {self.validationRefNo}")
        if str(self.validationRefNo) == '' and str(self.validationType) != '':
            raise HTTPException(status_code=400, detail="validationRefNo should not be blank")
        # duplicate identifier check
        json_request_data = jsonable_encoder(self)
        duplicate_identifier_values = utils.check_for_duplicate_values(json_request_data)
        duplicate_pan_value = utils.check_for_duplicate_pan_values(json_request_data)
        duplicate_lei_value = utils.check_for_duplicate_lei_values(json_request_data)
        duplicate_cin_value = utils.check_for_duplicate_cin_values(json_request_data)
        duplicate_tax_no_value = utils.check_for_duplicate_tax_no_values(json_request_data)
        if duplicate_identifier_values or duplicate_pan_value or duplicate_lei_value or duplicate_cin_value or duplicate_tax_no_value:
            raise HTTPException(status_code=400, detail="sellerIdNo and buyerIdNo cannot be same. ")
        return self

    @field_validator('invoiceNo')
    def validate_invoice_no(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="Invoice no can not be blank")
        elif not re.match(invoice_number_pattern, value):
            raise HTTPException(status_code=400, detail=f"Invalid invoice number format. Use only letters, numbers, spaces, and symbols: '-', '_', '/', '#'. Please check your input.")
        return value

    @field_validator('invoiceDate')
    def validate_invoice_date(cls, value: date) -> date:
        from datetime import datetime
        try:
            datetime.strptime(value, "%d/%m/%Y")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"date format except d/m/Y format {value}")
        return value

    @field_validator('validationType')
    def validate_validation_type(cls, value: str):

        if value != '':
            if not value.lower() in ('einvoice', 'ewaybill', 'gstfiling'):
                raise HTTPException(status_code=400, detail=f"validationType can be eInvoice, eWayBill or gstFiling {value}")
        return value


class AsyncValidationServiceWithCodeSchema(BaseSchema):
    sellerCode: str
    buyerCode: str
    sellerGst: str
    buyerGst: str
    ledgerData: List[AsyncInvoiceSchema] = Field(...)

    @field_validator('sellerCode')
    def validate_seller_code(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="seller code can not be blank")
        elif len(value) > 20:
            raise HTTPException(status_code=400, detail="seller code can not be greater than 20")
        elif value != "":
            cleaned_string = re.sub(r'[^a-zA-Z0-9\s]', '', value)
            validate_string = re.search(validate_value, value)
            if not validate_string:
                raise HTTPException(status_code=400, detail="seller code can not accept special character")
            if cleaned_string:
                cleaned_string = re.sub(r'\s+', ' ', cleaned_string)
                if not cleaned_string:
                    raise HTTPException(status_code=400, detail="seller code can not accept special character")
            else:
                raise HTTPException(status_code=400, detail="seller code can not accept special character")
        return value

    @field_validator('buyerCode')
    def validate_buyer_code(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="buyer code can not be blank")
        elif len(value) > 20:
            raise HTTPException(status_code=400, detail="buyer code can not be greater than 20")
        elif value != "":
            cleaned_string = re.sub(r'[^a-zA-Z0-9\s]', '', value)
            validate_string = re.search(validate_value, value)
            if not validate_string:
                raise HTTPException(status_code=400, detail="buyer code can not accept special character")
            if cleaned_string:
                cleaned_string = re.sub(r'\s+', ' ', cleaned_string)
                if not cleaned_string:
                    raise HTTPException(status_code=400, detail="buyer code can not accept special character")
            else:
                raise HTTPException(status_code=400, detail="buyer code can not accept special character")
        return value

    @field_validator('sellerGst')
    def seller_gst_validate(cls, value: str):
        seller_gst_value = ValidationCheck.validate_gst(value)
        if not seller_gst_value:
            raise HTTPException(status_code=400, detail="seller gst is not valid")
        return value

    @field_validator('sellerGst')
    def validate_seller_gst(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="seller gst can not be blank")
        elif len(value) > 20:
            raise HTTPException(status_code=400, detail="seller gst can not be greater than 20")
        elif value != "":
            cleaned_string = re.sub(r'[^a-zA-Z0-9\s]', '', value)
            validate_string = re.search(validate_value, value)
            if not validate_string:
                raise HTTPException(status_code=400, detail="seller gst can not accept special character")
            if cleaned_string:
                cleaned_string = re.sub(r'\s+', ' ', cleaned_string)
                if not cleaned_string:
                    raise HTTPException(status_code=400, detail="seller gst can not accept special character")
            else:
                raise HTTPException(status_code=400, detail="seller gst can not accept special character")
        return value

    @field_validator('buyerGst')
    def validate_buyer_gst(cls, value: str):
        buyer_gst_value = ValidationCheck.validate_gst(value)
        if not buyer_gst_value:
            raise HTTPException(status_code=400, detail="buyer gst is not valid")
        if value == '':
            raise HTTPException(status_code=400, detail="buyer gst can not be blank")
        elif len(value) > 20:
            raise HTTPException(status_code=400, detail="buyer gst can not be greater than 20")
        elif value != "":
            cleaned_string = re.sub(r'[^a-zA-Z0-9\s]', '', value)
            validate_string = re.search(validate_value, value)
            if not validate_string:
                raise HTTPException(status_code=400, detail="buyer gst can not accept special character")
            if cleaned_string:
                cleaned_string = re.sub(r'\s+', ' ', cleaned_string)
                if not cleaned_string:
                    raise HTTPException(status_code=400, detail="buyer gst can not accept special character")
            else:
                raise HTTPException(status_code=400, detail="buyer gst can not accept special character")
        return value

    @model_validator(mode='after')
    def validate_field(self):
        import utils
        json_request_data = jsonable_encoder(self)
        invoice_date_response = utils.check_invoice_date(json_request_data)
        invoice_due_date_response = utils.check_invoice_due_date(json_request_data)
        duplicates_json_exist = utils.are_duplicates_exist(json_request_data.get('ledgerData'))
        if not invoice_date_response:
            raise HTTPException(status_code=400, detail="Invoice date is greater then current date")
        if invoice_due_date_response:
            raise HTTPException(status_code=400, detail="Invoice due date should be greater than invoice date")
        if duplicates_json_exist:
            raise HTTPException(status_code=400, detail="Duplicate invoice data found")
        return self


class SellerDataValidate(BaseModel):
    sellerIdType: str
    sellerIdNo: str
    sellerIdName: str
    ifsc: str

    @model_validator(mode='after')
    def validate_field(self):
        if not self.sellerIdType:
            raise HTTPException(status_code=400, detail="Seller id type can not be blank")
        if len(self.sellerIdType) > 50:
            raise HTTPException(status_code=400, detail="Seller id type can not be greater than 50")
        if self.sellerIdType.lower() not in ['lei', 'gstin', 'pan', 'cin', 'tax_no', 'accountnumber']:
            raise HTTPException(status_code=400, detail="Invalid entity type")
        if not self.sellerIdName:
            raise HTTPException(status_code=400, detail="Seller id name can not be blank")
        if not special_char_pattern.match(self.sellerIdName):
            raise HTTPException(status_code=400, detail="Seller id name can not accept special character")
        if len(self.sellerIdName) > 50:
            raise HTTPException(status_code=400, detail="Seller id name can not be greater than 50")
        if self.sellerIdType.lower() == "accountnumber":
            if not self.sellerIdNo.isnumeric():
                raise HTTPException(status_code=400, detail="seller id no can have only numeric value")
            if self.ifsc == "":
                raise HTTPException(status_code=400, detail="IFSC can not be blank in seller data")
            elif not special_char_pattern.match(self.ifsc):
                raise HTTPException(status_code=400, detail="IFSC can not accept special character")
            elif len(self.ifsc) > 16:
                raise HTTPException(status_code=400, detail="IFSC can not be greater than 16")
            elif self.sellerIdType.lower() != "accountnumber":
                raise HTTPException(status_code=400, detail="Entity id type should be 'Account Number' for ifsc in "
                                                            "seller data")
        else:
            if self.ifsc != "":
                raise HTTPException(status_code=400,
                                    detail="Entity id type should be 'Account Number' for ifsc in seller data")
        return self

    # all identifier validation check schema -['lei', 'gst', 'pan', 'cin', 'tax_no']
    @model_validator(mode='after')
    def identifier_field(self):
        if self.sellerIdType.lower() == "gstin":
            gst_value = ValidationCheck.validate_gst(self.sellerIdNo)
            if not gst_value:
                raise HTTPException(status_code=400, detail="seller gst is not valid")
        elif self.sellerIdType.lower() == 'lei':
            lei_value = ValidationCheck.validate_lei(self.sellerIdNo)
            if not lei_value:
                raise HTTPException(status_code=400, detail="seller lei is not valid")
        elif self.sellerIdType.lower() == 'pan':
            pan_value = ValidationCheck.validate_pan_card(self.sellerIdNo)
            if not pan_value:
                raise HTTPException(status_code=400, detail="seller pan number is not valid")
        elif self.sellerIdType.lower() == 'cin':
            cin_value = ValidationCheck.validate_cin(self.sellerIdNo)
            if not cin_value:
                raise HTTPException(status_code=400, detail="seller cin is not valid")
        elif self.sellerIdType.lower() == 'tax_no':
            pt_value = ValidationCheck.validate_pt(self.sellerIdNo)
            if not pt_value:
                raise HTTPException(status_code=400, detail="seller tax no is not valid")
        return self

    @field_validator('sellerIdNo')
    def validate_seller_id_no(cls, value: str):
        if value == "":
            raise HTTPException(status_code=400, detail="Seller id no can not be left blank")
        elif len(value) > 50:
            raise HTTPException(status_code=400, detail="Seller id no can not be greater than 50")
        elif value != "":
            cleaned_string = re.sub(r'[^a-zA-Z0-9\s]', '', value)
            if cleaned_string:
                cleaned_string = re.sub(r'\s+', ' ', cleaned_string)
                if not cleaned_string:
                    raise HTTPException(status_code=400, detail="Seller id no can not accept special character")
            else:
                raise HTTPException(status_code=400, detail="Seller id no can not accept special character")
        return value


class BuyerDataValidate(BaseModel):
    buyerIdType: str
    buyerIdNo: str
    buyerIdName: str
    ifsc: str

    @model_validator(mode='after')
    def validate_field(self):
        if not self.buyerIdType:
            raise HTTPException(status_code=400, detail="Buyer id type can not be blank")
        if len(self.buyerIdType) > 50:
            raise HTTPException(status_code=400, detail="Buyer id type can not be greater than 50")
        if self.buyerIdType.lower() not in ['lei', 'gstin', 'pan', 'cin', 'tax_no', 'accountnumber']:
            raise HTTPException(status_code=400, detail="Invalid entity type")
        if not self.buyerIdName:
            raise HTTPException(status_code=400, detail="Buyer id name can not be blank")
        if not special_char_pattern.match(self.buyerIdName):
            raise HTTPException(status_code=400, detail="Buyer id name can not accept special character")
        if len(self.buyerIdName) > 50:
            raise HTTPException(status_code=400, detail="Buyer id name can not be greater than 50")
        if self.buyerIdType.lower() == "accountnumber":
            if not self.buyerIdNo.isnumeric():
                raise HTTPException(status_code=400, detail="Buyer id no can have only numeric value")
            if self.ifsc == "":
                raise HTTPException(status_code=400, detail="IFSC can not be blank in buyer data")
            elif not special_char_pattern.match(self.ifsc):
                raise HTTPException(status_code=400, detail="IFSC can not accept special character")
            elif len(self.ifsc) > 16:
                raise HTTPException(status_code=400, detail="IFSC can not be greater than 16")
            elif self.buyerIdType.lower() != "accountnumber":
                raise HTTPException(status_code=400, detail="Entity id type should be 'Account Number' for ifsc in "
                                                            "buyer data")
        else:
            if self.ifsc != "":
                raise HTTPException(status_code=400, detail="Entity id type should be 'Account Number' for ifsc in buyer data")
        return self

    # all identifier validation check schema -['lei', 'gst', 'pan', 'cin', 'tax_no']
    @model_validator(mode='after')
    def identifier_field(self):
        if self.buyerIdType.lower() == "gstin":
            gst_value = ValidationCheck.validate_gst(self.buyerIdNo)
            if not gst_value:
                raise HTTPException(status_code=400, detail="buyer gst is not valid")
        elif self.buyerIdType.lower() == 'lei':
            lei_value = ValidationCheck.validate_lei(self.buyerIdNo)
            if not lei_value:
                raise HTTPException(status_code=400, detail="buyer lei is not valid")
        elif self.buyerIdType.lower() == 'pan':
            pan_value = ValidationCheck.validate_pan_card(self.buyerIdNo)
            if not pan_value:
                raise HTTPException(status_code=400, detail="buyer pan number is not valid")
        elif self.buyerIdType.lower() == 'cin':
            cin_value = ValidationCheck.validate_cin(self.buyerIdNo)
            if not cin_value:
                raise HTTPException(status_code=400, detail="buyer cin is not valid")
        elif self.buyerIdType.lower() == 'tax_no':
            pt_value = ValidationCheck.validate_pt(self.buyerIdNo)
            if not pt_value:
                raise HTTPException(status_code=400, detail="buyer tax no is not valid")
        return self

    @field_validator('buyerIdNo')
    def validate_buyer_id_no(cls, value: str):
        if value == "":
            raise HTTPException(status_code=400, detail="Buyer id no can not be left blank")
        elif len(value) > 50:
            raise HTTPException(status_code=400, detail="Buyer id no can not be greater than 50")
        elif value != "":
            cleaned_string = re.sub(r'[^a-zA-Z0-9\s]', '', value)
            if cleaned_string:
                cleaned_string = re.sub(r'\s+', ' ', cleaned_string)
                if not cleaned_string:
                    raise HTTPException(status_code=400, detail="Buyer id no can not accept special character")
            else:
                raise HTTPException(status_code=400, detail="Buyer id no can not accept special character")

        return value


# InvoiceRequestSchema
class AsyncValidationServiceWithoutCodeSchema(BaseSchema):

    sellerGst: str
    buyerGst: str
    ledgerData: List[InvoiceSchema] = Field(...)
    sellerIdentifierData: List[SellerDataValidate] = Field(...)
    buyerIdentifierData: List[BuyerDataValidate] = Field(...)

    @field_validator('sellerGst')
    def seller_gst_validate(cls, value: str):
        seller_gst_value = ValidationCheck.validate_gst(value)
        if not seller_gst_value:
            raise HTTPException(status_code=400, detail="seller gst is not valid")
        return value

    @field_validator('sellerGst')
    def validate_seller_gst(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="seller gst can not be blank")
        elif len(value) > 20:
            raise HTTPException(status_code=400, detail="seller gst can not greater than 20")
        elif value != "":
            cleaned_string = re.sub(r'[^a-zA-Z0-9\s]', '', value)
            validate_string = re.search(validate_value, value)
            if not validate_string:
                raise HTTPException(status_code=400, detail="seller gst can not accept special character")
            if cleaned_string:
                cleaned_string = re.sub(r'\s+', ' ', cleaned_string)
                if not cleaned_string:
                    raise HTTPException(status_code=400, detail="seller gst can not accept special character")
            else:
                raise HTTPException(status_code=400, detail="seller gst can not accept special character")
        return value

    @field_validator('buyerGst')
    def validate_buyer_gst(cls, value: str):
        buyer_gst_value = ValidationCheck.validate_gst(value)
        if not buyer_gst_value:
            raise HTTPException(status_code=400, detail="buyer gst is not valid")
        if value == '':
            raise HTTPException(status_code=400, detail="buyer gst can not be blank")
        elif len(value) > 20:
            raise HTTPException(status_code=400, detail="buyer gst can not greater than 20")
        elif value != "":
            cleaned_string = re.sub(r'[^a-zA-Z0-9\s]', '', value)
            validate_string = re.search(validate_value, value)
            if not validate_string:
                raise HTTPException(status_code=400, detail="buyer gst can not accept special character")
            if cleaned_string:
                cleaned_string = re.sub(r'\s+', ' ', cleaned_string)
                if not cleaned_string:
                    raise HTTPException(status_code=400, detail="buyer gst can not accept special character")
            else:
                raise HTTPException(status_code=400, detail="buyer gst can not accept special character")
        return value

    @model_validator(mode='after')
    def validate_field(self):
        import utils
        json_request_data = jsonable_encoder(self)
        invoice_date_response = utils.check_invoice_date(json_request_data)
        invoice_due_date_response = utils.check_invoice_due_date(json_request_data)
        duplicates_json_exist = utils.are_duplicates_exist(json_request_data.get('ledgerData'))
        if not invoice_date_response:
            raise HTTPException(status_code=400, detail="Invoice date is greater then current date")
        if invoice_due_date_response:
            raise HTTPException(status_code=400, detail="Invoice due date should be greater than invoice date")
        if duplicates_json_exist:
            raise HTTPException(status_code=400, detail="Duplicate invoice data found")
        return self


class CheckWebhookHistorySchema(BaseModel):
    requestId: str
    fromDate: str = Field(default='01/06/1989')
    toDate: str = Field(default='01/07/1989')

    @model_validator(mode='after')
    def validate_field(self):
        import utils
        if not self.requestId:
            raise HTTPException(status_code=400, detail="request id can not be blank")
        elif not special_char_pattern.match(self.requestId):
            raise HTTPException(status_code=400, detail="Request id can not accept special character")
        elif len(self.requestId) >= 30:
            raise HTTPException(status_code=400, detail="Request id can not be greater than 30")
        elif not self.fromDate:
            raise HTTPException(status_code=400, detail="From date can not be blank")
        elif not self.toDate:
            raise HTTPException(status_code=400, detail="To date can not be blank")

    @field_validator('fromDate')
    def validate_from_dates(cls, value: date) -> date:
        from datetime import datetime
        try:
            dd = datetime.strptime(value, "%d/%m/%Y")
        except Exception as e:
            raise HTTPException(status_code=400, detail="date format except d/m/Y format")
        return value

    @field_validator('toDate')
    def validate_to_dates(cls, value: date) -> date:
        from datetime import datetime
        try:
            dd = datetime.strptime(value, "%d/%m/%Y")
        except Exception as e:
            raise HTTPException(status_code=400, detail="date format except d/m/Y format")
        return value


class HubSchema(BaseModel):
    encryptData : str
    txnCode: str
    correlationId: str
    signature: str

    # @model_validator(mode='after')
    # def validate_field(self):
    #     import utils
    #     if not self.encryptedData:
    #         raise HTTPException(status_code=400, detail="request id can not be blank")

    @field_validator('encryptData')
    def validate_encrypt_data(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="encryptData can not be blank")
        return value

    @field_validator('txnCode')
    def validate_txn_code(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="txnCode can not be blank")
        return value

    @field_validator('correlationId')
    def validate_correlation_id(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="correlationId can not be blank")
        return value

    @field_validator('signature')
    def validate_signature(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="signature can not be blank")
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail="signature can not accept special character")
        elif len(value) > 500:
            raise HTTPException(status_code=400, detail="signature can not be greater than 500")
        return value


class InvoiceRequestGroupSchema(BaseModel):
    sellerGst: str
    buyerGst: str
    groupingId: str
    ledgerData: List[BulkInvoiceSchema] = Field(...)
    sellerIdentifierData: Optional[List[SellerData]] = Field(None)
    buyerIdentifierData: Optional[List[BuyerData]] = Field(None)

    @field_validator('groupingId')
    def validate_grouping_id(cls, value: str):
        if not value:
            raise HTTPException(status_code=400, detail="grouping id can not blank")
        if not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"grouping id can not accept special character {value}")
        if len(value) > 30:
            raise HTTPException(status_code=400, detail=f"grouping id can not be greater than 30 {value}")
        return value

    @field_validator('sellerGst')
    def validate_seller_gst(cls, value: str):
        if value == '':
            pass
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"seller gst can not accept special character {value}")
        elif len(value) > 20:
            raise HTTPException(status_code=400, detail=f"seller gst can not greater than 20 {value}")
        elif value != "":
            seller_gst_value = ValidationCheck.validate_gst(value)
            if not seller_gst_value:
                raise HTTPException(status_code=400, detail=f"seller gst is not valid {value}")
        return value

    @field_validator('buyerGst')
    def validate_buyer_gst(cls, value: str):
        if value == '':
            pass
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"buyer gst can not accept special character {value}")
        elif len(value) > 20:
            raise HTTPException(status_code=400, detail=f"buyer gst can not greater than 20 {value}")
        elif value != "":
            buyer_gst_value = ValidationCheck.validate_gst(value)
            if not buyer_gst_value:
                raise HTTPException(status_code=400, detail=f"buyer gst is not valid {value}")
        return value

    @model_validator(mode='after')
    def validate_field(self):
        import utils
        json_request_data = jsonable_encoder(self)
        validate_seller_identifier = utils.validate_seller_identifier(json_request_data)
        validate_buyer_identifier = utils.validate_buyer_identifier(json_request_data)
        invoice_date_response = utils.check_invoice_date(json_request_data)
        invoice_due_date_response = utils.check_invoice_due_date(json_request_data)
        duplicates_json_exist = utils.are_duplicates_exist(json_request_data.get('ledgerData'))
        duplicate_identifier_values = utils.check_for_duplicate_values(json_request_data)
        duplicate_pan_value = utils.check_for_duplicate_pan_values(json_request_data)
        duplicate_lei_value = utils.check_for_duplicate_lei_values(json_request_data)
        duplicate_cin_value = utils.check_for_duplicate_cin_values(json_request_data)
        duplicate_tax_no_value = utils.check_for_duplicate_tax_no_values(json_request_data)
        if not validate_seller_identifier:
            raise HTTPException(status_code=400,
                                detail="Seller identifier data can not be blank if seller gst is blank")
        if not validate_buyer_identifier:
            raise HTTPException(status_code=400, detail="Buyer identifier data can not be blank if buyer gst is blank")
        if not invoice_date_response:
            raise HTTPException(status_code=400, detail="Invoice date is greater then current date")
        if invoice_due_date_response:
            raise HTTPException(status_code=400, detail="Invoice due date should be greater than invoice date")
        if duplicates_json_exist:
            raise HTTPException(status_code=400, detail="Duplicate invoice data found")
        if duplicate_identifier_values:
            raise HTTPException(status_code=400, detail="sellerIdNo and buyerIdNo cannot be same.")
        if duplicate_pan_value:
            raise HTTPException(status_code=400, detail="sellerIdNo and buyerIdNo cannot be same.")
        if duplicate_lei_value:
            raise HTTPException(status_code=400, detail="sellerIdNo and buyerIdNo cannot be same.")
        if duplicate_cin_value:
            raise HTTPException(status_code=400, detail="sellerIdNo and buyerIdNo cannot be same.")
        if duplicate_tax_no_value:
            raise HTTPException(status_code=400, detail="sellerIdNo and buyerIdNo cannot be same.")
        return self


class InvoiceBulkRequestSchema(BaseSchema):
    groupData: List[InvoiceRequestGroupSchema] = Field(...)


class BulkAsyncFinanceInvoiceData(BaseModel):
    validationType: str
    validationRefNo: str
    invoiceNo: str
    financeRequestAmt: str
    financeRequestDate: str = Field(default='01/06/1989')
    dueDate: str
    fundingAmtFlag: str
    adjustmentType: str
    adjustmentAmt: str
    invoiceDate: str
    invoiceAmt: str

    @model_validator(mode='after')
    def validate_field(self):
        if not date_special_char_pattern.match(str(self.financeRequestDate)):
            raise HTTPException(status_code=400, detail=f"financeRequestDate can not accept special character {self.financeRequestDate}")
        if not date_special_char_pattern.match(str(self.dueDate)):
            raise HTTPException(status_code=400, detail=f"dueDate can not accept special character {self.dueDate}")
        if not special_char_pattern.match(self.fundingAmtFlag):
            raise HTTPException(status_code=400, detail=f"fundingAmtFlag can not accept special character {self.fundingAmtFlag}")
        if not special_char_pattern.match(str(self.adjustmentType)):
            raise HTTPException(status_code=400, detail=f"adjustmentType can not accept special character {self.adjustmentType}")
        if not date_special_char_pattern.match(str(self.invoiceDate)):
            raise HTTPException(status_code=400, detail=f"invoiceDate can not accept special character {self.invoiceDate}")
        if str(self.validationType) == '' and str(self.validationRefNo) != '':
            raise HTTPException(status_code=400, detail="validationType should not be blank")
        if str(self.validationRefNo) != '':
            validate_string = re.search(validation_ref_no_pattern, str(self.validationRefNo))
            if not validate_string:
                raise HTTPException(status_code=400, detail=f"validation Ref No can not accept special character {self.validationRefNo}")
        if str(self.validationRefNo) == '' and str(self.validationType) != '':
            raise HTTPException(status_code=400, detail="validationRefNo should not be blank")

        check_decimal_precision('adjustmentAmt', str(self.adjustmentAmt))
        check_decimal_precision('financeRequestAmt', str(self.financeRequestAmt))
        check_decimal_precision('invoiceAmt', str(self.invoiceAmt))
        return self

    @field_validator('validationType')
    def validate_validation_type(cls, value: str):
        # if value == '':
        #     raise HTTPException(status_code=400, detail="validationType can not be blank")
        if value != '':
            if not value.lower() in ('einvoice', 'ewaybill', 'gstfiling'):
                raise HTTPException(status_code=400, detail=f"validationType can be eInvoice, eWayBill or gstFiling {value}")
        return value

    # @field_validator('validationRefNo')
    # def validate_validation_ref_no(cls, value: str):
    #     # if value == '':
    #     #     raise HTTPException(status_code=400, detail="validationRefNo can not be blank")
    #     if value == '':
    #         if len(value) > 100:
    #             raise HTTPException(status_code=400, detail="validationRefNo can not be greater than 100")
    #     return value

    @field_validator('invoiceNo')
    def validate_invoice_no(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="Invoice no can not be blank")
        elif len(value) > 100:
            raise HTTPException(status_code=400, detail=f"Invoice no can not be greater than 100 {value}")
        elif not re.match(invoice_number_pattern, value):
            raise HTTPException(status_code=400, detail=f"Invalid invoice number format. Use only letters, numbers, spaces, and symbols: '-', '_', '/', '#'. Please check your input.")
        return value

    @field_validator('financeRequestAmt')
    def validate_finance_request_amount(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="financeRequestAmt can not be blank")
        if value == '0':
            raise HTTPException(status_code=400, detail=f"financeRequestAmt should be greater than 0 {value}")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"financeRequestAmt can not be greater than 20 {value}")
        return value

    @field_validator('financeRequestDate')
    def validate_finance_request_date(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="financeRequest Date can not be blank")
        elif len(value) > 10:
            raise HTTPException(status_code=400, detail=f"financeRequest Date can not be greater than 10 {value}")
        return value

    @field_validator('financeRequestDate')
    def validate_finance_request_dates(cls, value: date) -> date:
        from datetime import datetime
        try:
            dd = datetime.strptime(value, "%d/%m/%Y")
        except Exception as e:
            raise HTTPException(status_code=400, detail="date format accept d/m/Y format")
        return value

    @field_validator('dueDate')
    def validate_due_date(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="dueDate can not be blank")
        elif len(value) > 10:
            raise HTTPException(status_code=400, detail=f"due Date can not be greater than 10 {value}")
        return value

    @field_validator('dueDate')
    def validate_due_dates(cls, value: date) -> date:
        from datetime import datetime
        try:
            dd = datetime.strptime(value, "%d/%m/%Y")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"date format except d/m/Y format {value}")
            # raise ValueError("date formate except d/m/Y formate")
        return value

    @field_validator('fundingAmtFlag')
    def validate_funding_amt_flag(cls, value: str):
        # if value == '':
        #     raise HTTPException(status_code=400, detail="fundingAmtFlag can not be blank")
        if len(value) > 20:
            raise HTTPException(status_code=400, detail=f"funding amt flag can not be greater than 20 {value}")
        elif value != '':
            if not value.lower() in ('full', 'partial'):
                raise HTTPException(status_code=400, detail=f"Funding amt flag can be full or partial {value}")
        return value

    @field_validator('adjustmentType')
    def validate_adjustment_type(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="adjustmentType can not be blank")
        elif len(value) > 30:
            raise HTTPException(status_code=400, detail=f"adjustmentType can not be greater than 30 {value}")
        else:
            if not value.lower() in ('none', 'advance', 'creditnote'):
                raise HTTPException(status_code=400, detail=f"adjustmentType can be none, advance or creditnote {value}")
        return value

    @field_validator('adjustmentAmt')
    def validate_adjustment_amt(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="adjustmentAmt can not be blank")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"adjustmentAmt can not be greater than 20 {value}")
        return value

    @field_validator('invoiceDate')
    def validate_invoice_date(cls, value: date) -> date:
        if value == '':
            raise HTTPException(status_code=400, detail="Invoice date can not be blank")
        elif len(str(value)) > 10:
            raise HTTPException(status_code=400, detail=f"Invoice date can not be greater than 10 {value}")
        elif value != '':
            from datetime import datetime
            try:
                dd = datetime.strptime(value, "%d/%m/%Y")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"date format except d/m/Y format {value}")
        return value

    @field_validator('invoiceAmt')
    def validate_invoice_amount(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="invoiceAmt can not be blank")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"invoiceAmt can not be greater than 20 digit {value}")
        return value


class BulkAsyncFinanceInvoiceGroupData(BaseModel):
    groupingId: str
    ledgerNo: str
    ledgerAmtFlag: str
    lenderCategory: str
    lenderName: str
    lenderCode: str
    borrowerCategory: str
    ledgerData: List[BulkAsyncFinanceInvoiceData] = Field(...)

    @model_validator(mode='after')
    def validate_field(self):
        if not self.groupingId:
            raise HTTPException(status_code=400, detail="grouping id can not blank")
        if not special_char_pattern.match(self.groupingId):
            raise HTTPException(status_code=400, detail=f"groupingId can not accept special character{self.groupingId}")
        if not special_char_pattern.match(str(self.ledgerNo)):
            raise HTTPException(status_code=400, detail=f"ledgerNo can not accept special character{self.ledgerNo}")
        if not special_char_pattern.match(str(self.ledgerAmtFlag)):
            raise HTTPException(status_code=400, detail=f"ledgerAmtFlag can not accept special character{self.ledgerAmtFlag}")
        if not special_char_pattern.match(self.lenderCategory):
            raise HTTPException(status_code=400, detail=f"lenderCategory can not accept special character{self.lenderCategory}")
        if not lender_name_pattern.match(self.lenderName):
            raise HTTPException(status_code=400, detail=f"lenderName can not accept special character{self.lenderName}")
        if not special_char_pattern.match(self.lenderCode):
            raise HTTPException(status_code=400, detail=f"lenderCode can not accept special character{self.lenderCode}")
        if not special_char_pattern.match(self.borrowerCategory):
            raise HTTPException(status_code=400, detail=f"borrowerCategory can not accept special character{self.borrowerCategory}")
        return self

    @field_validator('groupingId')
    def validate_grouping_id(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="groupingId can not be blank")
        elif len(value) > 50:
            raise HTTPException(status_code=400, detail=f"groupingId can not be greater than 50{value}")
        return value

    @field_validator('ledgerNo')
    def validate_ledger_no(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="ledgerNo can not be blank")
        elif len(value) > 100:
            raise HTTPException(status_code=400, detail=f"ledgerNo can not be greater than 100 {value}")
        elif value != "":
            # cleaned_string = re.sub(r'[^.-@!#$%^&*()<>?/\|}{~:a-zA-Z\b\s]', '', value)
            cleaned_string = value.isnumeric()
            if not cleaned_string:
                raise HTTPException(status_code=400, detail=f"ledger no can have only numeric value{value}")
        return value

    @field_validator('ledgerAmtFlag')
    def validate_ledger_amt_flag(cls, value: str):
        if value != '':
            if not value.lower() in ('full', 'partial'):
                raise HTTPException(status_code=400, detail=f"ledgerAmtFlag can be full or partial {value}")
        return value

    @field_validator('lenderCategory')
    def validate_lender_category(cls, value: str):
        # if value == '':
        #     raise HTTPException(status_code=400, detail="lenderCategory can not be blank")
        if value != '':
            if len(value) > 50:
                raise HTTPException(status_code=400, detail=f"lenderCategory can not be greater than 50 {value}")
        return value

    @field_validator('lenderName')
    def validate_lender_name(cls, value: str):
        if value != "":
            if len(value) > 64:
                raise HTTPException(status_code=400, detail=f"lenderName can not be greater than 64 char {value}")
            # cleaned_string = re.sub(r'[^.-@!#$%^&*()<>?/\|}{~:\s]', '', value) #[.-@!#$%^&*()<>?/\|}{~:\b\s]
            # cleaned_string = value.isalnum()
            # if not cleaned_string:
            #     raise HTTPException(status_code=400, detail="lender name can not have special character")
        return value

    @field_validator('lenderCode')
    def validate_lender_code(cls, value: str):
        if value != "":
            if len(value) > 20:
                raise HTTPException(status_code=400, detail=f"lenderCode can not be greater than 20 {value}")
        return value

    @field_validator('borrowerCategory')
    def validate_borrower_category(cls, value: str):
        if len(value) > 50:
            raise HTTPException(status_code=400, detail=f"borrowerCategory can not be greater than 50 {value}")
        return value


class BulkAsyncFinanceSchema(BaseSchema):
    groupData: List[BulkAsyncFinanceInvoiceGroupData] = Field(...)


class BulkAsyncDisburseLedgerData(BaseModel):
    validationType: str
    validationRefNo: str
    invoiceNo: str
    invoiceDate: str
    invoiceAmt: str
    dueDate: str
    disbursedFlag: str
    disbursedAmt: str
    disbursedDate: str
    dueAmt: str

    @model_validator(mode='after')
    def validate_field(self):
        if not special_char_pattern.match(str(self.disbursedFlag)):
            raise HTTPException(status_code=400, detail=f"disbursedFlag can not accept special character {self.disbursedFlag}")
        if not date_special_char_pattern.match(self.disbursedDate):
            raise HTTPException(status_code=400, detail=f"disbursedDate can not accept special character {self.disbursedDate}")
        if not date_special_char_pattern.match(self.dueDate):
            raise HTTPException(status_code=400, detail=f"dueDate can not accept special character {self.dueDate}")
        if not date_special_char_pattern.match(self.invoiceDate):
            raise HTTPException(status_code=400, detail=f"invoiceDate can not accept special character {self.invoiceDate}")
        if str(self.validationType) == '' and str(self.validationRefNo) != '':
            raise HTTPException(status_code=400, detail="validationType should not be blank")
        if str(self.validationRefNo) != '':
            validate_string = re.search(validation_ref_no_pattern, str(self.validationRefNo))
            if not validate_string:
                raise HTTPException(status_code=400, detail=f"validation Ref No can not accept special character {self.validationRefNo}")
        if str(self.validationRefNo) == '' and str(self.validationType) != '':
            raise HTTPException(status_code=400, detail="validationRefNo should not be blank")

        check_decimal_precision('disbursedAmt', str(self.disbursedAmt))
        check_decimal_precision('dueAmt', str(self.dueAmt))
        check_decimal_precision('invoiceAmt', str(self.invoiceAmt))
        return self

    @field_validator('validationType')
    def validate_validation_type(cls, value: str):
        # if value == '':
        #     raise HTTPException(status_code=400, detail="validationType can not be blank")
        if value != "":
            if not value.lower() in ('einvoice', 'ewaybill', 'gstfiling'):
                raise HTTPException(status_code=400, detail=f"validationType can be eInvoice, eWayBill or gstFiling {value}")
        return value

    # @field_validator('validationRefNo')
    # def validate_validation_ref_no(cls, value: str):
    #     # if value == '':
    #     #     raise HTTPException(status_code=400, detail="validationRefNo can not be blank")
    #     if value != "":
    #         if len(value) > 100:
    #             raise HTTPException(status_code=400, detail="validationRefNo can not be greater than 100")
    #     return value

    @field_validator('invoiceNo')
    def validate_invoice_no(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="InvoiceNo can not be blank")
        elif len(value) > 100:
            raise HTTPException(status_code=400, detail=f"InvoiceNo can not be greater than 100 {value}")
        # elif value != "":
        #     cleaned_string = re.sub(r'[^a-zA-Z0-9\s]', '', value)
        #     if cleaned_string:
        #         cleaned_string = re.sub(r'\s+', ' ', cleaned_string)
        #         if not cleaned_string:
        #             raise HTTPException(status_code=400, detail="Invoice no can not accept only special character")
        #     else:
        #         raise HTTPException(status_code=400, detail="Invoice no can not accept only special character")
        elif not re.match(invoice_number_pattern, value):
            raise HTTPException(status_code=400, detail=f"Invalid invoice number format. Use only letters, numbers, spaces, and symbols: '-', '_', '/', '#'. Please check your input.")
        return value

    @field_validator('disbursedFlag')
    def validate_disbursed_flag(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="disbursedFlag can not be blank")
        else:
            if not value.lower() in ('full', 'partial'):
                raise HTTPException(status_code=400, detail=f"disbursedFlag can be full or partial {value}")
        return value

    @field_validator('disbursedAmt')
    def validate_disbursed_amt(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="disbursedAmt can not be blank")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"disbursedAmt can not be greater than 20 digit {value}")
        return value

    @field_validator('disbursedDate')
    def validate_disbursed_date(cls, value: date) -> date:
        if value == '':
            raise HTTPException(status_code=400, detail="disbursed date can not be blank")
        elif len(str(value)) > 10:
            raise HTTPException(status_code=400, detail=f"disbursedDate can not be greater than 10 {value}")
        elif value != '':
            from datetime import datetime
            try:
                dd = datetime.strptime(value, "%d/%m/%Y")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"date format accept d/m/Y format {value}")
        return value

    @field_validator('dueAmt')
    def validate_due_amt(cls, value: int):
        if value == '':
            raise HTTPException(status_code=400, detail="dueAmt can not be blank")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"dueAmt can not be greater than 20 digit {value}")
        return value

    @field_validator('dueDate')
    def validate_due_date(cls, value: date) -> date:
        if value == '':
            raise HTTPException(status_code=400, detail="dueDate can not be blank")
        elif len(str(value)) > 10:
            raise HTTPException(status_code=400, detail=f"dueDate can not be greater than 10 {value}")
        elif value != '':
            from datetime import datetime
            try:
                dd = datetime.strptime(value, "%d/%m/%Y")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"date format except d/m/Y format {value}")
        return value

    @field_validator('invoiceDate')
    def validate_invoice_date(cls, value: date) -> date:
        if value == '':
            raise HTTPException(status_code=400, detail="invoiceDate can not be blank")
        elif len(str(value)) > 10:
            raise HTTPException(status_code=400, detail=f"invoiceDate can not be greater than 10 {value}")
        elif value != '':
            from datetime import datetime
            try:
                dd = datetime.strptime(value, "%d/%m/%Y")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"date format except d/m/Y format {value}")
        return value

    @field_validator('invoiceAmt')
    def validate_invoice_amount(cls, value: int):
        if value == '':
            raise HTTPException(status_code=400, detail="invoiceAmt can not be blank")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"invoiceAmt can not be greater than 20 digit {value}")
        return value


class AsyncDisbursementInvoiceGroupData(BaseModel):
    groupingId: str
    ledgerNo: str
    ledgerAmtFlag: str
    lenderCategory: str
    lenderName: str
    lenderCode: str
    ledgerData: List[BulkAsyncDisburseLedgerData] = Field(...)

    @model_validator(mode='after')
    def validate_field(self):
        if not self.groupingId:
            raise HTTPException(status_code=400, detail="grouping id can not blank")
        if not special_char_pattern.match(self.groupingId):
            raise HTTPException(status_code=400, detail=f"groupingId can not accept special character {self.groupingId}")
        if not special_char_pattern.match(str(self.ledgerNo)):
            raise HTTPException(status_code=400, detail=f"ledgerNo can not accept special character {self.ledgerNo}")
        if not special_char_pattern.match(str(self.ledgerAmtFlag)):
            raise HTTPException(status_code=400, detail=f"ledgerAmtFlag can not accept special character {self.ledgerAmtFlag}")
        if not special_char_pattern.match(self.lenderCategory):
            raise HTTPException(status_code=400, detail=f"lenderCategory can not accept special character {self.lenderCategory}")
        if not lender_name_pattern.match(self.lenderName):
            raise HTTPException(status_code=400, detail=f"lenderName can not accept special character {self.lenderName}")
        if not special_char_pattern.match(self.lenderCode):
            raise HTTPException(status_code=400, detail=f"lenderCode can not accept special character {self.lenderCode}")
        return self

    @field_validator('groupingId')
    def validate_grouping_id(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="groupingId can not be blank")
        elif len(value) > 50:
            raise HTTPException(status_code=400, detail=f"groupingId can not be greater than 50 {value}")
        return value

    @field_validator('ledgerNo')
    def validate_ledger_no(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="ledgerNo can not be blank")
        elif len(value) > 100:
            raise HTTPException(status_code=400, detail=f"ledgerNo can not be greater than 100 {value}")
        elif value != "":
            # cleaned_string = re.sub(r'[^.-@!#$%^&*()<>?/\|}{~:a-zA-Z\b\s]', '', value)
            cleaned_string = value.isnumeric()
            if not cleaned_string:
                raise HTTPException(status_code=400, detail=f"ledger no can have only numeric value {value}")
        return value

    @field_validator('ledgerAmtFlag')
    def validate_ledger_amt_flag(cls, value: str):
        if value != '':
            if not value.lower() in ('full', 'partial'):
                raise HTTPException(status_code=400, detail=f"ledgerAmtFlag can be full or partial {value}")
        return value

    @field_validator('lenderCategory')
    def validate_lender_category(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="lenderCategory can not be blank")
        if value != '':
            if len(value) > 50:
                raise HTTPException(status_code=400, detail=f"lenderCategory can not be greater than 50 {value}")
        return value

    @field_validator('lenderName')
    def validate_lender_name(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="lenderName can not be blank")
        if value != "":
            if len(value) > 64:
                raise HTTPException(status_code=400, detail=f"lenderName can not be greater than 64 char {value}")
            # cleaned_string = re.sub(r'[^.-@!#$%^&*()<>?/\|}{~:\s]', '', value) #[.-@!#$%^&*()<>?/\|}{~:\b\s]
            # cleaned_string = value.isalnum()
            # if not cleaned_string:
            #     raise HTTPException(status_code=400, detail="lender name can not have special character")
        return value

    @field_validator('lenderCode')
    def validate_lender_code(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="lenderName can not be blank")
        if value != "":
            if len(value) > 20:
                raise HTTPException(status_code=400, detail=f"lenderCode can not be greater than 20 {value}")
        return value


class BulkAsyncDisbursementSchema(BaseSchema):
    groupData: List[AsyncDisbursementInvoiceGroupData] = Field(...)


class BulkAsyncRepaymentLedgerData(BaseModel):
    validationType: str
    validationRefNo : str
    invoiceNo: str
    assetClassification: str
    dueAmt: str
    dueDate: str
    repaymentType: str
    repaymentFlag: str
    repaymentAmt: str
    repaymentDate: str
    pendingDueAmt: str
    dpd: str
    invoiceDate: str
    invoiceAmt: str

    @model_validator(mode='after')
    def validate_field(self):
        if str(self.validationType) == '' and str(self.validationRefNo) != '':
            raise HTTPException(status_code=400, detail="validationType should not be blank")
        if str(self.validationRefNo) == '' and str(self.validationType) != '':
            raise HTTPException(status_code=400, detail="validationRefNo should not be blank")
        if str(self.validationRefNo) != '':
            validate_string = re.search(validation_ref_no_pattern, str(self.validationRefNo))
            if not validate_string:
                raise HTTPException(status_code=400, detail=f"validationRefNo can not accept special character {self.validationRefNo}")
        if not special_char_pattern.match(str(self.assetClassification)):
            raise HTTPException(status_code=400, detail=f"assetClassification can not accept special character{self.assetClassification}")
        if not date_special_char_pattern.match(str(self.dueDate)):
            raise HTTPException(status_code=400, detail=f"dueDate can not accept special character{self.dueDate}")
        if not special_char_pattern.match(self.repaymentType):
            raise HTTPException(status_code=400, detail=f"repaymentType can not accept special character{self.repaymentType}")
        if not special_char_pattern.match(str(self.repaymentFlag)):
            raise HTTPException(status_code=400, detail=f"repaymentFlag can not accept special character{self.repaymentFlag}")
        if not date_special_char_pattern.match(str(self.repaymentDate)):
            raise HTTPException(status_code=400, detail=f"repaymentDate can not accept special character {self.repaymentDate}")
        if not special_char_pattern.match(str(self.dpd)):
            raise HTTPException(status_code=400, detail=f"dpd can not accept special character {self.dpd}")
        if not date_special_char_pattern.match(str(self.invoiceDate)):
            raise HTTPException(status_code=400, detail=f"invoiceDate can not accept special character {self.invoiceDate}")
        check_decimal_precision('dueAmt', str(self.dueAmt))
        check_decimal_precision('pendingDueAmt', str(self.pendingDueAmt))
        check_decimal_precision('invoiceAmt', str(self.invoiceAmt))
        check_decimal_precision('repaymentAmt', str(self.repaymentAmt))
        return self

    @field_validator('validationType')
    def validate_validation_type(cls, value: str):
        # if value == '':
        #     raise HTTPException(status_code=400, detail="validationType can not be blank")
        if value != "":
            if not value.lower() in ('einvoice', 'ewaybill', 'gstfiling'):
                raise HTTPException(status_code=400, detail=f"validationType can be eInvoice, eWayBill or gstFiling {value}")
        return value

    # @field_validator('validationRefNo')
    # def validate_validation_ref_no(cls, value: str):
    #     # if value == '':
    #     #     raise HTTPException(status_code=400, detail="validationRefNo can not be blank")
    #     if value != "":
    #         if len(value) > 100:
    #             raise HTTPException(status_code=400, detail="validationRefNo can not be greater than 100")
    #     return value

    @field_validator('invoiceNo')
    def validate_invoice_no(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="InvoiceNo can not be blank")
        elif len(value) > 100:
            raise HTTPException(status_code=400, detail=f"InvoiceNo can not be greater than 100 {value}")
        elif not re.match(invoice_number_pattern, value):
            raise HTTPException(status_code=400, detail=f"Invalid invoice number format. Use only letters, numbers, spaces, and symbols: '-', '_', '/', '#'. Please check your input.")
        return value

    @field_validator('assetClassification')
    def validate_asset_classification(cls, value: str):
        if len(value) > 250:
            raise HTTPException(status_code=400, detail=f"assetClassification can not be greater than 250 {value}")
        return value

    @field_validator('dueAmt')
    def validate_due_amt(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="dueAmt can not be blank")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"dueAmt can not be greater than 20 digit {value}")
        return value

    @field_validator('dueDate')
    def validate_due_date(cls, value: date) -> date:
        if value == '':
            raise HTTPException(status_code=400, detail="dueDate can not be blank")
        elif len(str(value)) > 10:
            raise HTTPException(status_code=400, detail=f"dueDate can not be greater than 10 {value}")
        elif value != '':
            try:
                dd = datetime.strptime(value, "%d/%m/%Y")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"date format except d/m/Y format {value}")
        return value

    @field_validator('repaymentType')
    def validate_repayment_type(cls, value: str):
        if len(value) > 20:
            raise HTTPException(status_code=400, detail=f"repaymentType can not be greater than 20 {value}")
        return value

    @field_validator('repaymentAmt')
    def validate_repayment_amt(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="repaymentAmt can not be blank")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"repaymentAmt can not be greater than 20 digit {value}")
        return value

    @field_validator('repaymentDate')
    def validate_repayment_date(cls, value: date) -> date:
        if value == '':
            raise HTTPException(status_code=400, detail="repaymentDate can not be blank")
        elif len(str(value)) > 10:
            raise HTTPException(status_code=400, detail=f"repaymentDate can not be greater than 10 {value}")
        elif value != '':
            try:
                dd = datetime.strptime(value, "%d/%m/%Y")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"date format accept d/m/Y format {value}")
        return value

    @field_validator('repaymentFlag')
    def validate_repayment_flag(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="repaymentFlag can not be blank")
        elif len(value) > 20:
            raise HTTPException(status_code=400, detail=f"repaymentFlag can not be greater than 20 {value}")
        else:
            if not value.lower() in ('full', 'partial'):
                raise HTTPException(status_code=400, detail=f"repayment flag can be full or partial {value}")
        return value

    @field_validator('pendingDueAmt')
    def validate_pending_due_amount(cls, value: int):
        if value == '':
            raise HTTPException(status_code=400, detail="pendingDueAmt can not be blank")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"pendingDueAmt can not be greater than 20 digit {value}")
        return value

    @field_validator('dpd')
    def validate_dpd(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="dpd can not be blank")
        elif len(str(value)) > 10:
            raise HTTPException(status_code=400, detail=f"dpd can not be greater than 10 {value}")
        return value

    @field_validator('invoiceDate')
    def validate_invoice_date(cls, value: date) -> date:
        if value == '':
            raise HTTPException(status_code=400, detail="InvoiceDate can not be blank")
        elif len(str(value)) > 10:
            raise HTTPException(status_code=400, detail=f"InvoiceDate can not be greater than 10 {value}")
        elif value != '':
            try:
                dd = datetime.strptime(value, "%d/%m/%Y")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"date format except d/m/Y format {value}")
        return value

    @field_validator('invoiceAmt')
    def validate_invoice_amount(cls, value: int):
        if value == '':
            raise HTTPException(status_code=400, detail="invoiceAmt can not be blank")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"invoiceAmt can not be greater than 20 digit {value}")
        return value


class AsyncRepaymentInvoiceGroupData(BaseModel):
    groupingId: str
    ledgerNo: str
    borrowerCategory: str
    ledgerData: List[BulkAsyncRepaymentLedgerData] = Field(...)

    @model_validator(mode='after')
    def validate_field(self):
        if not special_char_pattern.match(str(self.groupingId)):
            raise HTTPException(status_code=400, detail=f"groupingId can not accept special character {self.groupingId}")
        if not special_char_pattern.match(str(self.ledgerNo)):
            raise HTTPException(status_code=400, detail=f"ledgerNo can not accept special character {self.ledgerNo}")
        if not special_char_pattern.match(str(self.borrowerCategory)):
            raise HTTPException(status_code=400, detail=f"borrowerCategory can not accept special character {self.borrowerCategory}")
        return self

    @field_validator('groupingId')
    def validate_grouping_id(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="groupingId can not be blank")
        elif len(value) > 50:
            raise HTTPException(status_code=400, detail=f"groupingId can not be greater than 50 {value}")
        return value

    @field_validator('ledgerNo')
    def validate_ledger_no(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="ledgerNo can not be blank")
        elif len(value) > 100:
            raise HTTPException(status_code=400, detail=f"ledgerNo can not be greater than 100 {value}")
        elif value != "":
            cleaned_string = value.isnumeric()
            if not cleaned_string:
                raise HTTPException(status_code=400, detail=f"ledger no can have only numeric value {value}")
        return value

    @field_validator('borrowerCategory')
    def validate_borrower_category(cls, value: str):
        if len(value) > 50:
            raise HTTPException(status_code=400, detail=f"borrowerCategory can not be greater than 50 {value}")
        return value


class BulkAsyncRepaymentSchema(BaseSchema):
    groupData: List[AsyncRepaymentInvoiceGroupData] = Field(...)


class BulkAsyncDisbursementRepaymentLedgerData(BaseModel):
    validationType: str
    validationRefNo : str
    invoiceNo: str
    assetClassification: str
    dueAmt: str
    disbursedFlag: str
    disbursedAmt: str
    disbursedDate: str
    dueDate: str
    repaymentType: str
    repaymentFlag: str
    repaymentAmt: str
    repaymentDate: str
    pendingDueAmt: str
    dpd: str
    invoiceDate: str
    invoiceAmt: str

    @model_validator(mode='after')
    def validate_field(self):
        if str(self.validationType) == '' and str(self.validationRefNo) != '':
            raise HTTPException(status_code=400, detail="validationType should not be blank")
        if str(self.validationRefNo) == '' and str(self.validationType) != '':
            raise HTTPException(status_code=400, detail="validationRefNo should not be blank")
        if str(self.validationRefNo) != '':
            validate_string = re.search(validation_ref_no_pattern, str(self.validationRefNo))
            if not validate_string:
                raise HTTPException(status_code=400, detail=f"validationRefNo can not accept special character {self.validationRefNo}")
        if not special_char_pattern.match(str(self.assetClassification)):
            raise HTTPException(status_code=400, detail=f"assetClassification can not accept special character {self.assetClassification}")
        if not special_char_pattern.match(str(self.disbursedFlag)):
            raise HTTPException(status_code=400, detail=f"disbursedFlag can not accept special character {self.disbursedFlag}")
        if not date_special_char_pattern.match(self.disbursedDate):
            raise HTTPException(status_code=400, detail=f"disbursedDate can not accept special character {self.disbursedDate}")
        if not date_special_char_pattern.match(str(self.dueDate)):
            raise HTTPException(status_code=400, detail=f"dueDate can not accept special character {self.dueDate}")
        if not special_char_pattern.match(self.repaymentType):
            raise HTTPException(status_code=400, detail=f"repaymentType can not accept special character {self.repaymentType}")
        if not special_char_pattern.match(str(self.repaymentFlag)):
            raise HTTPException(status_code=400, detail=f"repaymentFlag can not accept special character {self.repaymentFlag}")
        if not date_special_char_pattern.match(str(self.repaymentDate)):
            raise HTTPException(status_code=400, detail=f"repaymentDate can not accept special character {self.repaymentDate}")
        if not special_char_pattern.match(str(self.dpd)):
            raise HTTPException(status_code=400, detail=f"dpd can not accept special character {self.dpd}")
        if not date_special_char_pattern.match(str(self.invoiceDate)):
            raise HTTPException(status_code=400, detail=f"invoiceDate can not accept special character {self.invoiceDate}")
        check_decimal_precision('disbursedAmt', str(self.disbursedAmt))
        check_decimal_precision('dueAmt', str(self.dueAmt))
        check_decimal_precision('pendingDueAmt', str(self.pendingDueAmt))
        check_decimal_precision('invoiceAmt', str(self.invoiceAmt))
        check_decimal_precision('repaymentAmt', str(self.repaymentAmt))
        return self

    @field_validator('validationType')
    def validate_validation_type(cls, value: str):
        # if value == '':
        #     raise HTTPException(status_code=400, detail="validationType can not be blank")
        if value != "":
            if not value.lower() in ('einvoice', 'ewaybill', 'gstfiling'):
                raise HTTPException(status_code=400, detail=f"validationType can be eInvoice, eWayBill or gstFiling {value}")
        return value

    # @field_validator('validationRefNo')
    # def validate_validation_ref_no(cls, value: str):
    #     # if value == '':
    #     #     raise HTTPException(status_code=400, detail="validationRefNo can not be blank")
    #     if value != "":
    #         if len(value) > 100:
    #             raise HTTPException(status_code=400, detail="validationRefNo can not be greater than 100")
    #     return value

    @field_validator('invoiceNo')
    def validate_invoice_no(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="InvoiceNo can not be blank")
        elif len(value) > 100:
            raise HTTPException(status_code=400, detail=f"InvoiceNo can not be greater than 100 {value}")
        elif not re.match(invoice_number_pattern, value):
            raise HTTPException(status_code=400, detail=f"Invalid invoice number format. Use only letters, numbers, spaces, and symbols: '-', '_', '/', '#'. Please check your input.")
        return value

    @field_validator('assetClassification')
    def validate_asset_classification(cls, value: str):
        if len(value) > 250:
            raise HTTPException(status_code=400, detail=f"assetClassification can not be greater than 250 {value}")
        return value

    @field_validator('dueAmt')
    def validate_due_amt(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="dueAmt can not be blank")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"dueAmt can not be greater than 20 digit {value}")
        return value

    @field_validator('disbursedFlag')
    def validate_disbursed_flag(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="disbursedFlag can not be blank")
        else:
            if not value.lower() in ('full', 'partial'):
                raise HTTPException(status_code=400, detail=f"disbursedFlag can be full or partial {value}")
        return value

    @field_validator('disbursedAmt')
    def validate_disbursed_amt(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="disbursedAmt can not be blank")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"disbursedAmt can not be greater than 20 digit {value}")
        return value

    @field_validator('disbursedDate')
    def validate_disbursed_date(cls, value: date) -> date:
        if value == '':
            raise HTTPException(status_code=400, detail="disbursed date can not be blank")
        elif len(str(value)) > 10:
            raise HTTPException(status_code=400, detail=f"disbursedDate can not be greater than 10 {value}")
        elif value != '':
            from datetime import datetime
            try:
                dd = datetime.strptime(value, "%d/%m/%Y")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"date format accept d/m/Y format {value}")
        return value

    @field_validator('dueDate')
    def validate_due_date(cls, value: date) -> date:
        if value == '':
            raise HTTPException(status_code=400, detail="dueDate can not be blank")
        elif len(str(value)) > 10:
            raise HTTPException(status_code=400, detail=f"dueDate can not be greater than 10 {value}")
        elif value != '':
            try:
                dd = datetime.strptime(value, "%d/%m/%Y")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"date format except d/m/Y format {value}")
        return value

    @field_validator('repaymentType')
    def validate_repayment_type(cls, value: str):
        if len(value) > 20:
            raise HTTPException(status_code=400, detail=f"repaymentType can not be greater than 20 {value}")
        return value

    @field_validator('repaymentAmt')
    def validate_repayment_amt(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="repaymentAmt can not be blank")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"repaymentAmt can not be greater than 20 digit {value}")
        return value

    @field_validator('repaymentDate')
    def validate_repayment_date(cls, value: date) -> date:
        if value == '':
            raise HTTPException(status_code=400, detail="repaymentDate can not be blank")
        elif len(str(value)) > 10:
            raise HTTPException(status_code=400, detail=f"repaymentDate can not be greater than 10 {value}")
        elif value != '':
            try:
                dd = datetime.strptime(value, "%d/%m/%Y")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"date format accept d/m/Y format {value}")
        return value

    @field_validator('repaymentFlag')
    def validate_repayment_flag(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="repaymentFlag can not be blank")
        elif len(value) > 20:
            raise HTTPException(status_code=400, detail=f"repaymentFlag can not be greater than 20 {value}")
        else:
            if not value.lower() in ('full', 'partial'):
                raise HTTPException(status_code=400, detail=f"repayment flag can be full or partial {value}")
        return value

    @field_validator('pendingDueAmt')
    def validate_pending_due_amount(cls, value: int):
        if value == '':
            raise HTTPException(status_code=400, detail="pendingDueAmt can not be blank")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"pendingDueAmt can not be greater than 20 digit {value}")
        return value

    @field_validator('dpd')
    def validate_dpd(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="dpd can not be blank")
        elif len(str(value)) > 10:
            raise HTTPException(status_code=400, detail=f"dpd can not be greater than 10{value}")
        return value

    @field_validator('invoiceDate')
    def validate_invoice_date(cls, value: date) -> date:
        if value == '':
            raise HTTPException(status_code=400, detail="InvoiceDate can not be blank")
        elif len(str(value)) > 10:
            raise HTTPException(status_code=400, detail=f"InvoiceDate can not be greater than 10 {value}")
        elif value != '':
            try:
                dd = datetime.strptime(value, "%d/%m/%Y")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"date format except d/m/Y format {value}")
        return value

    @field_validator('invoiceAmt')
    def validate_invoice_amount(cls, value: int):
        if value == '':
            raise HTTPException(status_code=400, detail="invoiceAmt can not be blank")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"invoiceAmt can not be greater than 20 digit {value}")
        return value


class AsyncDisbursementRepaymentInvoiceGroupData(BaseModel):
    groupingId: str
    ledgerNo: str
    lenderCategory: str
    lenderName: str
    lenderCode: str
    borrowerCategory: str
    ledgerData: List[BulkAsyncDisbursementRepaymentLedgerData] = Field(...)

    @model_validator(mode='after')
    def validate_field(self):
        if not special_char_pattern.match(str(self.groupingId)):
            raise HTTPException(status_code=400, detail=f"groupingId can not accept special character{self.groupingId}")
        if not special_char_pattern.match(str(self.ledgerNo)):
            raise HTTPException(status_code=400, detail=f"ledgerNo can not accept special character {self.ledgerNo}")
        if not special_char_pattern.match(self.lenderCategory):
            raise HTTPException(status_code=400, detail=f"lenderCategory can not accept special character {self.lenderCategory}")
        if not lender_name_pattern.match(self.lenderName):
            raise HTTPException(status_code=400, detail=f"lenderName can not accept special character {self.lenderName}")
        if not special_char_pattern.match(self.lenderCode):
            raise HTTPException(status_code=400, detail=f"lenderCode can not accept special character {self.lenderCode}")
        if not special_char_pattern.match(str(self.borrowerCategory)):
            raise HTTPException(status_code=400, detail=f"borrowerCategory can not accept special character {self.borrowerCategory}")
        return self

    @field_validator('groupingId')
    def validate_grouping_id(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="groupingId can not be blank")
        elif len(value) > 50:
            raise HTTPException(status_code=400, detail=f"groupingId can not be greater than 50 {value}")
        return value

    @field_validator('ledgerNo')
    def validate_ledger_no(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="ledgerNo can not be blank")
        elif len(value) > 100:
            raise HTTPException(status_code=400, detail=f"ledgerNo can not be greater than 100 {value}")
        elif value != "":
            cleaned_string = value.isnumeric()
            if not cleaned_string:
                raise HTTPException(status_code=400, detail=f"ledger no can have only numeric value {value}")
        return value

    @field_validator('lenderCategory')
    def validate_lender_category(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="lenderCategory can not be blank")
        if value != '':
            if len(value) > 50:
                raise HTTPException(status_code=400, detail=f"lenderCategory can not be greater than 50 {value}")
        return value

    @field_validator('lenderName')
    def validate_lender_name(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="lenderName can not be blank")
        if value != "":
            if len(value) > 64:
                raise HTTPException(status_code=400, detail=f"lenderName can not be greater than 64 char {value}")
            # cleaned_string = re.sub(r'[^.-@!#$%^&*()<>?/\|}{~:\s]', '', value) #[.-@!#$%^&*()<>?/\|}{~:\b\s]
            # cleaned_string = value.isalnum()
            # if not cleaned_string:
            #     raise HTTPException(status_code=400, detail="lender name can not have special character")
        return value

    @field_validator('lenderCode')
    def validate_lender_code(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="lenderCode can not be blank")
        if value != "":
            if len(value) > 20:
                raise HTTPException(status_code=400, detail=f"lenderCode can not be greater than 20 {value}")
        return value

    @field_validator('borrowerCategory')
    def validate_borrower_category(cls, value: str):
        if len(value) > 50:
            raise HTTPException(status_code=400, detail=f"borrowerCategory can not be greater than 50 {value}")
        return value


class BulkAsyncDisbursementRepaymentSchema(BaseSchema):
    groupData: List[AsyncDisbursementRepaymentInvoiceGroupData] = Field(...)


class LedgerRegistrationFinanceSchema(BaseModel):
    validationType: str
    validationRefNo: str
    invoiceNo: str
    invoiceDate: str = Field(default='01/06/1989')
    invoiceAmt: str
    verifyGSTNFlag: bool
    invoiceDueDate: str = Field(default='01/06/1989')
    financeRequestAmt: str
    financeRequestDate: str = Field(default='01/06/1989')
    dueDate: str
    fundingAmtFlag: str
    adjustmentType: str
    adjustmentAmt: str

    @field_validator('invoiceNo')
    def validate_invoice_no(cls, value: str):
        logger.info(f"getting data {re.match(invoice_number_pattern, value)}")
        if value == '':
            raise HTTPException(status_code=400, detail="Invoice no can not be blank")
        elif len(value) > 100:
            raise HTTPException(status_code=400, detail=f"Invoice number can not be greater than 100 {value}")
        elif not re.match(invoice_number_pattern, value):
            raise HTTPException(status_code=400, detail=f"Invalid invoice number format. Use only letters, numbers, spaces, and symbols: '-', '_', '/', '#'. Please check your input.")
        return value

    @field_validator('invoiceDate')
    def validate_invoice_date(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="Invoice date can not be blank")
        elif len(value) > 10:
            raise HTTPException(status_code=400, detail=f"Invoice date can not be greater than 10 {value}")
        return value

    @field_validator('invoiceDate')
    def validate_invoice_dates(cls, value: date) -> date:
        from datetime import datetime
        try:
            dd = datetime.strptime(value, "%d/%m/%Y")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"date format except d/m/Y format {value}")
        return value

    @field_validator('invoiceAmt')
    def validate_invoice_amount(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="Invoice amount can not be blank")
        if value == '0':
            raise HTTPException(status_code=400, detail=f"Invoice amount should be greater than 0 {value}")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"Invoice number can not be greater than 20 {value}")
        elif not bool(re.match(amt_regex_pattern, value)):
            raise HTTPException(status_code=400, detail=f"Invalid invoice amount {value}")
        if '.' in value:
            amount_list = value.split('.')
            if len(amount_list) > 2:
                raise HTTPException(status_code=400, detail="Invalid invoice amount")
            elif len(amount_list[1]) > 2:
                raise HTTPException(status_code=400, detail=f"Invoice amount can not accept more than two digit value {value}")
        return value

    @field_validator('verifyGSTNFlag')
    def validate_verify_gst_flag(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="Verify gst flag can not be blank")
        elif value not in [True, False]:
            raise HTTPException(status_code=400, detail=f"Verify gst flag either True or False {value}")
        return value

    @field_validator('invoiceDueDate')
    def validate_invoice_due_date(cls, value: date) -> date:
        from datetime import datetime
        if len(value) > 10:
            raise HTTPException(status_code=400, detail=f"Invoice due date can not be greater than 10 {value}")
        elif value != "":
            try:
                dd = datetime.strptime(value, "%d/%m/%Y")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invoice due date format except d/m/Y format {value}")
            return value
        else:
            return value

    @model_validator(mode='after')
    def validate_field(self):
        if self.validationRefNo != "":
            validate_string = re.search(validation_ref_no_pattern, self.validationRefNo)
            if not validate_string:
                raise HTTPException(status_code=400, detail=f"validationRefNo can not accept special character {self.validationRefNo}")
            if self.validationType.lower() not in ['einvoice', 'ewaybill', 'gstfiling']:
                raise HTTPException(status_code=400, detail=f"validation type should be eInvoice, eWayBill, gstFiling {self.validationType}")
        if self.verifyGSTNFlag:
            if self.validationType.lower() not in ['einvoice', 'ewaybill', 'gstfiling']:
                raise HTTPException(status_code=400, detail=f"validation type should be eInvoice, eWayBill, gstFiling {self.verifyGSTNFlag}")
            if not self.validationRefNo:
                raise HTTPException(status_code=400, detail="Validation reference no can not be blank")
        if self.validationType:
            if not self.validationRefNo:
                raise HTTPException(status_code=400, detail="Validation reference no can not be blank")
        if not date_special_char_pattern.match(str(self.financeRequestDate)):
            raise HTTPException(status_code=400, detail=f"financeRequestDate can not accept special character {self.financeRequestDate}")
        if not date_special_char_pattern.match(str(self.dueDate)):
            raise HTTPException(status_code=400, detail=f"dueDate can not accept special character {self.dueDate}")
        if not special_char_pattern.match(self.fundingAmtFlag):
            raise HTTPException(status_code=400, detail=f"fundingAmtFlag can not accept special character {self.fundingAmtFlag}")
        if not special_char_pattern.match(str(self.adjustmentType)):
            raise HTTPException(status_code=400, detail=f"adjustmentType can not accept special character {self.adjustmentType}")
        if not date_special_char_pattern.match(str(self.invoiceDate)):
            raise HTTPException(status_code=400, detail=f"invoiceDate can not accept special character {self.invoiceDate}")

        check_decimal_precision('adjustmentAmt', str(self.adjustmentAmt))
        check_decimal_precision('financeRequestAmt', str(self.financeRequestAmt))
        check_decimal_precision('invoiceAmt', str(self.invoiceAmt))
        return self

    @field_validator('financeRequestAmt')
    def validate_finance_request_amount(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="financeRequestAmt can not be blank")
        if value == '0':
            raise HTTPException(status_code=400, detail=f"financeRequestAmt should be greater than 0 {value}")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"financeRequestAmt can not be greater than 20 {value}")
        return value

    @field_validator('financeRequestDate')
    def validate_finance_request_date(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="financeRequest Date can not be blank")
        elif len(value) > 10:
            raise HTTPException(status_code=400, detail=f"financeRequest Date can not be greater than 10 {value}")
        return value

    @field_validator('financeRequestDate')
    def validate_finance_request_dates(cls, value: date) -> date:
        from datetime import datetime
        try:
            dd = datetime.strptime(value, "%d/%m/%Y")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"date format accept d/m/Y format {value}")
        return value

    @field_validator('dueDate')
    def validate_due_date(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="dueDate can not be blank")
        elif len(value) > 10:
            raise HTTPException(status_code=400, detail=f"due Date can not be greater than 10 {value}")
        return value

    @field_validator('dueDate')
    def validate_due_dates(cls, value: date) -> date:
        from datetime import datetime
        try:
            dd = datetime.strptime(value, "%d/%m/%Y")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"date format except d/m/Y format {value}")
            # raise ValueError("date formate except d/m/Y formate")
        return value

    @field_validator('fundingAmtFlag')
    def validate_funding_amt_flag(cls, value: str):
        # if value == '':
        #     raise HTTPException(status_code=400, detail="fundingAmtFlag can not be blank")
        if len(value) > 20:
            raise HTTPException(status_code=400, detail=f"funding amt flag can not be greater than 20 {value}")
        elif value != '':
            if not value.lower() in ('full', 'partial'):
                raise HTTPException(status_code=400, detail=f"Funding amt flag can be full or partial {value}")
        return value

    @field_validator('adjustmentType')
    def validate_adjustment_type(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="adjustmentType can not be blank")
        elif len(value) > 30:
            raise HTTPException(status_code=400, detail=f"adjustmentType can not be greater than 30 {value}")
        else:
            if not value.lower() in ('none', 'advance', 'creditnote'):
                raise HTTPException(status_code=400, detail=f"adjustmentType can be none, advance or creditnote {value}")
        return value

    @field_validator('adjustmentAmt')
    def validate_adjustment_amt(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="adjustmentAmt can not be blank")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"adjustmentAmt can not be greater than 20 {value}")
        return value


class InvoiceRequestWithFinGroupSchema(BaseModel):
    sellerGst: str
    buyerGst: str
    groupingId: str
    ledgerAmtFlag: str
    lenderCategory: str
    lenderName: str
    lenderCode: str
    borrowerCategory: str
    ledgerData: List[LedgerRegistrationFinanceSchema] = Field(...)
    sellerIdentifierData: Optional[List[SellerData]] = Field(None)
    buyerIdentifierData: Optional[List[BuyerData]] = Field(None)

    @field_validator('groupingId')
    def validate_grouping_id(cls, value: str):
        if not value:
            raise HTTPException(status_code=400, detail="grouping id can not blank")
        if not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"grouping id can not accept special character {value}")
        if len(value) > 30:
            raise HTTPException(status_code=400, detail=f"grouping id can not be greater than 30 {value}")
        return value

    @field_validator('sellerGst')
    def validate_seller_gst(cls, value: str):
        if value == '':
            pass
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"seller gst can not accept special character {value}")
        elif len(value) > 20:
            raise HTTPException(status_code=400, detail=f"seller gst can not greater than 20 {value}")
        elif value != "":
            seller_gst_value = ValidationCheck.validate_gst(value)
            if not seller_gst_value:
                raise HTTPException(status_code=400, detail=f"seller gst is not valid {value}")
        return value

    @field_validator('buyerGst')
    def validate_buyer_gst(cls, value: str):
        if value == '':
            pass
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"buyer gst can not accept special character {value}")
        elif len(value) > 20:
            raise HTTPException(status_code=400, detail=f"buyer gst can not greater than 20 {value}")
        elif value != "":
            buyer_gst_value = ValidationCheck.validate_gst(value)
            if not buyer_gst_value:
                raise HTTPException(status_code=400, detail=f"buyer gst is not valid {value}")
        return value

    @field_validator('ledgerAmtFlag')
    def validate_ledger_amt_flag(cls, value: str):
        if value != '':
            if not value.lower() in ('full', 'partial'):
                raise HTTPException(status_code=400, detail=f"ledgerAmtFlag can be full or partial {value}")
        return value

    @field_validator('lenderCategory')
    def validate_lender_category(cls, value: str):
        # if value == '':
        #     raise HTTPException(status_code=400, detail="lenderCategory can not be blank")
        if value != '':
            if len(value) > 50:
                raise HTTPException(status_code=400, detail=f"lenderCategory can not be greater than 50 {value}")
        return value

    @field_validator('lenderName')
    def validate_lender_name(cls, value: str):
        if value != "":
            if len(value) > 64:
                raise HTTPException(status_code=400, detail=f"lenderName can not be greater than 64 char {value}")
            # cleaned_string = value.isalnum()
            # if not cleaned_string:
            #     raise HTTPException(status_code=400, detail="lender name can not have special character")
        return value

    @field_validator('lenderCode')
    def validate_lender_code(cls, value: str):
        if value != '':
            if len(value) > 20:
                raise HTTPException(status_code=400, detail=f"lenderCode can not be greater than 20 {value}")
        return value

    @field_validator('borrowerCategory')
    def validate_borrower_category(cls, value: str):
        if len(value) > 50:
            raise HTTPException(status_code=400, detail=f"borrowerCategory can not be greater than 50 {value}")
        return value

    @model_validator(mode='after')
    def validate_field(self):
        import utils
        json_request_data = jsonable_encoder(self)
        validate_seller_identifier = utils.validate_seller_identifier(json_request_data)
        validate_buyer_identifier = utils.validate_buyer_identifier(json_request_data)
        invoice_date_response = utils.check_invoice_date(json_request_data)
        invoice_due_date_response = utils.check_invoice_due_date(json_request_data)
        duplicates_json_exist = utils.are_duplicates_exist(json_request_data.get('ledgerData'))
        duplicate_identifier_values = utils.check_for_duplicate_values(json_request_data)
        duplicate_pan_value = utils.check_for_duplicate_pan_values(json_request_data)
        duplicate_lei_value = utils.check_for_duplicate_lei_values(json_request_data)
        duplicate_cin_value = utils.check_for_duplicate_cin_values(json_request_data)
        duplicate_tax_no_value = utils.check_for_duplicate_tax_no_values(json_request_data)
        if not validate_seller_identifier:
            raise HTTPException(status_code=400,
                                detail="Seller identifier data can not be blank if seller gst is blank")
        if not validate_buyer_identifier:
            raise HTTPException(status_code=400, detail="Buyer identifier data can not be blank if buyer gst is blank")
        if not invoice_date_response:
            raise HTTPException(status_code=400, detail="Invoice date is greater then current date")
        if invoice_due_date_response:
            raise HTTPException(status_code=400, detail="Invoice due date should be greater than invoice date")
        if duplicates_json_exist:
            raise HTTPException(status_code=400, detail="Duplicate invoice data found")
        if duplicate_identifier_values:
            raise HTTPException(status_code=400, detail="sellerIdNo and buyerIdNo cannot be same.")
        if duplicate_pan_value:
            raise HTTPException(status_code=400, detail="sellerIdNo and buyerIdNo cannot be same.")
        if duplicate_lei_value:
            raise HTTPException(status_code=400, detail="sellerIdNo and buyerIdNo cannot be same.")
        if duplicate_cin_value:
            raise HTTPException(status_code=400, detail="sellerIdNo and buyerIdNo cannot be same.")
        if duplicate_tax_no_value:
            raise HTTPException(status_code=400, detail="sellerIdNo and buyerIdNo cannot be same.")
        if not special_char_pattern.match(str(self.ledgerAmtFlag)):
            raise HTTPException(status_code=400, detail=f"ledgerAmtFlag can not accept special character {self.ledgerAmtFlag}")
        if not special_char_pattern.match(self.lenderCategory):
            raise HTTPException(status_code=400, detail=f"lenderCategory can not accept special character {self.lenderCategory}")
        if not lender_name_pattern.match(self.lenderName):
            raise HTTPException(status_code=400, detail=f"lenderName can not accept special character {self.lenderName}")
        if not special_char_pattern.match(self.lenderCode):
            raise HTTPException(status_code=400, detail=f"lenderCode can not accept special character {self.lenderCode}")
        if not special_char_pattern.match(self.borrowerCategory):
            raise HTTPException(status_code=400, detail=f"borrowerCategory can not accept special character {self.borrowerCategory}")
        return self


class InvoiceBulkRequestWithoutCodeFinSchema(BaseSchema):

    groupData: List[InvoiceRequestWithFinGroupSchema] = Field(...)


class GSPUserCreateSchema(BaseModel):
    requestId: str
    gstin: str
    gsp: str
    username: str
    password: str
    name: str
    pan: str
    emailId: str
    mobileNumber: str
    idpId: str = Field(None, title="Optional IdpId")

    @field_validator('requestId')
    def validate_request_id(cls, value: str):
        if not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"request id can not accept special character {value}")
        if value.strip() == '':
            raise HTTPException(status_code=400, detail="request id can not be blank")
        elif len(value) > 30:
            raise HTTPException(status_code=400, detail=f"request id can not be greater than 30 {value}")
        return value

    @field_validator('gstin')
    def validate_gstin(cls, value: str):
        if value.strip() == '':
            raise HTTPException(status_code=400, detail="gstin can not be blank")
        elif value != "":
            gstin_value = ValidationCheck.validate_gst(value.strip())
            if not gstin_value:
                raise HTTPException(status_code=400, detail=f"gstin is not valid {value}")
        elif len(value) > 15:
            raise HTTPException(status_code=400, detail=f"gstin can not be greater than 15 {value}")
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"gstin can not accept special character {value}")
        return value

    @field_validator('gsp')
    def validate_gsp(cls, value: str):
        if not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"gsp can not accept special character {value}")
        if value.strip() == '':
            raise HTTPException(status_code=400, detail="gsp can not be blank")
        elif len(value) > 10:
            raise HTTPException(status_code=400, detail=f"gsp can not be greater than 10 {value}")
        elif value.capitalize() not in ['Vayana', 'Cygnet']:
            raise HTTPException(status_code=400, detail=f"gsp can be Vayana or Cygnet {value}")
        return value

    @field_validator('username')
    def validate_uname(cls, value: str):
        if value.strip() == '':
            raise HTTPException(status_code=400, detail="username can not be blank")
        # elif value != "":
        #     uname_value = ValidationCheck.validate_name_value(value.strip())
        #     if not uname_value:
        #         raise HTTPException(status_code=400, detail=f"username is not valid {value}")
        elif len(value) > 100:
            raise HTTPException(status_code=400, detail=f"username can not be greater than 100 {value}")
        # elif not username_special_char_pattern.match(value):
        #     raise HTTPException(status_code=400, detail=f"username can not accept special character {value}")
        return value

    @field_validator('password')
    def validate_pwd(cls, value: str):
        if value.strip() == '':
            raise HTTPException(status_code=400, detail="password can not be blank")
        # elif value != "":
        #     pwd_value = ValidationCheck.validate_name_value(value.strip())
        #     if not pwd_value:
        #         raise HTTPException(status_code=400, detail=f"password is not valid {value}")
        elif len(value) > 100:
            raise HTTPException(status_code=400, detail=f"password can not be greater than 100 {value}")
        # elif not special_char_pattern.match(value):
        #     raise HTTPException(status_code=400, detail=f"password can not accept special character {value}")
        return value

    @field_validator('name')
    def validate_name(cls, value: str):
        if value.strip() == '':
            raise HTTPException(status_code=400, detail="name can not be blank")
        elif value != "":
            name_value = ValidationCheck.validate_corporate_name_value(value.strip())
            if not name_value:
                raise HTTPException(status_code=400, detail=f"name is not valid {value}")
        elif len(value) > 100:
            raise HTTPException(status_code=400, detail=f"name can not be greater than 100 {value}")
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"name can not accept special character {value}")
        return value

    @field_validator('pan')
    def validate_pan(cls, value: str):
        if value.strip() == '':
            raise HTTPException(status_code=400, detail="pan can not be blank")
        elif value != "":
            pan_value = ValidationCheck.validate_pan_card(value.strip())
            if not pan_value:
                raise HTTPException(status_code=400, detail=f"pan is not valid {value}")
        elif len(value) > 10:
            raise HTTPException(status_code=400, detail=f"pan can not be greater than 10 {value}")
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"pan can not accept special character {value}")
        return value

    @field_validator('emailId')
    def validate_email(cls, value: str):
        if value.strip() == '':
            pass
        elif value != "":
            email_value = ValidationCheck.validate_email(value.strip())
            if not email_value:
                raise HTTPException(status_code=400, detail=f"emailId is not valid {value}")
        elif len(value) > 100:
            raise HTTPException(status_code=400, detail=f"emailId can not be greater than 100 {value}")
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"emailId can not accept special character {value}")
        return value

    @field_validator('mobileNumber')
    def validate_contact(cls, value: str):
        if value.strip() == '':
            raise HTTPException(status_code=400, detail="mobileNumber can not be blank")
        elif value != "":
            contact_value = ValidationCheck.validate_phone(value.strip())
            if not contact_value:
                raise HTTPException(status_code=400, detail=f"mobileNumber is not valid {value}")
        elif len(value) > 10:
            raise HTTPException(status_code=400, detail=f"mobileNumber can not be greater than 100 {value}")
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"mobileNumber can not accept special character {value}")
        return value


class LedgerRegistrationFinanceDisbursementSchema(BaseModel):
    validationType: str
    validationRefNo: str
    invoiceNo: str
    invoiceDate: str = Field(default='01/06/1989')
    invoiceAmt: str
    verifyGSTNFlag: bool
    invoiceDueDate: str = Field(default='01/06/1989')
    financeRequestAmt: str
    financeRequestDate: str = Field(default='01/06/1989')
    dueDate: str
    fundingAmtFlag: str
    adjustmentType: str
    adjustmentAmt: str
    disbursedFlag: Optional[str] = None
    disbursedAmt: Optional[str] = None
    disbursedDate: Optional[str] = None
    dueAmt: Optional[str] = None

    @field_validator('invoiceNo')
    def validate_invoice_no(cls, value: str):
        logger.info(f"getting data {re.match(invoice_number_pattern, value)}")
        if value == '':
            raise HTTPException(status_code=400, detail="Invoice no can not be blank")
        elif len(value) > 100:
            raise HTTPException(status_code=400, detail=f"Invoice number can not be greater than 100 {value}")
        elif not re.match(invoice_number_pattern, value):
            raise HTTPException(status_code=400, detail=f"Invalid invoice number format. Use only letters, numbers, spaces, and symbols: '-', '_', '/', '#'. Please check your input.")
        return value

    @field_validator('invoiceDate')
    def validate_invoice_date(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="Invoice date can not be blank")
        elif len(value) > 10:
            raise HTTPException(status_code=400, detail=f"Invoice date can not be greater than 10 {value}")
        return value

    @field_validator('invoiceDate')
    def validate_invoice_dates(cls, value: date) -> date:
        from datetime import datetime
        try:
            dd = datetime.strptime(value, "%d/%m/%Y")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"date format except d/m/Y format {value}")
        return value

    @field_validator('invoiceAmt')
    def validate_invoice_amount(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="Invoice amount can not be blank")
        if value == '0':
            raise HTTPException(status_code=400, detail=f"Invoice amount should be greater than 0 {value}")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"Invoice number can not be greater than 20 {value}")
        elif not bool(re.match(amt_regex_pattern, value)):
            raise HTTPException(status_code=400, detail=f"Invalid invoice amount {value}")
        if '.' in value:
            amount_list = value.split('.')
            if len(amount_list) > 2:
                raise HTTPException(status_code=400, detail=f"Invalid invoice amount {value}")
            elif len(amount_list[1]) > 2:
                raise HTTPException(status_code=400, detail=f"Invoice amount can not accept more than two digit value {value}")
        return value

    @field_validator('verifyGSTNFlag')
    def validate_verify_gst_flag(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="Verify gst flag can not be blank")
        elif value not in [True, False]:
            raise HTTPException(status_code=400, detail=f"Verify gst flag either True or False {value}")
        return value

    @field_validator('invoiceDueDate')
    def validate_invoice_due_date(cls, value: date) -> date:
        from datetime import datetime
        if len(value) > 10:
            raise HTTPException(status_code=400, detail=f"Invoice due date can not be greater than 10 {value}")
        elif value != "":
            try:
                dd = datetime.strptime(value, "%d/%m/%Y")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invoice due date format except d/m/Y format {value}")
            return value
        else:
            return value

    @model_validator(mode='after')
    def validate_field(self):
        if self.validationRefNo != "":
            validate_string = re.search(validation_ref_no_pattern, self.validationRefNo)
            if not validate_string:
                raise HTTPException(status_code=400, detail=f"validationRefNo can not accept special character {self.validationRefNo}")
            if self.validationType.lower() not in ['einvoice', 'ewaybill', 'gstfiling']:
                raise HTTPException(status_code=400, detail=f"validation type should be eInvoice, eWayBill, gstFiling {self.validationType}")
        if self.verifyGSTNFlag:
            if self.validationType.lower() not in ['einvoice', 'ewaybill', 'gstfiling']:
                raise HTTPException(status_code=400, detail=f"validation type should be eInvoice, eWayBill, gstFiling {self.validationType}")
            if not self.validationRefNo:
                raise HTTPException(status_code=400, detail="Validation reference no can not be blank")
        if self.validationType:
            if not self.validationRefNo:
                raise HTTPException(status_code=400, detail="Validation reference no can not be blank")
        if not date_special_char_pattern.match(str(self.financeRequestDate)):
            raise HTTPException(status_code=400, detail=f"financeRequestDate can not accept special character {self.financeRequestDate}")
        if not date_special_char_pattern.match(str(self.dueDate)):
            raise HTTPException(status_code=400, detail=f"dueDate can not accept special character {self.dueDate}")
        if not special_char_pattern.match(self.fundingAmtFlag):
            raise HTTPException(status_code=400, detail=f"fundingAmtFlag can not accept special character {self.fundingAmtFlag}")
        if not special_char_pattern.match(str(self.adjustmentType)):
            raise HTTPException(status_code=400, detail=f"adjustmentType can not accept special character {self.adjustmentType}")
        if not date_special_char_pattern.match(str(self.invoiceDate)):
            raise HTTPException(status_code=400, detail=f"invoiceDate can not accept special character {self.invoiceDate}")
        if not special_char_pattern.match(str(self.disbursedFlag)):
            raise HTTPException(status_code=400, detail=f"disbursedFlag can not accept special character {self.disbursedFlag}")
        if not date_special_char_pattern.match(self.disbursedDate):
            raise HTTPException(status_code=400, detail=f"disbursedDate can not accept special character {self.disbursedDate}")

        check_decimal_precision('adjustmentAmt', str(self.adjustmentAmt))
        check_decimal_precision('financeRequestAmt', str(self.financeRequestAmt))
        check_decimal_precision('invoiceAmt', str(self.invoiceAmt))
        check_decimal_precision('disbursedAmt', str(self.disbursedAmt))
        check_decimal_precision('dueAmt', str(self.dueAmt))
        return self

    @field_validator('financeRequestAmt')
    def validate_finance_request_amount(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail=f"financeRequestAmt can not be blank {value}")
        if value == '0':
            raise HTTPException(status_code=400, detail=f"financeRequestAmt should be greater than 0 {value}")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"financeRequestAmt can not be greater than 20 {value}")
        return value

    @field_validator('financeRequestDate')
    def validate_finance_request_date(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="financeRequest Date can not be blank")
        elif len(value) > 10:
            raise HTTPException(status_code=400, detail=f"financeRequest Date can not be greater than 10 {value}")
        return value

    @field_validator('financeRequestDate')
    def validate_finance_request_dates(cls, value: date) -> date:
        from datetime import datetime
        try:
            dd = datetime.strptime(value, "%d/%m/%Y")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"date format accept d/m/Y format {value}")
        return value

    @field_validator('dueDate')
    def validate_due_date(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="dueDate can not be blank")
        elif len(value) > 10:
            raise HTTPException(status_code=400, detail=f"due Date can not be greater than 10 {value}")
        return value

    @field_validator('dueDate')
    def validate_due_dates(cls, value: date) -> date:
        from datetime import datetime
        try:
            dd = datetime.strptime(value, "%d/%m/%Y")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"date format except d/m/Y format {value}")
            # raise ValueError("date formate except d/m/Y formate")
        return value

    @field_validator('fundingAmtFlag')
    def validate_funding_amt_flag(cls, value: str):
        # if value == '':
        #     raise HTTPException(status_code=400, detail="fundingAmtFlag can not be blank")
        if len(value) > 20:
            raise HTTPException(status_code=400, detail=f"funding amt flag can not be greater than 20 {value}")
        elif value != '':
            if not value.lower() in ('full', 'partial'):
                raise HTTPException(status_code=400, detail=f"Funding amt flag can be full or partial {value}")
        return value

    @field_validator('adjustmentType')
    def validate_adjustment_type(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="adjustmentType can not be blank")
        elif len(value) > 30:
            raise HTTPException(status_code=400, detail=f"adjustmentType can not be greater than 30 {value}")
        else:
            if not value.lower() in ('none', 'advance', 'creditnote'):
                raise HTTPException(status_code=400, detail=f"adjustmentType can be none, advance or creditnote {value}")
        return value

    @field_validator('adjustmentAmt')
    def validate_adjustment_amt(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="adjustmentAmt can not be blank")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"adjustmentAmt can not be greater than 20 {value}")
        return value

    @field_validator('disbursedFlag')
    def validate_disbursed_flag(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="disbursedFlag can not be blank")
        else:
            if not value.lower() in ('full', 'partial'):
                raise HTTPException(status_code=400, detail=f"disbursedFlag can be full or partial {value}")
        return value

    @field_validator('disbursedAmt')
    def validate_disbursed_amt(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="disbursedAmt can not be blank")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"disbursedAmt can not be greater than 20 digit {value}")
        return value

    @field_validator('disbursedDate')
    def validate_disbursed_date(cls, value: date) -> date:
        if value == '':
            raise HTTPException(status_code=400, detail="disbursed date can not be blank")
        elif len(str(value)) > 10:
            raise HTTPException(status_code=400, detail=f"disbursedDate can not be greater than 10 {value}")
        elif value != '':
            from datetime import datetime
            try:
                dd = datetime.strptime(value, "%d/%m/%Y")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"date format accept d/m/Y format {value}")
        return value

    @field_validator('dueAmt')
    def validate_due_amt(cls, value: int):
        if value == '':
            raise HTTPException(status_code=400, detail="dueAmt can not be blank")
        elif len(str(value)) > 20:
            raise HTTPException(status_code=400, detail=f"dueAmt can not be greater than 20 digit {value}")
        return value


class InvoiceRequestWithFinDisbursementGroupSchema(BaseModel):
    sellerGst: str
    buyerGst: str
    groupingId: str
    ledgerAmtFlag: str
    lenderCategory: str
    lenderName: str
    lenderCode: str
    borrowerCategory: str
    ledgerData: List[LedgerRegistrationFinanceDisbursementSchema] = Field(...)
    sellerIdentifierData: Optional[List[SellerData]] = Field(None)
    buyerIdentifierData: Optional[List[BuyerData]] = Field(None)

    @field_validator('groupingId')
    def validate_grouping_id(cls, value: str):
        if not value:
            raise HTTPException(status_code=400, detail="grouping id can not blank")
        if not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"grouping id can not accept special character {value}")
        if len(value) > 30:
            raise HTTPException(status_code=400, detail=f"grouping id can not be greater than 30 {value}")
        return value

    @field_validator('sellerGst')
    def validate_seller_gst(cls, value: str):
        if value == '':
            pass
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"seller gst can not accept special character {value}")
        elif len(value) > 20:
            raise HTTPException(status_code=400, detail=f"seller gst can not greater than 20 {value}")
        elif value != "":
            seller_gst_value = ValidationCheck.validate_gst(value)
            if not seller_gst_value:
                raise HTTPException(status_code=400, detail=f"seller gst is not valid {value}")
        return value

    @field_validator('buyerGst')
    def validate_buyer_gst(cls, value: str):
        if value == '':
            pass
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"buyer gst can not accept special character {value}")
        elif len(value) > 20:
            raise HTTPException(status_code=400, detail=f"buyer gst can not greater than 20 {value}")
        elif value != "":
            buyer_gst_value = ValidationCheck.validate_gst(value)
            if not buyer_gst_value:
                raise HTTPException(status_code=400, detail=f"buyer gst is not valid {value}")
        return value

    @field_validator('ledgerAmtFlag')
    def validate_ledger_amt_flag(cls, value: str):
        if value != '':
            if not value.lower() in ('full', 'partial'):
                raise HTTPException(status_code=400, detail=f"ledgerAmtFlag can be full or partial {value}")
        return value

    @field_validator('lenderCategory')
    def validate_lender_category(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="lenderCategory can not be blank")
        if value != '':
            if len(value) > 50:
                raise HTTPException(status_code=400, detail=f"lenderCategory can not be greater than 50 {value}")
        return value

    @field_validator('lenderName')
    def validate_lender_name(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="lenderName can not be blank")
        if len(value) > 64:
            raise HTTPException(status_code=400, detail=f"lenderName can not be greater than 64 char {value}")
        # elif value != "":
        #     cleaned_string = value.isalnum()
        #     if not cleaned_string:
        #         raise HTTPException(status_code=400, detail="lender name can not have special character")
        return value

    @field_validator('lenderCode')
    def validate_lender_code(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="lenderCode can not be blank")
        if len(value) > 20:
            raise HTTPException(status_code=400, detail=f"lenderCode can not be greater than 20 {value}")
        return value

    @field_validator('borrowerCategory')
    def validate_borrower_category(cls, value: str):
        if len(value) > 50:
            raise HTTPException(status_code=400, detail=f"borrowerCategory can not be greater than 50 {value}")
        return value

    @model_validator(mode='after')
    def validate_field(self):
        import utils
        json_request_data = jsonable_encoder(self)
        validate_seller_identifier = utils.validate_seller_identifier(json_request_data)
        validate_buyer_identifier = utils.validate_buyer_identifier(json_request_data)
        invoice_date_response = utils.check_invoice_date(json_request_data)
        invoice_due_date_response = utils.check_invoice_due_date(json_request_data)
        duplicates_json_exist = utils.are_duplicates_exist(json_request_data.get('ledgerData'))
        duplicate_identifier_values = utils.check_for_duplicate_values(json_request_data)
        duplicate_pan_value = utils.check_for_duplicate_pan_values(json_request_data)
        duplicate_lei_value = utils.check_for_duplicate_lei_values(json_request_data)
        duplicate_cin_value = utils.check_for_duplicate_cin_values(json_request_data)
        duplicate_tax_no_value = utils.check_for_duplicate_tax_no_values(json_request_data)
        if not validate_seller_identifier:
            raise HTTPException(status_code=400,
                                detail="Seller identifier data can not be blank if seller gst is blank")
        if not validate_buyer_identifier:
            raise HTTPException(status_code=400, detail="Buyer identifier data can not be blank if buyer gst is blank")
        if not invoice_date_response:
            raise HTTPException(status_code=400, detail="Invoice date is greater then current date")
        if invoice_due_date_response:
            raise HTTPException(status_code=400, detail="Invoice due date should be greater than invoice date")
        if duplicates_json_exist:
            raise HTTPException(status_code=400, detail="Duplicate invoice data found")
        if duplicate_identifier_values:
            raise HTTPException(status_code=400, detail="sellerIdNo and buyerIdNo cannot be same.")
        if duplicate_pan_value:
            raise HTTPException(status_code=400, detail="sellerIdNo and buyerIdNo cannot be same.")
        if duplicate_lei_value:
            raise HTTPException(status_code=400, detail="sellerIdNo and buyerIdNo cannot be same.")
        if duplicate_cin_value:
            raise HTTPException(status_code=400, detail="sellerIdNo and buyerIdNo cannot be same.")
        if duplicate_tax_no_value:
            raise HTTPException(status_code=400, detail="sellerIdNo and buyerIdNo cannot be same.")
        if not special_char_pattern.match(str(self.ledgerAmtFlag)):
            raise HTTPException(status_code=400, detail=f"ledgerAmtFlag can not accept special character {self.ledgerAmtFlag}")
        if not special_char_pattern.match(self.lenderCategory):
            raise HTTPException(status_code=400, detail=f"lenderCategory can not accept special character {self.lenderCategory}")
        if not lender_name_pattern.match(self.lenderName):
            raise HTTPException(status_code=400, detail=f"lenderName can not accept special character {self.lenderName}")
        if not special_char_pattern.match(self.lenderCode):
            raise HTTPException(status_code=400, detail=f"lenderCode can not accept special character {self.lenderCode}")
        if not special_char_pattern.match(self.borrowerCategory):
            raise HTTPException(status_code=400, detail=f"borrowerCategory can not accept special character {self.borrowerCategory}")
        return self


class InvoiceBulkRequestWithoutCodeFinDisbursementSchema(BaseSchema):
    groupData: List[InvoiceRequestWithFinDisbursementGroupSchema] = Field(...)


# class UserConsentDetailSchema(BaseModel):
class SFTPUserDetailSchema(BaseModel):
    sftpUserBackendId: str
    requestId: str
    action: str
    userId: str
    role: str
    name: str
    emailAddress: str
    idpId: str
    idpName: str
    sftpUserId: str
    sftpUsername: str
    sftpPassword: str
    itsmUsername: str
    itsmPassword: str
    # sftpFirstname: str
    # customerName: str
    contactNumber: str
    userType: str
    project: List[str] = Field(...)
    # project: str

    @model_validator(mode='after')
    def validate_field(self):
        if self.action.strip() == '':
            raise HTTPException(status_code=400, detail="Action can not be blank")
        if not special_char_pattern.match(self.action):
            raise HTTPException(status_code=400, detail=f"action can not accept special character {self.action}")
        if len(self.action) > 10:
            raise HTTPException(status_code=400, detail=f"Action can not be greater than 10 {self.action}")
        if self.action.capitalize() not in ['Create', 'Update', 'Delete']:
            raise HTTPException(status_code=400, detail=f"Action can be Create, Update or Delete ! {self.action}")
        if self.action.capitalize() in ['Create', 'Update'] and  not self.userType:
            raise HTTPException(status_code=400, detail="userType can not be blank")
        if  self.userType :
            if len(self.userType) > 10:
                raise HTTPException(status_code=400, detail=f"userType can not be greater than 10 {self.userType}")
            if self.userType.lower() not in ['sftp', 'itsm', 'SFTP', 'Sftp', 'ITSM', 'Itsm']:
                raise HTTPException(status_code=400, detail=f"userType can be SFTP or ITSM {self.userType}")
            if self.userType.lower() == "sftp":
                print(f"userType--- {self.userType.lower()}")
                if self.action.capitalize() not in ['Create', 'Delete']:
                    raise HTTPException(status_code=400, detail=f"Action can be Create or Delete in sftp userType {self.userType}")
                if self.action.capitalize() in ['Create']:
                    if self.sftpUsername == "":
                        raise HTTPException(status_code=400, detail="sftpUsername can not be blank")
                    else:
                        sftp_name_value = ValidationCheck.validate_sftp_name_value(self.sftpUsername.strip())
                        if not sftp_name_value:
                            raise HTTPException(status_code=400, detail=f"sftpUsername is not valid {self.sftpUsername}")
                    if self.sftpPassword == "":
                        raise HTTPException(status_code=400, detail=f"sftpPassword can not be blank {self.sftpPassword}")
                    if self.sftpUserId.strip() == '':
                        raise HTTPException(status_code=400, detail="sftpUserId can not be blank")
                    if not special_char_pattern.match(self.sftpUserId):
                        raise HTTPException(status_code=400, detail=f"sftpUserId can not accept special character {self.sftpUserId}")
                    elif len(self.sftpUserId) > 20:
                        raise HTTPException(status_code=400, detail=f"sftpUserId can not be greater than 20 {self.sftpUserId}")
            if self.userType.lower() == "itsm":
                if self.action.strip() == '':
                    raise HTTPException(status_code=400, detail="Action can not be blank")
                if not special_char_pattern.match(self.action):
                    raise HTTPException(status_code=400, detail=f"action can not accept special character {self.action}")
                elif len(self.action) > 10:
                    raise HTTPException(status_code=400, detail=f"Action can not be greater than 10 {self.action}")
                elif self.action.capitalize() not in ['Create', 'Update', 'Delete']:
                    raise HTTPException(status_code=400, detail=f"Action can be Create, Update or Delete in itsm userType {self.action}")
                if self.itsmUsername.strip() == "":
                    # raise HTTPException(status_code=400, detail="itsmUsername can not be blank")
                    pass
                elif self.itsmUsername != "":
                    itsm_name_value = ValidationCheck.validate_sftp_name_value(self.itsmUsername.strip())
                    if not itsm_name_value:
                        raise HTTPException(status_code=400, detail=f"itsmUsername is not valid {self.sftpUsername}")
                if self.itsmPassword.strip() == "":
                    # raise HTTPException(status_code=400, detail="itsmPassword can not be blank")
                    pass

        if self.action.capitalize() in ['Create', 'Update']:
            if self.userId == '':
                raise HTTPException(status_code=400, detail="userId can not be blank")
            if not special_char_pattern.match(self.userId):
                raise HTTPException(status_code=400, detail=f"userId can not accept special character {self.userId}")
            elif len(self.userId) > 50:
                raise HTTPException(status_code=400, detail=f"userId can not be greater than 50 {self.userId}")

            if self.role == '':
                raise HTTPException(status_code=400, detail="role can not be blank")
            if self.role != '':
                name_value = ValidationCheck.validate_name_value(self.role.strip())
                if not name_value:
                    raise HTTPException(status_code=400, detail=f"role is not valid {self.role}")
            elif not special_char_pattern.match(self.role):
                raise HTTPException(status_code=400, detail=f"role can not accept special character {self.role}")
            if len(self.role) > 20:
                raise HTTPException(status_code=400, detail=f"role can not be greater than 20 {self.role}")
            # elif not special_char_pattern.match(self.role):
            #     raise HTTPException(status_code=400, detail="role can not accept special character")

            if self.name == '':
                raise HTTPException(status_code=400, detail="name can not be blank")
            if self.name != "":
                name_value = ValidationCheck.validate_idp_name(self.name.strip())
                if not name_value:
                    raise HTTPException(status_code=400, detail=f"name is not valid {self.name}")
            elif not special_char_pattern.match(self.name):
                raise HTTPException(status_code=400, detail=f"name can not accept special character {self.name}")
            if len(self.name) > 100:
                raise HTTPException(status_code=400, detail=f"name can not be greater than 100 {self.name}")
            # elif not special_char_pattern.match(self.name):
            #     raise HTTPException(status_code=400, detail="name can not accept special character")

            if self.emailAddress == '':
                raise HTTPException(status_code=400, detail="email address can not be blank")
            if self.emailAddress != "":
                email_value = ValidationCheck.validate_sftp_email(self.emailAddress)
                if not email_value:
                    raise HTTPException(status_code=400, detail=f"email address is not valid {self.emailAddress}")
            elif not special_char_pattern.match(self.emailAddress):
                raise HTTPException(status_code=400, detail=f"email address can not accept special character {self.emailAddress}")
            if len(self.emailAddress) > 60:
                raise HTTPException(status_code=400, detail=f"email address can not be greater than 60 {self.emailAddress}")

            if self.idpId.strip() == '':
                raise HTTPException(status_code=400, detail="idpId can not be blank")
            if not special_char_pattern.match(self.idpId):
                raise HTTPException(status_code=400, detail=f"idpId can not accept special character {self.idpId}")
            if len(self.idpId) > 20:
                raise HTTPException(status_code=400, detail=f"idpId can not be greater than 20 {self.idpId}")

            if self.idpName.strip() == '':
                raise HTTPException(status_code=400, detail="idpName can not be blank")
            if self.idpName.strip() != "":
                name_value = ValidationCheck.validate_idp_name(self.idpName.strip())
                if not name_value:
                    raise HTTPException(status_code=400, detail="idpName is not valid")
            elif len(self.idpName) > 100:
                raise HTTPException(status_code=400, detail=f"idpName can not be greater than 100 {self.idpName}")
            elif not special_char_pattern.match(self.idpName):
                raise HTTPException(status_code=400, detail=f"idpName can not accept special character {self.idpName}")

            if self.contactNumber == '':
                raise HTTPException(status_code=400, detail=f"contact number can not be blank {self.contactNumber}")
            if self.contactNumber != "":
                phone_value = ValidationCheck.validate_phone(self.contactNumber)
                if not phone_value:
                    raise HTTPException(status_code=400, detail=f"contact number is not valid {self.contactNumber}")
            elif not special_char_pattern.match(self.contactNumber):
                raise HTTPException(status_code=400, detail=f"contact number can not accept special character {self.contactNumber}")
            if len(self.contactNumber) > 10:
                raise HTTPException(status_code=400, detail=f"contact number can not be greater than 10 {self.contactNumber}")

        return self

    @field_validator('requestId')
    def validate_request_id(cls, value: str):
        if not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"request id can not accept special character {value}")
        if value.strip() == '':
            raise HTTPException(status_code=400, detail="request id can not be blank")
        elif len(value) > 30:
            raise HTTPException(status_code=400, detail=f"request id can not be greater than 30 {value}")

        return value



    # @field_validator('userId')
    # def validate_user_id(cls, value: str):
    #     if not special_char_pattern.match(value):
    #         raise HTTPException(status_code=400, detail="userId can not accept special character")
    #     if value.strip() == '':
    #         raise HTTPException(status_code=400, detail="userId can not be blank")
    #     elif len(value) > 50:
    #         raise HTTPException(status_code=400, detail="userId can not be greater than 50")
    #     return value

    # @field_validator('role')
    # def validate_role(cls, value: str):
    #     if value != "":
    #         name_value = ValidationCheck.validate_name_value(value.strip())
    #         if not name_value:
    #             raise HTTPException(status_code=400, detail="role is not valid")
    #     elif len(value) > 10:
    #         raise HTTPException(status_code=400, detail="role can not be greater than 10")
    #     elif not special_char_pattern.match(value):
    #         raise HTTPException(status_code=400, detail="role can not accept special character")
    #     return value

    # @field_validator('name')
    # def validate_name(cls, value: str):
    #     if value != "":
    #         name_value = ValidationCheck.validate_name_value(value.strip())
    #         if not name_value:
    #             raise HTTPException(status_code=400, detail="name is not valid")
    #     elif len(value) > 100:
    #         raise HTTPException(status_code=400, detail="name can not be greater than 100")
    #     elif not special_char_pattern.match(value):
    #         raise HTTPException(status_code=400, detail="name can not accept special character")
    #     return value

    # @field_validator('emailAddress')
    # def validate_email_id(cls, value: str):
    #
    #     if value != "":
    #         email_value = ValidationCheck.validate_sftp_email(value)
    #         if not email_value:
    #             raise HTTPException(status_code=400, detail="email address is not valid")
    #     elif not special_char_pattern.match(value):
    #         raise HTTPException(status_code=400, detail="email address can not accept special character")
    #     elif len(value) > 60:
    #         raise HTTPException(status_code=400, detail="email address can not be greater than 60")
    #     return value

    # @field_validator('idpId')
    # def validate_idpid(cls, value: str):
    #     if not special_char_pattern.match(value):
    #         raise HTTPException(status_code=400, detail="idpId can not accept special character")
    #     if value.strip() == '':
    #         raise HTTPException(status_code=400, detail="idpId can not be blank")
    #     elif len(value) > 20:
    #         raise HTTPException(status_code=400, detail="idpId can not be greater than 20")
    #     return value

    # @field_validator('idpName')
    # def validate_idpname(cls, value: str):
    #     if value != "":
    #         name_value = ValidationCheck.validate_idp_name(value.strip())
    #         if not name_value:
    #             raise HTTPException(status_code=400, detail="idpName is not valid")
    #     elif len(value) > 100:
    #         raise HTTPException(status_code=400, detail="idpName can not be greater than 100")
    #     elif not special_char_pattern.match(value):
    #         raise HTTPException(status_code=400, detail="idpName can not accept special character")
    #     return value



    # @field_validator('contactNumber')
    # def validate_contact_no(cls, value: str):
    #     if value != "":
    #         phone_value = ValidationCheck.validate_phone(value)
    #         if not phone_value:
    #             raise HTTPException(status_code=400, detail="contact number is not valid")
    #     elif not special_char_pattern.match(value):
    #         raise HTTPException(status_code=400, detail="contact number can not accept special character")
    #     elif len(value) > 10:
    #         raise HTTPException(status_code=400, detail="contact number can not be greater than 10")
    #     return value


class InvoiceWithCodeRequestGroupSchema(BaseModel):
    sellerCode: str
    buyerCode: str
    sellerGst: str
    buyerGst: str
    groupingId: str
    ledgerData: List[BulkInvoiceSchema] = Field(...)
    # sellerIdentifierData: Optional[List[SellerData]] = Field(None)
    # buyerIdentifierData: Optional[List[BuyerData]] = Field(None)

    @field_validator('groupingId')
    def validate_grouping_id(cls, value: str):
        if not value:
            raise HTTPException(status_code=400, detail="grouping id can not blank")
        if not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"grouping id can not accept special character {value}")
        if len(value) > 30:
            raise HTTPException(status_code=400, detail=f"grouping id can not be greater than 30 {value}")
        return value

    @field_validator('sellerCode')
    def validate_seller_code(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="seller code can not be blank")
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"seller code can not accept special character {value}")
        elif len(value) > 20:
            raise HTTPException(status_code=400, detail=f"seller code can not be greater than 20 {value}")
        return value

    @field_validator('buyerCode')
    def validate_buyer_code(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="buyer code can not be blank")
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"buyer code can not accept special character {value}")
        elif len(value) > 20:
            raise HTTPException(status_code=400, detail=f"buyer code can not be greater than 20 {value}")
        return value

    @field_validator('sellerGst')
    def validate_seller_gst(cls, value: str):
        if value != '':
            if not special_char_pattern.match(value):
                raise HTTPException(status_code=400, detail=f"seller gst can not accept special character {value}")
            elif len(value) > 20:
                raise HTTPException(status_code=400, detail=f"seller gst can not greater than 20 {value}")
            elif value != "":
                seller_gst_value = ValidationCheck.validate_gst(value)
                if not seller_gst_value:
                    raise HTTPException(status_code=400, detail=f"seller gst is not valid {value}")
        return value

    @field_validator('buyerGst')
    def validate_buyer_gst(cls, value: str):
        if value != '':
            if not special_char_pattern.match(value):
                raise HTTPException(status_code=400, detail=f"buyer gst can not accept special character {value}")
            elif len(value) > 20:
                raise HTTPException(status_code=400, detail=f"buyer gst can not greater than 20 {value}")
            elif value != "":
                buyer_gst_value = ValidationCheck.validate_gst(value)
                if not buyer_gst_value:
                    raise HTTPException(status_code=400, detail=f"buyer gst is not valid {value}")
        return value

    @model_validator(mode='after')
    def validate_field(self):
        import utils
        json_request_data = jsonable_encoder(self)
        invoice_date_response = utils.check_invoice_date(json_request_data)
        invoice_due_date_response = utils.check_invoice_due_date(json_request_data)
        duplicates_json_exist = utils.are_duplicates_exist(json_request_data.get('ledgerData'))

        duplicate_tax_no_value = utils.check_for_duplicate_tax_no_values(json_request_data)
        if not invoice_date_response:
            raise HTTPException(status_code=400, detail="Invoice date is greater then current date")
        if invoice_due_date_response:
            raise HTTPException(status_code=400, detail="Invoice due date should be greater than invoice date")
        if duplicates_json_exist:
            raise HTTPException(status_code=400, detail="Duplicate invoice data found")
        if duplicate_tax_no_value:
            raise HTTPException(status_code=400, detail="sellerIdNo and buyerIdNo cannot be same.")
        return self


class InvoiceWithCodeFinanceRequestGroupSchema(BaseModel):
    sellerCode: str
    buyerCode: str
    sellerGst: str
    buyerGst: str
    groupingId: str
    ledgerAmtFlag: str
    lenderCategory: str
    lenderName: str
    lenderCode: str
    borrowerCategory: str
    ledgerData: List[LedgerRegistrationFinanceSchema] = Field(...)

    @field_validator('groupingId')
    def validate_grouping_id(cls, value: str):
        if not value:
            raise HTTPException(status_code=400, detail="grouping id can not blank")
        if not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"grouping id can not accept special character {value}")
        if len(value) > 30:
            raise HTTPException(status_code=400, detail=f"grouping id can not be greater than 30 {value}")
        return value

    @field_validator('sellerCode')
    def validate_seller_code(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="seller code can not be blank")
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"seller code can not accept special character {value}")
        elif len(value) > 20:
            raise HTTPException(status_code=400, detail=f"seller code can not be greater than 20 {value}")
        return value

    @field_validator('buyerCode')
    def validate_buyer_code(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="buyer code can not be blank")
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"buyer code can not accept special character {value}")
        elif len(value) > 20:
            raise HTTPException(status_code=400, detail="buyer code can not be greater than 20")
        return value

    @field_validator('sellerGst')
    def validate_seller_gst(cls, value: str):
        if value == '':
            pass
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"seller gst can not accept special character {value}")
        elif len(value) > 20:
            raise HTTPException(status_code=400, detail=f"seller gst can not greater than 20 {value}")
        elif value != "":
            seller_gst_value = ValidationCheck.validate_gst(value)
            if not seller_gst_value:
                raise HTTPException(status_code=400, detail=f"seller gst is not valid {value}")
        return value

    @field_validator('buyerGst')
    def validate_buyer_gst(cls, value: str):
        if value == '':
            pass
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"buyer gst can not accept special character {value}")
        elif len(value) > 20:
            raise HTTPException(status_code=400, detail=f"buyer gst can not greater than 20 {value}")
        elif value != "":
            buyer_gst_value = ValidationCheck.validate_gst(value)
            if not buyer_gst_value:
                raise HTTPException(status_code=400, detail=f"buyer gst is not valid {value}")
        return value

    @field_validator('ledgerAmtFlag')
    def validate_ledger_amt_flag(cls, value: str):
        if value != '':
            if not value.lower() in ('full', 'partial'):
                raise HTTPException(status_code=400, detail=f"ledgerAmtFlag can be full or partial {value}")
        return value

    @field_validator('lenderCategory')
    def validate_lender_category(cls, value: str):
        # if value == '':
        #     raise HTTPException(status_code=400, detail="lenderCategory can not be blank")
        if value != '':
            if len(value) > 50:
                raise HTTPException(status_code=400, detail=f"lenderCategory can not be greater than 50 {value}")
        return value

    @field_validator('lenderName')
    def validate_lender_name(cls, value: str):
        if value != "":
            if len(value) > 64:
                raise HTTPException(status_code=400, detail=f"lenderName can not be greater than 64 char {value}")
            # cleaned_string = value.isalnum()
            # if not cleaned_string:
            #     raise HTTPException(status_code=400, detail="lender name can not have special character")
        return value

    @field_validator('lenderCode')
    def validate_lender_code(cls, value: str):
        if value != "":
            if len(value) > 20:
                raise HTTPException(status_code=400, detail=f"lenderCode can not be greater than 20 {value}")
        return value

    @field_validator('borrowerCategory')
    def validate_borrower_category(cls, value: str):
        if len(value) > 50:
            raise HTTPException(status_code=400, detail=f"borrowerCategory can not be greater than 50 {value}")
        return value

    @model_validator(mode='after')
    def validate_field(self):
        import utils
        json_request_data = jsonable_encoder(self)
        if not special_char_pattern.match(str(self.ledgerAmtFlag)):
            raise HTTPException(status_code=400, detail=f"ledgerAmtFlag can not accept special character {self.ledgerAmtFlag}")
        if not special_char_pattern.match(self.lenderCategory):
            raise HTTPException(status_code=400, detail=f"lenderCategory can not accept special character {self.lenderCategory}")
        if not lender_name_pattern.match(self.lenderName):
            raise HTTPException(status_code=400, detail=f"lenderName can not accept special character {self.lenderName}")
        if not special_char_pattern.match(self.lenderCode):
            raise HTTPException(status_code=400, detail=f"lenderCode can not accept special character {self.lenderCode}")
        if not special_char_pattern.match(self.borrowerCategory):
            raise HTTPException(status_code=400, detail=f"borrowerCategory can not accept special character {self.borrowerCategory}")

        invoice_date_response = utils.check_invoice_date(json_request_data)
        invoice_due_date_response = utils.check_invoice_due_date(json_request_data)
        duplicates_json_exist = utils.are_duplicates_exist(json_request_data.get('ledgerData'))
        duplicate_identifier_values = utils.check_for_duplicate_values(json_request_data)
        duplicate_pan_value = utils.check_for_duplicate_pan_values(json_request_data)
        duplicate_lei_value = utils.check_for_duplicate_lei_values(json_request_data)
        duplicate_cin_value = utils.check_for_duplicate_cin_values(json_request_data)
        duplicate_tax_no_value = utils.check_for_duplicate_tax_no_values(json_request_data)

        if not invoice_date_response:
            raise HTTPException(status_code=400, detail="Invoice date is greater then current date")
        if invoice_due_date_response:
            raise HTTPException(status_code=400, detail="Invoice due date should be greater than invoice date")
        if duplicates_json_exist:
            raise HTTPException(status_code=400, detail="Duplicate invoice data found")
        if duplicate_identifier_values:
            raise HTTPException(status_code=400, detail="sellerIdNo and buyerIdNo cannot be same.")
        if duplicate_pan_value:
            raise HTTPException(status_code=400, detail="sellerIdNo and buyerIdNo cannot be same.")
        if duplicate_lei_value:
            raise HTTPException(status_code=400, detail="sellerIdNo and buyerIdNo cannot be same.")
        if duplicate_cin_value:
            raise HTTPException(status_code=400, detail="sellerIdNo and buyerIdNo cannot be same.")
        if duplicate_tax_no_value:
            raise HTTPException(status_code=400, detail="sellerIdNo and buyerIdNo cannot be same.")
        return self


class InvoiceWithCodeBulkRequestSchema(BaseSchema):
    groupData: List[InvoiceWithCodeRequestGroupSchema] = Field(...)


class InvoiceWithCodeFinanceBulkRequestSchema(BaseSchema):
    groupData: List[InvoiceWithCodeFinanceRequestGroupSchema] = Field(...)


class InvoiceRequestWithCodeFinanceDisbursementSchema(BaseModel):
    groupingId: str
    sellerCode: str
    buyerCode: str
    sellerGst: str
    buyerGst: str
    ledgerAmtFlag: str
    lenderCategory: str
    lenderName: str
    lenderCode: str
    borrowerCategory: str
    ledgerData: List[LedgerRegistrationFinanceDisbursementSchema] = Field(...)

    @field_validator('groupingId')
    def validate_grouping_id(cls, value: str):
        if not value:
            raise HTTPException(status_code=400, detail="grouping id can not blank")
        if not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"grouping id can not accept special character {value}")
        if len(value) > 30:
            raise HTTPException(status_code=400, detail=f"grouping id can not be greater than 30 {value}")
        return value

    @field_validator('sellerCode')
    def validate_seller_code(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="seller code can not be blank")
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"seller code can not accept special character {value}")
        elif len(value) > 20:
            raise HTTPException(status_code=400, detail=f"seller code can not be greater than 20 {value}")
        return value

    @field_validator('buyerCode')
    def validate_buyer_code(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="buyer code can not be blank")
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"buyer code can not accept special character {value}")
        elif len(value) > 20:
            raise HTTPException(status_code=400, detail=f"buyer code can not be greater than 20 {value}")
        return value

    @field_validator('sellerGst')
    def validate_seller_gst(cls, value: str):
        if value != '':
            if not special_char_pattern.match(value):
                raise HTTPException(status_code=400, detail=f"seller gst can not accept special character {value}")
            elif len(value) > 20:
                raise HTTPException(status_code=400, detail=f"seller gst can not greater than 20 {value}")
            elif value != "":
                seller_gst_value = ValidationCheck.validate_gst(value)
                if not seller_gst_value:
                    raise HTTPException(status_code=400, detail=f"seller gst is not valid {value}")
        return value

    @field_validator('buyerGst')
    def validate_buyer_gst(cls, value: str):
        if value != '':
            if not special_char_pattern.match(value):
                raise HTTPException(status_code=400, detail=f"buyer gst can not accept special character {value}")
            elif len(value) > 20:
                raise HTTPException(status_code=400, detail=f"buyer gst can not greater than 20 {value}")
            elif value != "":
                buyer_gst_value = ValidationCheck.validate_gst(value)
                if not buyer_gst_value:
                    raise HTTPException(status_code=400, detail=f"buyer gst is not valid {value}")
        return value

    @field_validator('ledgerAmtFlag')
    def validate_ledger_amt_flag(cls, value: str):
        if value != '':
            if not value.lower() in ('full', 'partial'):
                raise HTTPException(status_code=400, detail=f"ledgerAmtFlag can be full or partial {value}")
        return value

    @field_validator('lenderCategory')
    def validate_lender_category(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="lenderCategory can not be blank")
        if value != '':
            if len(value) > 50:
                raise HTTPException(status_code=400, detail=f"lenderCategory can not be greater than 50 {value}")
        return value

    @field_validator('lenderName')
    def validate_lender_name(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="lenderName can not be blank")
        elif value != "":
            if len(value) > 64:
                raise HTTPException(status_code=400, detail=f"lenderName can not be greater than 64 char {value}")
            # cleaned_string = value.isalnum()
            # if not cleaned_string:
            #     raise HTTPException(status_code=400, detail="lender name can not have special character")
        return value

    @field_validator('lenderCode')
    def validate_lender_code(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="lenderCode can not be blank")
        elif value != "":
            if len(value) > 20:
                raise HTTPException(status_code=400, detail=f"lenderCode can not be greater than 20 {value}")
        return value

    @field_validator('borrowerCategory')
    def validate_borrower_category(cls, value: str):
        if len(value) > 50:
            raise HTTPException(status_code=400, detail=f"borrowerCategory can not be greater than 50 {value}")
        return value

    @model_validator(mode='after')
    def validate_field(self):
        import utils
        json_request_data = jsonable_encoder(self)
        invoice_date_response = utils.check_invoice_date(json_request_data)
        invoice_due_date_response = utils.check_invoice_due_date(json_request_data)
        duplicates_json_exist = utils.are_duplicates_exist(json_request_data.get('ledgerData'))

        if not invoice_date_response:
            raise HTTPException(status_code=400, detail="Invoice date is greater then current date")
        if invoice_due_date_response:
            raise HTTPException(status_code=400, detail="Invoice due date should be greater than invoice date")
        if duplicates_json_exist:
            raise HTTPException(status_code=400, detail="Duplicate invoice data found")
        if not special_char_pattern.match(str(self.ledgerAmtFlag)):
            raise HTTPException(status_code=400, detail=f"ledgerAmtFlag can not accept special character {self.ledgerAmtFlag}")
        if not special_char_pattern.match(self.lenderCategory):
            raise HTTPException(status_code=400, detail=f"lenderCategory can not accept special character {self.lenderCategory}")
        if not lender_name_pattern.match(self.lenderName):
            raise HTTPException(status_code=400, detail=f"lenderName can not accept special character {self.lenderName}")
        if not special_char_pattern.match(self.lenderCode):
            raise HTTPException(status_code=400, detail=f"lenderCode can not accept special character {self.lenderCode}")
        if not special_char_pattern.match(self.borrowerCategory):
            raise HTTPException(status_code=400, detail=f"borrowerCategory can not accept special character {self.borrowerCategory}")
        return self


class InvoiceRequestWithCodeFinanceDisbursementGroupSchema(BaseSchema):
    groupData: List[InvoiceRequestWithCodeFinanceDisbursementSchema] = Field(...)


class GetInvoiceHubMisReportSchema(BaseModel):
    requestId: str
    fromDate: str
    toDate: str
    filterType: str
    idpId: List[str]
    reportType: str

    @model_validator(mode='after')
    def validate_field(self):
        if not date_special_char_pattern.match(str(self.fromDate)):
            raise HTTPException(status_code=400, detail=f"fromDate can not accept special character {self.fromDate}")
        if not date_special_char_pattern.match(str(self.toDate)):
            raise HTTPException(status_code=400, detail=f"toDate can not accept special character {self.toDate}")
        # if not special_char_pattern.match(self.idpId):
        #     raise HTTPException(status_code=400, detail=f"idpId can not accept special character {self.idpId}")
        if not isinstance(self.idpId, list):
            raise HTTPException(status_code=400, detail=f"invalide idpId  {self.idpId}")
        if not special_char_pattern.match(self.reportType):
            raise HTTPException(status_code=400, detail=f"reportType can not accept special character {self.reportType}")
        return self

    @field_validator('requestId')
    def validate_request_id(cls, value: str):
        if not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"request id can not accept special character {value}")
        if value == '':
            raise HTTPException(status_code=400, detail=f"request id can not be blank")
        elif len(value) > 30:
            raise HTTPException(status_code=400, detail=f"request id can not be greater than 30 {value}")
        return value

    @field_validator('fromDate')
    def validate_from_date(cls, value: date) -> date:
        if value == '':
            raise HTTPException(status_code=400, detail="fromDate can not be blank")
        elif len(str(value)) > 10:
            raise HTTPException(status_code=400, detail="fromDate can not be greater than 10")
        elif value != '':
            try:
                dd = datetime.strptime(value, "%d/%m/%Y")
            except Exception as e:
                raise HTTPException(status_code=400, detail="date format accept d/m/Y format")
        return value

    @field_validator('filterType')
    def filter_type(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="filterType can not be blank")
        if not value in ('all', 'date'):
            raise HTTPException(status_code=400, detail="filterType can be all or date")
        return value

    @field_validator('toDate')
    def validate_to_date(cls, value: date) -> date:
        if value == '':
            raise HTTPException(status_code=400, detail="toDate can not be blank")
        elif len(str(value)) > 10:
            raise HTTPException(status_code=400, detail="toDate can not be greater than 10")
        elif value != '':
            try:
                dd = datetime.strptime(value, "%d/%m/%Y")
            except Exception as e:
                raise HTTPException(status_code=400, detail="toDate format accept d/m/Y format")
        return value

    @field_validator('reportType')
    def validate_report_type(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="reportType can not be blank")
        if not value in ('registration', 'finance', 'cancellation', 'disbursement', 'repayment', 'statusCheck',
                         'misHub', 'directIBDIC', 'totalBusiness', 'summary', 'UsageMISforIDP',
                         'IdpWiseDailyTrend', 'IdpWise',  'consentData', 'gspApiCalls'):
            raise HTTPException(status_code=400, detail="reportType can be registration, finance, cancellation, "
                                                        "disbursement, repayment, statusCheck, misHub, "
                                                        "directIBDIC, totalBusiness, summary, UsageMISforIDP, IdpWiseDailyTrend, IdpWise, consentData, gspApiCalls")
        return value


class GetUserMisReportSchema(BaseModel):
    requestId: str
    fromDate: str
    toDate: str
    idpId: List[str]
    # filterType: str
    reportType: str
    reportSubType: str

    @model_validator(mode='after')
    def validate_field(self):
        if not date_special_char_pattern.match(str(self.fromDate)):
            raise HTTPException(status_code=400, detail=f"fromDate can not accept special character {self.fromDate}")
        if not date_special_char_pattern.match(str(self.toDate)):
            raise HTTPException(status_code=400, detail=f"toDate can not accept special character {self.toDate}")
        # if not special_char_pattern.match(self.idpId):
        #     raise HTTPException(status_code=400, detail=f"idpId can not accept special character {self.idpId}")
        if not isinstance(self.idpId, list):
            raise HTTPException(status_code=400, detail=f"invalide idpId  {self.idpId}")
        return self

    @field_validator('requestId')
    def validate_request_id(cls, value: str):
        if not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"request id can not accept special character {value}")
        if value == '':
            raise HTTPException(status_code=400, detail=f"request id can not be blank")
        elif len(value) > 30:
            raise HTTPException(status_code=400, detail=f"request id can not be greater than 30 {value}")
        return value

    @field_validator('fromDate')
    def validate_from_date(cls, value: date) -> date:
        if value == '':
            raise HTTPException(status_code=400, detail="fromDate can not be blank")
        elif len(str(value)) > 10:
            raise HTTPException(status_code=400, detail="fromDate can not be greater than 10")
        elif value != '':
            try:
                dd = datetime.strptime(value, "%d/%m/%Y")
            except Exception as e:
                raise HTTPException(status_code=400, detail="date format accept d/m/Y format")
        return value

    @field_validator('toDate')
    def validate_to_date(cls, value: date) -> date:
        if value == '':
            raise HTTPException(status_code=400, detail="toDate can not be blank")
        elif len(str(value)) > 10:
            raise HTTPException(status_code=400, detail="toDate can not be greater than 10")
        elif value != '':
            try:
                dd = datetime.strptime(value, "%d/%m/%Y")
            except Exception as e:
                raise HTTPException(status_code=400, detail="toDate format accept d/m/Y format")
        return value

    # @field_validator('filterType')
    # def filter_type(cls, value: str):
    #     if value == '':
    #         raise HTTPException(status_code=400, detail="filterType can not be blank")
    #     if not value in ('all', 'date'):
    #         raise HTTPException(status_code=400, detail="filterType can be all or date")
    #     return value

    @field_validator('reportType')
    def validate_report_type(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="reportType can not be blank")
        if not value in ('entity_registration_data', 'invoice_data', 'api_wises_success_failure_summary'):
            raise HTTPException(status_code=400, detail="reportType can be entity_registration_data, invoice_data, "
                                                        "api_wises_success_failure_summary")
        return value

    @field_validator('reportSubType')
    def validate_report_sub_type(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="reportSubType can not be blank")
        if not value in ("entity_registered", "gstin_wise_entity_registered", "entity_id_with_identifiers",
                         "entity_ids_having_multiple_gstin", "entity_ids_without_gstin", "entity_ids_without_pan",
                         "invoices_registered", "ledger_funded", "invoices_funded_with_invoice_details",
                         "invoices_cancelled", "invoices_disbursed", "ledger_with_partial_funding", "invoices_repaid",
                         "invoices_with_partial_funding", "funding_requests_rejected_for_reason_already_funded"):
            raise HTTPException(status_code=400, detail="reportSubType can be entity_registered, "
                                                        "gstin_wise_entity_registered, entity_id_with_identifiers, "
                                                        "entity_ids_having_multiple_gstin, entity_ids_without_gstin, "
                                                        "entity_ids_without_pan, " 
                                                        "invoices_registered, ledger_funded, invoices_funded_with_invoice_details,"
                                                        "invoices_cancelled, invoices_disbursed, ledger_with_partial_funding, "
                                                        "invoices_repaid, invoices_with_partial_funding, funding_requests_rejected_for_reason_already_funded")
        return value


class GetGspUserListSchema(BaseModel):
    requestId: str

    @field_validator('requestId')
    def validate_request_id(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="request id can not be blank")
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"request id can not accept special character {value}")
        elif len(value) >= 30:
            raise HTTPException(status_code=400, detail=f"request id can not be greater than 30 {value}")
        return value


class GSPUserDeleteSchema(BaseModel):
    requestId: str
    gspUserId: str

    @field_validator('requestId')
    def validate_request_id(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="request id can not be blank")
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"request id can not accept special character {value}")
        elif len(value) >= 30:
            raise HTTPException(status_code=400, detail=f"request id can not be greater than 30 {value}")
        return value


class GSPUserDetailSchema(BaseModel):
    requestId: str
    gspUserId: str

    @field_validator('requestId')
    def validate_request_id(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="request id can not be blank")
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"request id can not accept special character {value}")
        elif len(value) >= 30:
            raise HTTPException(status_code=400, detail=f"request id can not be greater than 30 {value}")
        return value


class IdpListSchema(BaseModel):
    requestId: str

    @field_validator('requestId')
    def validate_request_id(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="request id can not be blank")
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"request id can not accept special character {value}")
        elif len(value) >= 30:
            raise HTTPException(status_code=400, detail=f"request id can not be greater than 30 {value}")
        return value


class GenerateOtpSchema(BaseModel):
    requestId: str
    mobileNo: str
    emailId: str
    otpType: str

    @field_validator('requestId')
    def validate_request_id(cls, value: str):
        if value == '':
            raise HTTPException(status_code=400, detail="request id can not be blank")
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"request id can not accept special character {value}")
        elif len(value) >= 30:
            raise HTTPException(status_code=400, detail=f"request id can not be greater than 30 {value}")
        return value

    @field_validator('otpType')
    def validate_otp_type(cls, value: str):
        # if value == '':
        #     raise HTTPException(status_code=400, detail="fundingAmtFlag can not be blank")
        if len(value) > 20:
            raise HTTPException(status_code=400, detail=f"otpType can not be greater than 20 {value}")
        elif value != '':
            if not value.lower() in ('mobile_otp', 'email_otp'):
                raise HTTPException(status_code=400, detail=f"otpType can be email_otp {value}")
        return value

    @model_validator(mode='after')
    def validate_field(self):
        if self.otpType.strip() == '':
            raise HTTPException(status_code=400, detail="otpType can not be blank")
        if self.otpType.lower() == 'mobile_otp':
            if self.mobileNo == "":
                raise HTTPException(status_code=400, detail="mobileNo can not be blank")
            else:
                phone_value = ValidationCheck.validate_phone(self.mobileNo.strip())
                if not phone_value:
                    raise HTTPException(status_code=400, detail=f"mobileNo is not valid {self.mobileNo}")
        if self.otpType.lower() == 'email_otp':
            if self.emailId == "":
                raise HTTPException(status_code=400, detail="emailId can not be blank")
            else:
                email_value = ValidationCheck.validate_email(self.emailId.strip())
                if not email_value:
                    raise HTTPException(status_code=400, detail=f"emailId is not valid {self.emailId}")
        return self

class CorporateLoginSchema(BaseModel):
    requestId: str
    emailId: str
    emailIdOtp: str
    mobileNo: str
    # mobileNoOtp: str
    panNumber: str
    referenceId: str

    @field_validator('requestId')
    def validate_request_id(cls, value: str):
        if not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"request id can not accept special character {value}")
        if value == '':
            raise HTTPException(status_code=400, detail=f"request id can not be blank")
        elif len(value) > 40:
            raise HTTPException(status_code=400, detail=f"request id can not be greater than 40 {value}")
        return value

    @field_validator('emailId')
    def validate_email(cls, value: str):
        if value.strip() == "":
            raise HTTPException(status_code=400, detail="emailId should not be blank")
        # if not special_char_pattern.match(value):
        #     raise HTTPException(status_code=400, detail=f"emailId id can not accept special character {value}")
        elif value.strip() != "":
            email_value = ValidationCheck.validate_email(value.strip())
            if not email_value:
                raise HTTPException(status_code=400, detail=f"emailId is not valid {value}")
        elif len(value) > 150:
            raise HTTPException(status_code=400, detail=f"emailId id can not be greater than 150 {value}")
        return value

    @field_validator('emailIdOtp')
    def validate_email_otp(cls, value: str):
        if value.strip() == "":
            raise HTTPException(status_code=400, detail="emailIdOtp should not be blank")
        if not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"emailIdOtp id can not accept special character {value}")
        if value.strip() != "":
            if not number_pattern.match(value):
                raise HTTPException(status_code=400, detail=f"emailIdOtp is not valid {value}")
        elif len(value) > 6:
            raise HTTPException(status_code=400, detail=f"emailIdOtp id can not be greater than 6 {value}")
        return value

    @field_validator('mobileNo')
    def validate_mobile_no(cls, value: str):
        if value.strip() == '':
            raise HTTPException(status_code=400, detail="mobileNo can not be blank")
        elif value != "":
            phone_value = ValidationCheck.validate_phone(value)
            if not phone_value:
                raise HTTPException(status_code=400, detail=f"mobileNo no is not valid {value}")
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"mobileNo can not accept special character {value}")
        return value

    @field_validator('panNumber')
    def validate_pan(cls, value: str):
        if value.strip() == '':
            raise HTTPException(status_code=400, detail="panNumber can not be blank")
        elif value != "":
            pan_no_value = ValidationCheck.validate_pan_card(value)
            if not pan_no_value:
                raise HTTPException(status_code=400, detail=f"panNumber no is not valid {value}")
        elif not special_char_pattern.match(value):
            raise HTTPException(status_code=400, detail=f"panNumber can not accept special character {value}")
        return value
