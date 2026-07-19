import os
import hmac
import hashlib
import secrets
import bcrypt
from fastapi import FastAPI, Depends, HTTPException, Security, status, Header
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import desc, text
from db import SessionLocal, Agent, Market, Prediction
from pydantic import BaseModel, Field
from sync_polymarket import sync_markets_logic

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="Prediction Agents API")
app.mount(
    "/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static"
)

ADMIN_KEY = os.environ.get("ADMIN_KEY")
if not ADMIN_KEY:
    if os.environ.get("ENVIRONMENT", "development").lower() in {
        "prod",
        "production",
    }:
        raise RuntimeError("ADMIN_KEY must be set in production")
    ADMIN_KEY = secrets.token_urlsafe(32)
    os.environ["ADMIN_KEY"] = ADMIN_KEY
    print("\n" + "=" * 60)
    print(f"⚠️  GENERATED ADMIN_KEY: {ADMIN_KEY}")
    print("   Save this key! You will need it for the Admin UI.")
    print("=" * 60 + "\n")

api_key_header = APIKeyHeader(name="X-Admin-Key", auto_error=False)


def get_admin(api_key: str = Security(api_key_header)):
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing API Key"
        )
    if not hmac.compare_digest(api_key.encode(), ADMIN_KEY.encode()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid admin key"
        )
    return True


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def hash_api_key(api_key: str) -> str:
    """Return an indexed digest for a high-entropy API token."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def authenticate_agent(db: Session, api_key: str):
    """Authenticate new keys in O(1), with one-time bcrypt compatibility."""
    digest = hash_api_key(api_key)
    agent = db.query(Agent).filter(Agent.hashed_api_key == digest).first()
    if agent:
        return agent

    # The short-lived previous release stored bcrypt values. Preserve those
    # credentials and upgrade them to indexed digests after a successful use.
    legacy_agents = db.query(Agent).filter(Agent.hashed_api_key.like("$2%"))
    for legacy_agent in legacy_agents:
        try:
            if bcrypt.checkpw(
                api_key.encode("utf-8"), legacy_agent.hashed_api_key.encode("utf-8")
            ):
                legacy_agent.hashed_api_key = digest
                db.commit()
                return legacy_agent
        except ValueError:
            continue
    return None


class PredictionCreate(BaseModel):
    market_id: int
    probability_yes: float = Field(ge=0.0, le=1.0)
    confidence_score: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(min_length=5, max_length=3000)


class AgentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    model: str = Field(min_length=2, max_length=100)


@app.get("/", response_class=HTMLResponse)
def read_root():
    with open(os.path.join(BASE_DIR, "static", "index.html")) as f:
        return f.read()


@app.get("/admin", response_class=HTMLResponse)
def read_admin():
    with open(os.path.join(BASE_DIR, "static", "admin.html")) as f:
        return f.read()


@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "service": "prediction-agents-platform"}


@app.get("/markets")
def get_markets(db: Session = Depends(get_db)):
    return db.query(Market).filter(Market.resolution_status == "OPEN").all()


@app.post("/predictions")
def submit_prediction(
    pred: PredictionCreate,
    x_agent_key: str | None = Header(None),
    db: Session = Depends(get_db),
):
    if not x_agent_key:
        raise HTTPException(status_code=401, detail="Missing Agent API Key")

    agent = authenticate_agent(db, x_agent_key)

    if not agent:
        raise HTTPException(status_code=403, detail="Invalid Agent API Key")

    market = db.query(Market).filter(Market.id == pred.market_id).first()
    if not market:
        raise HTTPException(status_code=404, detail="Market not found")

    if market.resolution_status != "OPEN":
        raise HTTPException(status_code=400, detail="Market is already resolved")

    try:
        db_pred = Prediction(
            agent_id=agent.id,
            market_id=pred.market_id,
            probability_yes=pred.probability_yes,
            confidence_score=pred.confidence_score,
            reasoning=pred.reasoning,
        )
        db.add(db_pred)
        db.commit()
        return {"status": "success"}
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Agent has already predicted on this market"
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/leaderboard")
def get_leaderboard(db: Session = Depends(get_db)):
    agents = db.query(Agent).order_by(desc(Agent.accuracy_score)).all()
    return [
        {
            "id": a.id,
            "name": a.name,
            "model": a.model,
            "accuracy_score": a.accuracy_score,
            "predictions_count": a.predictions_count,
        }
        for a in agents
    ]


@app.get("/markets/{market_id}/predictions")
def get_market_predictions(market_id: int, db: Session = Depends(get_db)):
    market = db.query(Market).filter(Market.id == market_id).first()
    if not market:
        raise HTTPException(status_code=404, detail="Market not found")

    rows = (
        db.query(Prediction, Agent)
        .join(Agent, Agent.id == Prediction.agent_id)
        .filter(Prediction.market_id == market_id)
        .order_by(Prediction.created_at.desc())
        .all()
    )
    return [
        {
            "id": prediction.id,
            "agent_id": agent.id,
            "agent_name": agent.name,
            "model": agent.model,
            "probability_yes": prediction.probability_yes,
            "confidence_score": prediction.confidence_score,
            "reasoning": prediction.reasoning,
            "created_at": prediction.created_at,
        }
        for prediction, agent in rows
    ]


@app.post("/api/admin/agents", dependencies=[Depends(get_admin)])
def create_agent(agent: AgentCreate, db: Session = Depends(get_db)):
    try:
        exists = db.query(Agent).filter(Agent.name == agent.name).first()
        if exists:
            raise HTTPException(status_code=409, detail="Agent name already exists")

        raw_api_key = secrets.token_urlsafe(32)
        hashed_key = hash_api_key(raw_api_key)

        db_agent = Agent(name=agent.name, model=agent.model, hashed_api_key=hashed_key)
        db.add(db_agent)
        db.commit()
        return {"status": "success", "api_key": raw_api_key}
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/api/admin/agents/{agent_id}/rotate-key", dependencies=[Depends(get_admin)])
def rotate_agent_key(agent_id: int, db: Session = Depends(get_db)):
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    raw_api_key = secrets.token_urlsafe(32)
    agent.hashed_api_key = hash_api_key(raw_api_key)
    db.commit()
    return {"status": "success", "api_key": raw_api_key}


@app.post("/api/admin/sync", dependencies=[Depends(get_admin)])
def trigger_sync(db: Session = Depends(get_db)):
    try:
        result = sync_markets_logic(db)
        return {"status": "success", **result}
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Upstream sync failed: {exc}"
        ) from exc


@app.post("/api/admin/markets/{market_id}/resolve", dependencies=[Depends(get_admin)])
def resolve_market(market_id: int, status: str, db: Session = Depends(get_db)):
    if status not in ["RESOLVED_YES", "RESOLVED_NO"]:
        raise HTTPException(status_code=400, detail="Invalid status")

    try:
        market = db.query(Market).filter(Market.id == market_id).first()
        if not market:
            raise HTTPException(status_code=404, detail="Market not found")

        if market.resolution_status != "OPEN":
            raise HTTPException(status_code=400, detail="Market is already resolved")

        market.resolution_status = status

        predictions = (
            db.query(Prediction).filter(Prediction.market_id == market_id).all()
        )
        for p in predictions:
            agent = db.query(Agent).filter(Agent.id == p.agent_id).first()
            if agent:
                target = 1.0 if status == "RESOLVED_YES" else 0.0
                brier_score = (p.probability_yes - target) ** 2
                points = 1.0 - brier_score
                total_score = (agent.accuracy_score * agent.predictions_count) + points
                agent.predictions_count += 1
                agent.accuracy_score = total_score / agent.predictions_count

        db.commit()
        return {"status": "success"}
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")
