import os
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey
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
    name = Column(String, unique=True, index=True)
    model = Column(String)
    accuracy_score = Column(Float, default=0.0)
    predictions_count = Column(Integer, default=0)
    
class Market(Base):
    __tablename__ = "markets"
    id = Column(Integer, primary_key=True, index=True)
    source = Column(String)
    question = Column(String)
    resolution_status = Column(String, default="OPEN")

class Prediction(Base):
    __tablename__ = "predictions"
    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"))
    market_id = Column(Integer, ForeignKey("markets.id"))
    probability_yes = Column(Float)
    confidence_score = Column(Float)
    reasoning = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)
