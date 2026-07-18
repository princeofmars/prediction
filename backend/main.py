from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc
from db import SessionLocal, Agent, Market, Prediction
from pydantic import BaseModel

app = FastAPI(title="Prediction Agents API")

# Mount the static directory to serve the UI
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
def read_root():
    with open("static/index.html") as f:
        return f.read()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class PredictionCreate(BaseModel):
    agent_id: int
    market_id: int
    probability_yes: float
    confidence_score: float
    reasoning: str

@app.get("/markets")
def get_markets(db: Session = Depends(get_db)):
    return db.query(Market).filter(Market.resolution_status == "OPEN").all()

@app.post("/predictions")
def submit_prediction(pred: PredictionCreate, db: Session = Depends(get_db)):
    db_pred = Prediction(**pred.model_dump())
    db.add(db_pred)
    db.commit()
    return {"status": "success"}

@app.get("/leaderboard")
def get_leaderboard(db: Session = Depends(get_db)):
    return db.query(Agent).order_by(desc(Agent.accuracy_score)).all()
