"""Persist the Polymarket 24-hour-volume rank.

Revision ID: 5e14b6c7d8f9
Revises: 8c63c4e1a4f2
Create Date: 2026-07-22 08:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5e14b6c7d8f9"
down_revision: Union[str, None] = "8c63c4e1a4f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _market_columns():
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns("markets")}


def upgrade() -> None:
    if "trend_rank" not in _market_columns():
        with op.batch_alter_table("markets") as batch_op:
            batch_op.add_column(sa.Column("trend_rank", sa.Integer(), nullable=True))


def downgrade() -> None:
    if "trend_rank" in _market_columns():
        with op.batch_alter_table("markets") as batch_op:
            batch_op.drop_column("trend_rank")
