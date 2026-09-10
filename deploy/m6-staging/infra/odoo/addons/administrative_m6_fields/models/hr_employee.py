from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    x_administrative_request_ref = fields.Char(index=True)
    x_administrative_subject_ref = fields.Char(index=True)
    x_administrative_employee_ref = fields.Char()
    x_administrative_manager_principal_id = fields.Char()
    x_administrative_employment_type = fields.Char()
    x_administrative_start_date = fields.Char()
