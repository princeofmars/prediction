import os
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "prediction_agents.db")

Base = declarative_base()
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Agent(Base):
    __tablename__ = "agents"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    model = Column(String, nullable=False)
    hashed_api_key = Column(String, nullable=False)
    accuracy_score = Column(Float, default=0.0)
    predictions_count = Column(Integer, default=0)
    
class Market(Base):
    __tablename__ = "markets"
    id = Column(Integer, primary_key=True, index=True)
    source = Column(String, nullable=False)
    question = Column(String, nullable=False)
    resolution_status = Column(String, default="OPEN")

class Prediction(Base):
    __tablename__ = "predictions"
    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False)
    market_id = Column(Integer, ForeignKey("markets.id"), nullable=False)
    probability_yes = Column(Float, nullable=False)
    confidence_score = Column(Float, nullable=False)
    reasoning = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        UniqueConstraint('agent_id', 'market_id', name='uix_agent_market_prediction'),
    )

# Note: Base.metadata.create_all is removed in favor of Alembic
