"""Add market context and indexed API-key digests.

Revision ID: 8c63c4e1a4f2
Revises: 37f5d9b726fe
Create Date: 2026-07-18 10:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "8c63c4e1a4f2"
down_revision: Union[str, Sequence[str], None] = "37f5d9b726fe"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    agent_indexes = {index["name"] for index in inspector.get_indexes("agents")}
    if "ix_agents_hashed_api_key" not in agent_indexes:
        op.create_index(
            "ix_agents_hashed_api_key",
            "agents",
            ["hashed_api_key"],
            unique=True,
        )

    market_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("markets")
    }
    additions = {
        "source_market_id": sa.Column("source_market_id", sa.String(), nullable=True),
        "description": sa.Column("description", sa.String(), nullable=True),
        "resolution_rules": sa.Column("resolution_rules", sa.String(), nullable=True),
        "end_date": sa.Column("end_date", sa.DateTime(), nullable=True),
        "market_probability": sa.Column(
            "market_probability", sa.Float(), nullable=True
        ),
        "source_url": sa.Column("source_url", sa.String(), nullable=True),
        "updated_at": sa.Column("updated_at", sa.DateTime(), nullable=True),
    }
    for name, column in additions.items():
        if name not in market_columns:
            op.add_column("markets", column)

    market_indexes = {
        index["name"] for index in sa.inspect(bind).get_indexes("markets")
    }
    if "ix_markets_source_market_id" not in market_indexes:
        op.create_index(
            "ix_markets_source_market_id",
            "markets",
            ["source_market_id"],
            unique=True,
        )

    market_checks = {
        check.get("name") for check in sa.inspect(bind).get_check_constraints("markets")
    }
    if "ck_market_probability_bounds" not in market_checks:
        with op.batch_alter_table("markets") as batch_op:
            batch_op.create_check_constraint(
                "ck_market_probability_bounds",
                "market_probability IS NULL OR "
                "(market_probability >= 0 AND market_probability <= 1)",
            )

    prediction_checks = {
        check.get("name")
        for check in sa.inspect(bind).get_check_constraints("predictions")
    }
    missing_probability = "ck_prediction_probability_bounds" not in prediction_checks
    missing_confidence = "ck_prediction_confidence_bounds" not in prediction_checks
    if missing_probability or missing_confidence:
        with op.batch_alter_table("predictions") as batch_op:
            if missing_probability:
                batch_op.create_check_constraint(
                    "ck_prediction_probability_bounds",
                    "probability_yes >= 0 AND probability_yes <= 1",
                )
            if missing_confidence:
                batch_op.create_check_constraint(
                    "ck_prediction_confidence_bounds",
                    "confidence_score >= 0 AND confidence_score <= 1",
                )


def downgrade() -> None:
    # Compatibility migration: preserving data is safer than attempting to
    # reconstruct any of the predecessor schemas.
    pass
