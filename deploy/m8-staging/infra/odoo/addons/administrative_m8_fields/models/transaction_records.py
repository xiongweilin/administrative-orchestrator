from odoo import fields, models


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    x_administrative_transaction_request_ref = fields.Char(index=True)
    x_administrative_transaction_confirm_request_ref = fields.Char(index=True)
    x_administrative_transaction_subject_ref = fields.Char(index=True)
    x_administrative_m8_payload_json = fields.Text()


class AccountMove(models.Model):
    _inherit = "account.move"

    x_administrative_transaction_request_ref = fields.Char(index=True)
    x_administrative_transaction_confirm_request_ref = fields.Char(index=True)
    x_administrative_transaction_subject_ref = fields.Char(index=True)
    x_administrative_m8_payload_json = fields.Text()


class HrExpense(models.Model):
    _inherit = "hr.expense"

    x_administrative_transaction_request_ref = fields.Char(index=True)
    x_administrative_transaction_confirm_request_ref = fields.Char(index=True)
    x_administrative_transaction_subject_ref = fields.Char(index=True)
    x_administrative_m8_payload_json = fields.Text()
