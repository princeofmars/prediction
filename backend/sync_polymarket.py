import requests
from db import SessionLocal, Market

def sync_markets():
    # Polymarket Gamma API for active events
    url = "https://gamma-api.polymarket.com/events?limit=10&active=true&closed=false"
    print(f"Fetching live markets from {url}...")
    
    headers = {"Accept": "application/json"}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    events = response.json()
    
    db = SessionLocal()
    added = 0
    for event in events:
        title = event.get("title")
        if not title:
            continue
            
        # Avoid duplicates
        exists = db.query(Market).filter(Market.question == title, Market.source == "Polymarket").first()
        if not exists:
            new_market = Market(
                source="Polymarket",
                question=title,
                resolution_status="OPEN"
            )
            db.add(new_market)
            added += 1
            
    db.commit()
    db.close()
    print(f"✅ Successfully synced {added} new markets from Polymarket to the local database.")

if __name__ == "__main__":
    sync_markets()
