import hashlib
import logging
import datetime
from schema import InvoiceStatus

from fastapi import HTTPException

from sqlalchemy import Enum, Boolean, Column, ForeignKey, Integer, String, DateTime, Table, UniqueConstraint, Numeric
from sqlalchemy.orm import relationship, Mapped
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func, false, true, text
from database import Base, get_db

logger = logging.getLogger(__name__)
db = get_db()


class BaseModel(Base):
    __abstract__ = True

    # time_created = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(
        DateTime(timezone=True),
        server_default=text("(now() AT TIME ZONE 'Asia/Kolkata')"),
        nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=text("(now() AT TIME ZONE 'Asia/Kolkata')"),
        nullable=False
    )
    # time_updated = Column(DateTime(timezone=True), onupdate=func.now())
    is_active = Column(Boolean, server_default=true(), default=True)
    extra_data = Column(JSONB, default={})


class MerchantDetails(BaseModel):
    __tablename__ = "merchant_details"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=False, index=False)
    merchant_key = Column(String)
    merchant_secret = Column(String)
    is_active = Column(Boolean, default=True)
    username = Column(String, unique=True)
    password = Column(String)
    webhook_endpoint = Column(String, index=True)
    hub_id = Column(Integer, ForeignKey("hub.id"))
    unique_id = Column(String, unique=True)


class User(BaseModel):
    __tablename__ = "user"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=False, index=False)
    email = Column(String)
    password = Column(String)
    is_active = Column(Boolean, default=True)


invoice_ledger_association = Table(
    "invoice_ledger_association",
    Base.metadata,
    Column("invoice_id", Integer, ForeignKey("invoice.id")),
    Column("ledger_id", Integer, ForeignKey("ledger.id")),
)

old_invoice_ledger_association = Table(
    "old_invoice_ledger_association",
    Base.metadata,
    Column("invoice_id", Integer, ForeignKey("old_invoice.id")),
    Column("ledger_id", Integer, ForeignKey("ledger.id")),
)


class Ledger(BaseModel):
    __tablename__ = "ledger"

    id = Column(Integer, primary_key=True, index=True)
    merchant_id = Column(Integer, ForeignKey("merchant_details.id"))
    ledger_id = Column(String)
    invoice_count = Column(Integer)
    ledger_hash = Column(String)
    status = Column(String)
    invoice = relationship("Invoice", secondary=invoice_ledger_association, back_populates="ledger")
    old_invoice = relationship("OldInvoice", secondary=old_invoice_ledger_association, back_populates="ledger")

    def __str__(self):
        return f"{self.id}"


class Invoice(BaseModel):
    __tablename__ = "invoice"

    id = Column(Integer, primary_key=True, index=True)
    invoice_no = Column(String)
    invoice_date = Column(DateTime(timezone=True))
    invoice_due_date = Column(DateTime(timezone=True), nullable=True)
    invoice_amt = Column(Numeric(precision=10, scale=2))
    # buyer_gst = Column(String)
    # seller_gst = Column(String)
    invoice_hash = Column(String)
    funded_amt = Column(String)
    gst_status = Column(Boolean, default=False)
    fund_status = Column(Boolean, default=False)
    financial_year = Column(String)
    status = Column(String)
    ledger = relationship("Ledger", secondary=invoice_ledger_association, back_populates="invoice")

    # def __str__(self):
    #     return f"{self.id}"


class OldInvoice(BaseModel):
    __tablename__ = "old_invoice"

    id = Column(Integer, primary_key=True, index=True)
    invoice_no = Column(String)
    invoice_date = Column(DateTime(timezone=True))
    invoice_due_date = Column(DateTime(timezone=True))
    invoice_amt = Column(Numeric(precision=10, scale=2))
    invoice_hash = Column(String)
    funded_amt = Column(String)
    gst_status = Column(Boolean, default=False)
    fund_status = Column(Boolean, default=False)
    financial_year = Column(String)
    status = Column(String)
    ledger = relationship("Ledger", secondary=old_invoice_ledger_association, back_populates="old_invoice")


class InvoiceEncryptedData(BaseModel):
    __tablename__ = "invoice_encrypted_data"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoice.id"))
    old_invoice_id = Column(Integer, ForeignKey("old_invoice.id"))
    invoice_has_key = Column(String, index=True)
    status = Column(Boolean, default=False)


