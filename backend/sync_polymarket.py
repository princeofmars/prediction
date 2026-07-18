import json
from datetime import datetime, timezone

import requests
from sqlalchemy.orm import Session

from db import Market, SessionLocal


POLYMARKET_MARKETS_URL = "https://gamma-api.polymarket.com/markets"


def _json_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _parse_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except (TypeError, ValueError):
        return None


def _yes_probability(market):
    outcomes = _json_list(market.get("outcomes"))
    prices = _json_list(market.get("outcomePrices"))
    if len(outcomes) != len(prices):
        return None

    for outcome, price in zip(outcomes, prices):
        if str(outcome).strip().lower() == "yes":
            try:
                probability = float(price)
                return probability if 0 <= probability <= 1 else None
            except (TypeError, ValueError):
                return None
    return None


def _market_records(events):
    for event in events:
        event_markets = event.get("markets") or []
        if not event_markets:
            event_markets = [event]

        for market in event_markets:
            question = market.get("question") or event.get("title")
            source_market_id = market.get("id") or event.get("id")
            if not question or source_market_id is None:
                continue

            slug = market.get("slug") or event.get("slug")
            source_url = f"https://polymarket.com/event/{slug}" if slug else None
            yield {
                "source_market_id": str(source_market_id),
                "source": "Polymarket",
                "question": question,
                "description": market.get("description") or event.get("description"),
                "resolution_rules": market.get("resolutionSource")
                or event.get("resolutionSource"),
                "end_date": _parse_datetime(
                    market.get("endDate") or event.get("endDate")
                ),
                "market_probability": _yes_probability(market),
                "source_url": source_url,
                "resolution_status": "OPEN",
            }


def sync_markets_logic(db: Session = None):
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        response = requests.get(
            POLYMARKET_MARKETS_URL,
            params={
                "limit": 25,
                "active": "true",
                "closed": "false",
                "order": "volume24hr",
                "ascending": "false",
            },
            headers={"Accept": "application/json"},
            timeout=10,
        )
        response.raise_for_status()
        events = response.json()
        if not isinstance(events, list):
            raise RuntimeError("Unexpected Polymarket response")

        added = 0
        updated = 0
        trending_ids = set()
        for values in _market_records(events):
            trending_ids.add(values["source_market_id"])
            market = (
                db.query(Market)
                .filter(Market.source_market_id == values["source_market_id"])
                .first()
            )
            if market is None:
                market = Market(**values)
                db.add(market)
                added += 1
            else:
                for field, value in values.items():
                    setattr(market, field, value)
                updated += 1

        hidden = 0
        if trending_ids:
            hidden = (
                db.query(Market)
                .filter(
                    Market.source == "Polymarket",
                    Market.resolution_status == "OPEN",
                    ~Market.source_market_id.in_(trending_ids),
                )
                .update(
                    {Market.resolution_status: "NOT_TRENDING"},
                    synchronize_session=False,
                )
            )

        db.commit()
        return {"added": added, "updated": updated, "hidden": hidden}
    except Exception as exc:
        db.rollback()
        raise RuntimeError(f"Sync failed: {exc}") from exc
    finally:
        if close_db:
            db.close()


if __name__ == "__main__":
    print(sync_markets_logic())
