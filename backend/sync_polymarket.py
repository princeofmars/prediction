import requests
from sqlalchemy.orm import Session
from db import SessionLocal, Market

def sync_markets_logic(db: Session = None):
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True
    try:
        url = "https://gamma-api.polymarket.com/events?limit=10&active=true&closed=false"
        response = requests.get(url, headers={"Accept": "application/json"}, timeout=10)
        response.raise_for_status()
        events = response.json()
        added = 0
        for event in events:
            title = event.get("title")
            if not title: continue
            exists = db.query(Market).filter(Market.question == title, Market.source == "Polymarket").first()
            if not exists:
                new_market = Market(source="Polymarket", question=title, resolution_status="OPEN")
                db.add(new_market)
                added += 1
        db.commit()
        return added
    except Exception as e:
        print(f"Sync error: {e}")
        return 0
    finally:
        if close_db:
            db.close()

if __name__ == "__main__":
    sync_markets_logic()
