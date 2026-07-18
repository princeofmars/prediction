"""Create the initial schema or adopt the pre-Alembic schema.

Revision ID: 37f5d9b726fe
Revises:
Create Date: 2026-07-18 09:02:32.048556
"""

import hashlib
import secrets
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "37f5d9b726fe"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


MARKET_CONTEXT_COLUMNS = {
    "source_market_id": sa.Column("source_market_id", sa.String(), nullable=True),
    "description": sa.Column("description", sa.String(), nullable=True),
    "resolution_rules": sa.Column("resolution_rules", sa.String(), nullable=True),
    "end_date": sa.Column("end_date", sa.DateTime(), nullable=True),
    "market_probability": sa.Column("market_probability", sa.Float(), nullable=True),
    "source_url": sa.Column("source_url", sa.String(), nullable=True),
    "updated_at": sa.Column("updated_at", sa.DateTime(), nullable=True),
}


def _columns(bind, table_name):
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def _indexes(bind, table_name):
    return {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}


def _checks(bind, table_name):
    return {
        check.get("name")
        for check in sa.inspect(bind).get_check_constraints(table_name)
    }


def _adopt_legacy_agents(bind):
    columns = _columns(bind, "agents")
    if "hashed_api_key" not in columns:
        op.add_column("agents", sa.Column("hashed_api_key", sa.String(), nullable=True))
        if "api_key" in columns:
            rows = bind.execute(sa.text("SELECT id, api_key FROM agents")).mappings()
            for row in rows:
                raw_key = (
                    row["api_key"] or f"revoked:{row['id']}:{secrets.token_hex(16)}"
                )
                digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
                bind.execute(
                    sa.text(
                        "UPDATE agents SET hashed_api_key = :digest WHERE id = :agent_id"
                    ),
                    {"digest": digest, "agent_id": row["id"]},
                )
        else:
            rows = bind.execute(sa.text("SELECT id FROM agents")).mappings()
            for row in rows:
                digest = hashlib.sha256(
                    f"revoked:{row['id']}:{secrets.token_hex(16)}".encode("utf-8")
                ).hexdigest()
                bind.execute(
                    sa.text(
                        "UPDATE agents SET hashed_api_key = :digest WHERE id = :agent_id"
                    ),
                    {"digest": digest, "agent_id": row["id"]},
                )

        with op.batch_alter_table("agents") as batch_op:
            if "api_key" in columns:
                batch_op.drop_column("api_key")
            batch_op.alter_column(
                "hashed_api_key", existing_type=sa.String(), nullable=False
            )

    if "ix_agents_hashed_api_key" not in _indexes(bind, "agents"):
        op.create_index(
            "ix_agents_hashed_api_key",
            "agents",
            ["hashed_api_key"],
            unique=True,
        )


def _adopt_legacy_markets(bind):
    columns = _columns(bind, "markets")
    for name, column in MARKET_CONTEXT_COLUMNS.items():
        if name not in columns:
            op.add_column("markets", column)

    if "ix_markets_source_market_id" not in _indexes(bind, "markets"):
        op.create_index(
            "ix_markets_source_market_id",
            "markets",
            ["source_market_id"],
            unique=True,
        )

    if "ck_market_probability_bounds" not in _checks(bind, "markets"):
        with op.batch_alter_table("markets") as batch_op:
            batch_op.create_check_constraint(
                "ck_market_probability_bounds",
                "market_probability IS NULL OR "
                "(market_probability >= 0 AND market_probability <= 1)",
            )


def _adopt_legacy_predictions(bind):
    checks = _checks(bind, "predictions")
    missing_probability = "ck_prediction_probability_bounds" not in checks
    missing_confidence = "ck_prediction_confidence_bounds" not in checks
    if not missing_probability and not missing_confidence:
        return

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


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "agents" not in tables:
        op.create_table(
            "agents",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("model", sa.String(), nullable=False),
            sa.Column("hashed_api_key", sa.String(), nullable=False),
            sa.Column("accuracy_score", sa.Float(), nullable=True),
            sa.Column("predictions_count", sa.Integer(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_agents_id", "agents", ["id"], unique=False)
        op.create_index("ix_agents_name", "agents", ["name"], unique=True)
        op.create_index(
            "ix_agents_hashed_api_key",
            "agents",
            ["hashed_api_key"],
            unique=True,
        )
    else:
        _adopt_legacy_agents(bind)

    if "markets" not in tables:
        op.create_table(
            "markets",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("source_market_id", sa.String(), nullable=True),
            sa.Column("source", sa.String(), nullable=False),
            sa.Column("question", sa.String(), nullable=False),
            sa.Column("description", sa.String(), nullable=True),
            sa.Column("resolution_rules", sa.String(), nullable=True),
            sa.Column("end_date", sa.DateTime(), nullable=True),
            sa.Column("market_probability", sa.Float(), nullable=True),
            sa.Column("source_url", sa.String(), nullable=True),
            sa.Column("resolution_status", sa.String(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.CheckConstraint(
                "market_probability IS NULL OR "
                "(market_probability >= 0 AND market_probability <= 1)",
                name="ck_market_probability_bounds",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_markets_id", "markets", ["id"], unique=False)
        op.create_index(
            "ix_markets_source_market_id",
            "markets",
            ["source_market_id"],
            unique=True,
        )
    else:
        _adopt_legacy_markets(bind)

    if "predictions" not in tables:
        op.create_table(
            "predictions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("agent_id", sa.Integer(), nullable=False),
            sa.Column("market_id", sa.Integer(), nullable=False),
            sa.Column("probability_yes", sa.Float(), nullable=False),
            sa.Column("confidence_score", sa.Float(), nullable=False),
            sa.Column("reasoning", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.CheckConstraint(
                "probability_yes >= 0 AND probability_yes <= 1",
                name="ck_prediction_probability_bounds",
            ),
            sa.CheckConstraint(
                "confidence_score >= 0 AND confidence_score <= 1",
                name="ck_prediction_confidence_bounds",
            ),
            sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
            sa.ForeignKeyConstraint(["market_id"], ["markets.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "agent_id", "market_id", name="uix_agent_market_prediction"
            ),
        )
        op.create_index("ix_predictions_id", "predictions", ["id"], unique=False)
    else:
        _adopt_legacy_predictions(bind)


def downgrade() -> None:
    op.drop_table("predictions")
    op.drop_table("markets")
    op.drop_table("agents")
