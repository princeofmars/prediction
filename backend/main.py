import os
from fastapi import FastAPI, Depends, HTTPException, Security, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session
from sqlalchemy import desc
from db import SessionLocal, Agent, Market, Prediction
from pydantic import BaseModel, Field
from sync_polymarket import sync_markets_logic

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="Prediction Agents API")
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

ADMIN_KEY = os.environ.get("ADMIN_KEY", "dev-secret")
api_key_header = APIKeyHeader(name="X-Admin-Key", auto_error=False)

def get_admin(api_key: str = Security(api_key_header)):
    if api_key != ADMIN_KEY:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid admin key")
    return True

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class PredictionCreate(BaseModel):
    agent_id: int
    market_id: int
    probability_yes: float = Field(ge=0.0, le=1.0)
    confidence_score: float = Field(ge=0.0, le=1.0)
    reasoning: str

class AgentCreate(BaseModel):
    name: str
    model: str

@app.get("/", response_class=HTMLResponse)
def read_root():
    with open(os.path.join(BASE_DIR, "static", "index.html")) as f:
        return f.read()

@app.get("/admin", response_class=HTMLResponse)
def read_admin():
    with open(os.path.join(BASE_DIR, "static", "admin.html")) as f:
        return f.read()

@app.get("/markets")
def get_markets(db: Session = Depends(get_db)):
    return db.query(Market).filter(Market.resolution_status == "OPEN").all()

@app.post("/predictions")
def submit_prediction(pred: PredictionCreate, db: Session = Depends(get_db)):
    agent = db.query(Agent).filter(Agent.id == pred.agent_id).first()
    market = db.query(Market).filter(Market.id == pred.market_id).first()
    if not agent or not market:
        raise HTTPException(status_code=404, detail="Agent or Market not found")
        
    db_pred = Prediction(**pred.model_dump())
    db.add(db_pred)
    db.commit()
    return {"status": "success"}

@app.get("/leaderboard")
def get_leaderboard(db: Session = Depends(get_db)):
    return db.query(Agent).order_by(desc(Agent.accuracy_score)).all()

@app.post("/api/admin/agents", dependencies=[Depends(get_admin)])
def create_agent(agent: AgentCreate, db: Session = Depends(get_db)):
    exists = db.query(Agent).filter(Agent.name == agent.name).first()
    if exists:
        raise HTTPException(status_code=409, detail="Agent name already exists")
    db_agent = Agent(name=agent.name, model=agent.model)
    db.add(db_agent)
    db.commit()
    return {"status": "success"}

@app.post("/api/admin/sync", dependencies=[Depends(get_admin)])
def trigger_sync(db: Session = Depends(get_db)):
    added = sync_markets_logic(db)
    return {"status": "success", "added": added}

@app.post("/api/admin/markets/{market_id}/resolve", dependencies=[Depends(get_admin)])
def resolve_market(market_id: int, status: str, db: Session = Depends(get_db)):
    if status not in ["RESOLVED_YES", "RESOLVED_NO"]:
        raise HTTPException(status_code=400, detail="Invalid status")
        
    market = db.query(Market).filter(Market.id == market_id).first()
    if not market:
        raise HTTPException(status_code=404, detail="Market not found")
        
    market.resolution_status = status
    
    predictions = db.query(Prediction).filter(Prediction.market_id == market_id).all()
    for p in predictions:
        agent = db.query(Agent).filter(Agent.id == p.agent_id).first()
        if agent:
            target = 1.0 if status == "RESOLVED_YES" else 0.0
            points = 1.0 - abs(target - p.probability_yes)
            total_score = (agent.accuracy_score * agent.predictions_count) + points
            agent.predictions_count += 1
            agent.accuracy_score = total_score / agent.predictions_count
            
    db.commit()
    return {"status": "success"}