class APIRequestLog(BaseModel):
    __tablename__ = "api_request_log"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String, unique=True)
    api_url = Column(String)
    request_data = Column(JSONB, default={})
    response_data = Column(JSONB, default={})
    merchant_id = Column(String, index=True)

    @staticmethod
    def create(**data):
        session = db
        request_log = APIRequestLog(
            request_id=data.get("requestId"),
            api_url=data.get("apiURL"),
            request_data=data.get("requestData")
        )
        session.add(request_log)
        session.commit()
        session.refresh()
        return request_log


# class TestTable(BaseModel):
#     __tablename__ = "test_table"
#
#     id = Column(Integer, primary_key=True, index=True)
#     name = Column(String)
#     test_date = Column(DateTime(timezone=True))


# book_author_association = Table(
#     "book_author_association",
#     Base.metadata,
#     Column("book_id", Integer, ForeignKey("books.id")),
#     Column("author_id", Integer, ForeignKey("authors.id")),
# )


# class Author(Base):
#     __tablename__ = "authors"
#
#     id = Column(Integer, primary_key=True, index=True)
#     ledger_id = Column(String)
#     invoice_count = Column(Integer)
#     ledger_hash = Column(String)
#     extra_data = Column(JSONB, default={})
#     books = relationship("Book", secondary=book_author_association, back_populates="authors")
#
#     def __str__(self):
#         return f"{self.id}"


# class Book(Base):
#     __tablename__ = "books"
#
#     id = Column(Integer, primary_key=True, index=True)
#     invoice_no = Column(String)
#     invoice_date = Column(DateTime(timezone=True))
#     invoice_amt = Column(String)
#     buyer_gst = Column(String)
#     seller_gst = Column(String)
#     invoice_hash = Column(String)
#     funded_amt = Column(String)
#     gst_status = Column(String)
#     fund_status = Column(Boolean, default=False)
#     extra_data = Column(JSONB, default={})
#     authors = relationship("Author", secondary=book_author_association, back_populates="books")
#
#     # def __str__(self):
#     #     return f"{self.id}"


class Entity(BaseModel):
    __tablename__ = "entity"

    id = Column(Integer, primary_key=True, index=True)
    merchant_id = Column(Integer, ForeignKey("merchant_details.id"))
    # entity_code = Column(String)


class EntityCombination(BaseModel):
    __tablename__ = "entity_combination"

    id = Column(Integer, primary_key=True, index=True)
    merchant_id = Column(Integer, ForeignKey("merchant_details.id"))
    entity_code = Column(String)
    entity_id = Column(Integer, ForeignKey("entity.id"))


class EntityIdentifierLine(BaseModel):
    __tablename__ = "entity_identifier_line"

    id = Column(Integer, primary_key=True, index=True)
    entity_id = Column(Integer, ForeignKey("entity.id"))
    entity_id_type = Column(String)
    entity_id_no = Column(String)
    entity_id_name = Column(String)
    ifsc = Column(String)


class PostProcessingRequest(BaseModel):
    __tablename__ = "post_processing_request"

    id = Column(Integer, primary_key=True, index=True)
    request_extra_data = Column(JSONB, default=[])
    api_response = Column(JSONB, default=[])
    webhook_response = Column(JSONB, default=[])
    merchant_id = Column(String, index=True)
    type = Column(String)


class LenderDetails(BaseModel):
    __tablename__ = "lender_details"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    code = Column(String)
    category = Column(String)
    # Unique constraint on column1 and column2
    __table_args__ = (UniqueConstraint('name', 'code'),)


# lander_invoice_association = Table(
#     "lander_invoice_association",
#     Base.metadata,
#     Column("invoice_id", Integer, ForeignKey("invoice.id")),
#     Column("lander_id", Integer, ForeignKey("lander_details.id")),
# )
#
class LenderInvoiceAssociation(BaseModel):
    __tablename__ = "lender_invoice_association"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoice.id"))
    old_invoice_id = Column(Integer, ForeignKey("old_invoice.id"))
    lender_id = Column(Integer, ForeignKey("lender_details.id"))

    # Unique constraint on column1 and column2
    __table_args__ = (UniqueConstraint('invoice_id', 'lender_id', 'old_invoice_id'),)


class Hub(BaseModel):
    __tablename__ = "hub"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    unique_id = Column(String)
    hub_key = Column(String)
    hub_secret = Column(String)


