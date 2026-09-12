# Odoo loads this module-level mapping as the manifest contract.
# ruff: noqa: B018
{
    "name": "Administrative M8 staging fields",
    "version": "19.0.1.0.0",
    "author": "administrative-orchestrator",
    "license": "LGPL-3",
    "depends": ["hr", "purchase", "account", "hr_expense"],
    "data": [
        "data/staging_users.xml",
        "data/staging_employee.xml",
        "data/staging_vendor.xml",
    ],
    "installable": True,
    "application": False,
}
