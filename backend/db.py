import os
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "prediction_agents.db")
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DB_PATH}")

Base = declarative_base()
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Agent(Base):
    __tablename__ = "agents"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    model = Column(String, nullable=False)
    # API keys are high-entropy tokens. Storing a SHA-256 digest permits an
    # indexed lookup without retaining the credential itself.
    hashed_api_key = Column(String, unique=True, index=True, nullable=False)
    accuracy_score = Column(Float, default=0.0)
    predictions_count = Column(Integer, default=0)


class Market(Base):
    __tablename__ = "markets"
    id = Column(Integer, primary_key=True, index=True)
    source_market_id = Column(String, unique=True, index=True, nullable=True)
    source = Column(String, nullable=False)
    question = Column(String, nullable=False)
    description = Column(String, nullable=True)
    resolution_rules = Column(String, nullable=True)
    end_date = Column(DateTime, nullable=True)
    market_probability = Column(Float, nullable=True)
    source_url = Column(String, nullable=True)
    resolution_status = Column(String, default="OPEN")
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        CheckConstraint(
            "market_probability IS NULL OR (market_probability >= 0 AND market_probability <= 1)",
            name="ck_market_probability_bounds",
        ),
    )


class Prediction(Base):
    __tablename__ = "predictions"
    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False)
    market_id = Column(Integer, ForeignKey("markets.id"), nullable=False)
    probability_yes = Column(Float, nullable=False)
    confidence_score = Column(Float, nullable=False)
    reasoning = Column(String, nullable=False)
    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        UniqueConstraint("agent_id", "market_id", name="uix_agent_market_prediction"),
        CheckConstraint(
            "probability_yes >= 0 AND probability_yes <= 1",
            name="ck_prediction_probability_bounds",
        ),
        CheckConstraint(
            "confidence_score >= 0 AND confidence_score <= 1",
            name="ck_prediction_confidence_bounds",
        ),
    )