class HubRequestLog(BaseModel):
    __tablename__ = "hub_request_log"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String, unique=True)
    api_url = Column(String)
    request_data = Column(JSONB, default={})
    response_data = Column(JSONB, default={})
    hub_id = Column(String, index=True)
    merchant_id = Column(String, index=True)

    @staticmethod
    def create(**data):
        session = db
        request_log = HubRequestLog(
            request_id=data.get("requestId"),
            api_url=data.get("apiURL"),
            request_data=data.get("requestData")
        )
        session.add(request_log)
        session.commit()
        session.refresh()
        return request_log


class DisbursedHistory(BaseModel):
    __tablename__ = "disbursed_history"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoice.id"))
    old_invoice_id = Column(Integer, ForeignKey("old_invoice.id"))


class RepaymentHistory(BaseModel):
    __tablename__ = "repayment_history"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoice.id"))
    old_invoice_id = Column(Integer, ForeignKey("old_invoice.id"))


class BulkAPIRequestLog(BaseModel):
    __tablename__ = "bulk_api_request_log"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String, unique=True)
    api_url = Column(String)
    request_data = Column(JSONB, default={})
    response_data = Column(JSONB, default={})
    webhook_response = Column(JSONB, default=[])
    merchant_id = Column(String, index=True)

    # @staticmethod
    # def create(**data):
    #     session = db
    #     request_log = APIRequestLog(
    #         request_id=data.get("requestId"),
    #         api_url=data.get("apiURL"),
    #         request_data=data.get("requestData")
    #     )
    #     session.add(request_log)
    #     session.commit()
    #     session.refresh()
    #     return request_log


class SFTPUserInfo(BaseModel):
    __tablename__ = "sftp_user_info"

    id = Column(Integer, primary_key=True, index=True)
    # action = Column(String)
    user_id = Column(String)
    role = Column(String)
    name = Column(String)
    email_address = Column(String, unique=False)

    @staticmethod
    def get_user_email(user_id):

        sftp_user_obj = db.query(
            self.SFTPUserInfo
        ).filter(
            models.SFTPUserInfo.extra_data.contains({"userType": "SFTP", "SFTPUsername":user_id.strip()})
        ).first()
        return sftp_user_obj and sftp_user_obj.email_address or "arpit.bansal@citycash.in"


class GSPAPIRequestLog(BaseModel):
    __tablename__ = "gsp_api_request_log"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String, unique=True)
    api_url = Column(String)
    request_data = Column(JSONB, default={})
    response_data = Column(JSONB, default={})
    type = Column(String)


class VayanaTaskHistory(BaseModel):
    __tablename__ = "vayana_task_history"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String)
    user_id = Column(String)
    task_id_status = Column(String)
    download_status = Column(String)


# class FinancingApiViewModel(BaseModel):
#     __tablename__ = "financing_api_view"
#
#     id: int = Column(Integer, primary_key=True)
#     category: Mapped[str]  # Update the type annotation
#
#     __allow_unmapped__ = True  # Allow unmapped attributes
#     # category: str
#     # idp_name: str
#     # idp_code: str
#     # api_call_date: str
#     # period: str
#     # of_request: str
#     # repeat_per: str
#     # duplicate_per: str
#     # amount_of_request: str
#     # invoices_request: str
#     # per_of_invoices_ok: str
#     # amount_ok_for_funding: str
#     # per_funding_value: str


class Role(BaseModel):
    __tablename__ = "role"

    id = Column(Integer, primary_key=True, index=True)
    role_name = Column(String, unique=True)


class CorporateUserDetails(BaseModel):
    __tablename__ = "corporate_user"

    id = Column(Integer, primary_key=True, index=True)
    # gstin = Column(String, unique=True)
    email_id = Column(String)
    mobile_no = Column(String)
    pan_number = Column(String)
    role = Column(Integer, ForeignKey("role.id"))


class GSPUserDetails(BaseModel):
    __tablename__ = "gsp_user_details"

    id = Column(Integer, primary_key=True, index=True)
    gstin = Column(String, unique=True)
    gsp = Column(String)
    username = Column(String)
    password = Column(String)
    name = Column(String)
    pan = Column(String)
    email = Column(String)
    mobile_number = Column(String)
    created_by_id = Column(Integer, ForeignKey("corporate_user.id"))


class UserAuth(BaseModel):
    __tablename__ = "corporate_user_auth_token"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String)
    user_token = Column(String)
