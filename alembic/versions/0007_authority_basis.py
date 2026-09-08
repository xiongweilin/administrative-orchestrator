"""Persist governed decision roles and approval authorization basis.

Revision ID: 0007_authority_basis
Revises: 0006_authority_policy_plane
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_authority_basis"
down_revision: str | None = "0006_authority_policy_plane"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "administrative_decision",
        sa.Column("decision_role", sa.String(length=128), nullable=True),
    )
    # Kept as an application-enforced reference so SQLite migration smoke and
    # PostgreSQL share the same ALTER behavior. ApprovalSatisfaction itself is
    # durably keyed and validated before authorization is minted.
    op.add_column(
        "administrative_execution_authorization",
        sa.Column("approval_satisfaction_id", sa.Uuid(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column(
        "administrative_execution_authorization",
        "approval_satisfaction_id",
    )
    op.drop_column("administrative_decision", "decision_role")
