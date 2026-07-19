import hashlib
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import bcrypt
import pytest


TEST_DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TEST_DB_FILE.close()
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_FILE.name}"
os.environ["ADMIN_KEY"] = "test-admin-key"

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from db import Agent, Base, Market, SessionLocal, engine  # noqa: E402
from main import ADMIN_KEY, app  # noqa: E402
from runner import build_prompt, validate_forecast  # noqa: E402
from sync_polymarket import _market_records, sync_markets_logic  # noqa: E402


client = TestClient(app)
ADMIN_HEADERS = {"X-Admin-Key": ADMIN_KEY}


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def create_agent(name="Test Agent", model="gpt-4o-mini"):
    response = client.post(
        "/api/admin/agents",
        headers=ADMIN_HEADERS,
        json={"name": name, "model": model},
    )
    assert response.status_code == 200
    return response.json()["api_key"]


def create_market(question="Will the test pass?"):
    with SessionLocal() as db:
        market = Market(
            source_market_id=f"test-{question}",
            source="Test",
            question=question,
            description="A deterministic test market",
            resolution_status="OPEN",
        )
        db.add(market)
        db.commit()
        db.refresh(market)
        return market.id


def prediction_payload(market_id, probability=0.75):
    return {
        "market_id": market_id,
        "probability_yes": probability,
        "confidence_score": 0.9,
        "reasoning": "The test evidence supports this forecast.",
    }


def test_health_endpoint_checks_database():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "prediction-agents-platform",
    }


def test_public_page_explains_agent_onboarding_and_consensus_unlock():
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert "AI agents: predict first, then compare" in html
    assert "Self-onboard and save the one-time API key." in html
    assert "Unlock peer forecasts and consensus." in html
    assert 'href="/agents/onboarding"' in html
    assert "Agent forecasts unlock only after your agent submits" in html
    assert "market.predictions" not in html


def test_public_page_shows_service_health_status():
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert 'role="status"' in html
    assert 'aria-live="polite"' in html
    assert 'healthStatus: "Checking..."' in html
    assert "async fetchHealth()" in html
    assert 'fetch("/health")' in html
    assert 'this.healthStatus = "Online"' in html
    assert 'this.healthStatus = "Unavailable"' in html


def test_public_page_labels_trending_markets():
    response = client.get("/")
    assert response.status_code == 200
    assert "Trending Markets (24h volume)" in response.text


def test_public_page_has_trending_market_search():
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert 'aria-label="Search trending markets"' in html
    assert 'x-for="market in filteredMarkets"' in html
    assert "No trending markets match your search." in html
    assert "get filteredMarkets()" in html


def test_public_leaderboard_explains_forecast_score():
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert 'id="forecast-score-help"' in html
    assert 'role="note"' in html
    assert 'aria-describedby="forecast-score-help"' in html
    assert "Forecast score is 1 minus mean Brier score." in html
    assert "Higher is better" in html


def test_public_leaderboard_shows_forecast_counts():
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert "agent.predictions_count || 0" in html
    assert "' forecast'" in html
    assert "' forecasts'" in html


def test_public_page_can_reset_market_view():
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert 'aria-label="Reset market search, sorting, and favorite filter"' in html
    assert '@click="resetMarketView"' in html
    assert "resetMarketView()" in html
    assert 'this.searchQuery = ""' in html
    assert 'this.sortMode = "trending"' in html
    assert "this.showFavoritesOnly = false" in html


def test_public_page_supports_local_market_favorites():
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert 'aria-label="Show favorite markets only"' in html
    assert '@click="toggleFavorite(market.id)"' in html
    assert ':aria-pressed="isFavorite(market.id)"' in html
    assert '"favoriteMarketIds"' in html
    assert 'localStorage.setItem(' in html
    assert "showFavoritesOnly: false" in html


def test_public_page_shows_market_time_remaining():
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert "formatTimeRemaining(market.end_date)" in html
    assert "formatTimeRemaining(endDate)" in html
    assert 'return "closing"' in html
    assert "h left" in html
    assert "d left" in html


def test_public_page_has_accessible_probability_meter():
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert 'role="progressbar"' in html
    assert 'aria-valuemin="0"' in html
    assert 'aria-valuemax="100"' in html
    assert ':aria-valuenow="Math.round(market.market_probability * 100)"' in html
    assert "Crowd YES probability " in html
    assert "Math.round((1 - market.market_probability) * 100)" in html


def test_public_page_can_sort_trending_markets():
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert 'aria-label="Sort trending markets"' in html
    assert '<option value="trending">Trending order</option>' in html
    assert '<option value="probability-desc">Highest YES probability</option>' in html
    assert '<option value="probability-asc">Lowest YES probability</option>' in html
    assert '<option value="closing-soon">Closing soon</option>' in html
    assert 'sortMode: "trending"' in html


def test_public_page_distinguishes_leaderboard_loading_and_empty_states():
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert "leaderboardLoading: true" in html
    assert "leaderboardLoadFailed: false" in html
    assert "this.leaderboardLoading = true" in html
    assert "this.leaderboardLoading = false" in html
    assert "this.leaderboardLoadFailed = true" in html
    assert 'x-show="leaderboardLoading"' in html
    assert "Loading leaderboard..." in html
    assert "No ranked agents yet." in html
    assert "Scores appear after agents make forecasts and markets resolve." in html
    assert "No agents deployed yet." not in html


def test_public_page_distinguishes_market_loading_and_empty_states():
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert "marketsLoading: true" in html
    assert "marketsLoadFailed: false" in html
    assert "this.marketsLoading = true" in html
    assert "this.marketsLoading = false" in html
    assert "this.marketsLoadFailed = true" in html
    assert 'x-show="marketsLoading"' in html
    assert "Loading trending markets..." in html
    assert "No trending markets are available yet." in html
    assert 'href="/admin"' in html
    assert "Open admin to sync Polymarket" in html
    assert "Loading markets or no markets available..." not in html


def test_public_page_shows_data_loading_errors_with_retry():
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert 'role="alert"' in html
    assert 'aria-live="assertive"' in html
    assert "dataErrors: []" in html
    assert "this.dataErrors = []" in html
    assert 'Trending markets could not be loaded.' in html
    assert 'Leaderboard could not be loaded.' in html
    assert 'x-text="dataErrors.join(\' \')"' in html
    assert '@click="refreshData"' in html
    assert "Try again" in html


def test_public_page_has_manual_data_refresh():
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert 'aria-label="Refresh market and leaderboard data"' in html
    assert '@click="refreshData"' in html
    assert "refreshing ? 'Refreshing...' : 'Refresh data'" in html
    assert "async refreshData()" in html
    assert "this.lastUpdated = new Date().toLocaleTimeString" in html


def test_public_page_supports_opt_in_auto_refresh():
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert 'aria-label="Automatically refresh data every 60 seconds"' in html
    assert 'x-model="autoRefreshEnabled"' in html
    assert '@change="toggleAutoRefresh"' in html
    assert "autoRefreshEnabled: false" in html
    assert "toggleAutoRefresh()" in html
    assert "setInterval(" in html
    assert "60 * 1000" in html
    assert "clearInterval(this.autoRefreshTimer)" in html


def test_admin_page_supports_safe_key_visibility_control():
    response = client.get("/admin")
    assert response.status_code == 200
    html = response.text
    assert "showAdminKey: false" in html
    assert ":type=\"showAdminKey ? 'text' : 'password'\"" in html
    assert 'autocomplete="off"' in html
    assert 'aria-label="Admin API key"' in html
    assert '@click="showAdminKey = !showAdminKey"' in html
    assert ":aria-pressed=\"showAdminKey\"" in html
    assert "'Hide admin key' : 'Show admin key'" in html
    assert "Used only in this tab and never saved." in html
    assert "localStorage" not in html


def test_admin_page_has_loading_empty_and_error_states():
    response = client.get("/admin")
    assert response.status_code == 200
    html = response.text
    assert "Loading markets..." in html
    assert "No open markets. Use Sync Polymarket to load the top 25 markets by 24h volume." in html
    assert "Loading agents..." in html
    assert "No agents deployed yet. Create an agent above." in html
    assert "Failed to load markets:" in html
    assert "Failed to load agents:" in html



def test_admin_auth_required_and_invalid():
    assert client.post("/api/admin/sync").status_code == 401
    response = client.post("/api/admin/sync", headers={"X-Admin-Key": "wrong"})
    assert response.status_code == 403


@patch("main.sync_markets_logic")
def test_admin_auth_valid_mocked(mock_sync):
    mock_sync.return_value = {"added": 5, "updated": 2}
    response = client.post("/api/admin/sync", headers=ADMIN_HEADERS)
    assert response.status_code == 200
    assert response.json() == {"status": "success", "added": 5, "updated": 2}


def test_agent_creation_hashes_key_and_duplicate_is_conflict():
    raw_key = create_agent()
    with SessionLocal() as db:
        agent = db.query(Agent).one()
        assert agent.hashed_api_key != raw_key
        assert agent.hashed_api_key == hashlib.sha256(raw_key.encode()).hexdigest()

    leaderboard = client.get("/leaderboard").json()
    assert "hashed_api_key" not in leaderboard[0]

    duplicate = client.post(
        "/api/admin/agents",
        headers=ADMIN_HEADERS,
        json={"name": "Test Agent", "model": "gpt-4o-mini"},
    )
    assert duplicate.status_code == 409


def test_agent_can_self_onboard_and_receives_one_time_key():
    response = client.post(
        "/agents/onboard",
        json={"name": "Self Agent", "model": "gpt-4o-mini"},
    )
    assert response.status_code == 201
    data = response.json()
    raw_key = data["api_key"]
    assert data["agent"]["name"] == "Self Agent"
    assert "shown once" in data["credential_notice"]

    with SessionLocal() as db:
        agent = db.query(Agent).filter(Agent.name == "Self Agent").one()
        assert agent.hashed_api_key == hashlib.sha256(raw_key.encode()).hexdigest()
        assert agent.hashed_api_key != raw_key

    duplicate = client.post(
        "/agents/onboard",
        json={"name": "Self Agent", "model": "gpt-4o-mini"},
    )
    assert duplicate.status_code == 409


def test_onboarding_guide_documents_predict_before_consensus():
    response = client.get("/agents/onboarding")
    assert response.status_code == 200
    data = response.json()
    assert data["workflow"] == "predict_before_consensus"
    assert data["credential"]["returned_once"] is True
    assert data["steps"][0]["path"] == "/agents/onboard"
    assert data["steps"][-1]["requires"]


def test_peer_consensus_is_revealed_only_after_own_prediction():
    market_id = create_market()
    first_key = create_agent("First Agent")
    second_key = create_agent("Second Agent")

    first_vote = client.post(
        "/predictions",
        json=prediction_payload(market_id, probability=0.8),
        headers={"X-Agent-Key": first_key},
    )
    assert first_vote.status_code == 200
    assert first_vote.json()["peer_consensus"]["peer_count"] == 0

    locked = client.get(
        f"/markets/{market_id}/predictions",
        headers={"X-Agent-Key": second_key},
    )
    assert locked.status_code == 403
    assert "Submit your own prediction" in locked.json()["detail"]

    second_vote = client.post(
        "/predictions",
        json=prediction_payload(market_id, probability=0.4),
        headers={"X-Agent-Key": second_key},
    )
    assert second_vote.status_code == 200
    revealed = second_vote.json()["peer_consensus"]
    assert revealed["revealed"] is True
    assert revealed["peer_count"] == 1
    assert revealed["mean_probability_yes"] == pytest.approx(0.8)
    assert revealed["forecasts"][0]["agent_name"] == "First Agent"

    later = client.get(
        f"/markets/{market_id}/predictions",
        headers={"X-Agent-Key": second_key},
    )
    assert later.status_code == 200
    assert later.json()["own_forecast"]["probability_yes"] == pytest.approx(0.4)
    assert later.json()["peer_consensus"]["peer_count"] == 1


def test_prediction_auth_validation_and_duplicate_protection():
    market_id = create_market()
    raw_key = create_agent()
    payload = prediction_payload(market_id)

    assert client.post("/predictions", json=payload).status_code == 401
    assert (
        client.post(
            "/predictions", json=payload, headers={"X-Agent-Key": "wrong"}
        ).status_code
        == 403
    )

    invalid = {**payload, "probability_yes": 1.1}
    assert (
        client.post(
            "/predictions", json=invalid, headers={"X-Agent-Key": raw_key}
        ).status_code
        == 422
    )

    created = client.post(
        "/predictions", json=payload, headers={"X-Agent-Key": raw_key}
    )
    assert created.status_code == 200
    duplicate = client.post(
        "/predictions", json=payload, headers={"X-Agent-Key": raw_key}
    )
    assert duplicate.status_code == 409


def test_gated_predictions_and_brier_scoring():
    market_id = create_market()
    raw_key = create_agent()
    response = client.post(
        "/predictions",
        json=prediction_payload(market_id, probability=0.75),
        headers={"X-Agent-Key": raw_key},
    )
    assert response.status_code == 200

    assert client.get(f"/markets/{market_id}/predictions").status_code == 401
    revealed = client.get(
        f"/markets/{market_id}/predictions",
        headers={"X-Agent-Key": raw_key},
    )
    assert revealed.status_code == 200
    assert revealed.json()["own_forecast"]["probability_yes"] == 0.75
    assert revealed.json()["peer_consensus"]["peer_count"] == 0

    resolved = client.post(
        f"/api/admin/markets/{market_id}/resolve?status=RESOLVED_YES",
        headers=ADMIN_HEADERS,
    )
    assert resolved.status_code == 200
    agent = client.get("/leaderboard").json()[0]
    assert agent["predictions_count"] == 1
    assert agent["accuracy_score"] == pytest.approx(0.9375)

    repeated = client.post(
        f"/api/admin/markets/{market_id}/resolve?status=RESOLVED_YES",
        headers=ADMIN_HEADERS,
    )
    assert repeated.status_code == 400


def test_key_rotation_revokes_old_key():
    old_key = create_agent()
    first_market = create_market("First market?")
    second_market = create_market("Second market?")

    rotated = client.post("/api/admin/agents/1/rotate-key", headers=ADMIN_HEADERS)
    assert rotated.status_code == 200
    new_key = rotated.json()["api_key"]
    assert new_key != old_key

    old_response = client.post(
        "/predictions",
        json=prediction_payload(first_market),
        headers={"X-Agent-Key": old_key},
    )
    assert old_response.status_code == 403
    new_response = client.post(
        "/predictions",
        json=prediction_payload(second_market),
        headers={"X-Agent-Key": new_key},
    )
    assert new_response.status_code == 200


def test_bcrypt_release_key_is_accepted_and_upgraded():
    raw_key = "bcrypt-release-key"
    with SessionLocal() as db:
        agent = Agent(
            name="Legacy bcrypt agent",
            model="gpt-4o-mini",
            hashed_api_key=bcrypt.hashpw(raw_key.encode(), bcrypt.gensalt()).decode(),
        )
        market = Market(
            source_market_id="bcrypt-test-market",
            source="Test",
            question="Will legacy authentication work?",
            resolution_status="OPEN",
        )
        db.add_all([agent, market])
        db.commit()
        db.refresh(market)
        market_id = market.id

    response = client.post(
        "/predictions",
        json=prediction_payload(market_id),
        headers={"X-Agent-Key": raw_key},
    )
    assert response.status_code == 200
    with SessionLocal() as db:
        stored = db.query(Agent).one().hashed_api_key
        assert stored == hashlib.sha256(raw_key.encode()).hexdigest()


@patch("sync_polymarket.requests.get")
def test_market_sync_uses_supported_public_events_query(mock_get):
    response = Mock()
    response.json.return_value = []
    mock_get.return_value = response

    assert sync_markets_logic() == {"added": 0, "updated": 0, "hidden": 0}
    mock_get.assert_called_once_with(
        "https://gamma-api.polymarket.com/markets",
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
    response.raise_for_status.assert_called_once()


def test_market_context_parsing_and_runner_prompt():
    records = list(
        _market_records(
            [
                {
                    "id": "event-1",
                    "title": "Example event",
                    "slug": "example-event",
                    "markets": [
                        {
                            "id": "market-1",
                            "question": "Will this happen?",
                            "description": "Detailed context",
                            "resolutionSource": "Official source",
                            "endDate": "2026-08-01T00:00:00Z",
                            "outcomes": '["Yes", "No"]',
                            "outcomePrices": '["0.63", "0.37"]',
                        }
                    ],
                }
            ]
        )
    )
    assert len(records) == 1
    assert records[0]["market_probability"] == 0.63
    assert records[0]["source_url"].endswith("example-event")

    prompt = build_prompt({"id": 1, **records[0]})
    assert "Detailed context" in prompt
    assert "0.63" in prompt
    assert "Official source" in prompt
    assert (
        validate_forecast(
            {
                "probability_yes": 0.6,
                "confidence_score": 0.7,
                "reasoning": "Enough supporting detail.",
            }
        )["probability_yes"]
        == 0.6
    )


def alembic_config(database_url):
    config = Config(str(Path(__file__).with_name("alembic.ini")))
    config.set_main_option("sqlalchemy.url", database_url)
    os.environ["DATABASE_URL"] = database_url
    return config


def test_alembic_clean_install(tmp_path):
    database = tmp_path / "clean.db"
    database_url = f"sqlite:///{database}"
    command.upgrade(alembic_config(database_url), "head")
    connection = sqlite3.connect(database)
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    connection.close()
    assert {"agents", "markets", "predictions", "alembic_version"} <= set(tables)


def test_alembic_adopts_legacy_database_and_preserves_key(tmp_path):
    database = tmp_path / "legacy.db"
    raw_key = "legacy-agent-key"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE agents (
            id INTEGER PRIMARY KEY,
            name VARCHAR NOT NULL UNIQUE,
            model VARCHAR NOT NULL,
            api_key VARCHAR NOT NULL UNIQUE,
            accuracy_score FLOAT,
            predictions_count INTEGER
        );
        CREATE TABLE markets (
            id INTEGER PRIMARY KEY,
            source VARCHAR NOT NULL,
            question VARCHAR NOT NULL,
            resolution_status VARCHAR
        );
        CREATE TABLE predictions (
            id INTEGER PRIMARY KEY,
            agent_id INTEGER NOT NULL REFERENCES agents(id),
            market_id INTEGER NOT NULL REFERENCES markets(id),
            probability_yes FLOAT NOT NULL,
            confidence_score FLOAT NOT NULL,
            reasoning VARCHAR NOT NULL,
            created_at DATETIME,
            CONSTRAINT uix_agent_market_prediction UNIQUE (agent_id, market_id)
        );
        """
    )
    connection.execute(
        "INSERT INTO agents VALUES (1, 'Legacy', 'gpt-4o-mini', ?, 0, 0)",
        (raw_key,),
    )
    connection.commit()
    connection.close()

    database_url = f"sqlite:///{database}"
    command.upgrade(alembic_config(database_url), "head")

    connection = sqlite3.connect(database)
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(agents)").fetchall()
    }
    stored_hash = connection.execute(
        "SELECT hashed_api_key FROM agents WHERE id = 1"
    ).fetchone()[0]
    connection.close()

    assert "api_key" not in columns
    assert "hashed_api_key" in columns
    assert stored_hash == hashlib.sha256(raw_key.encode()).hexdigest()


def test_alembic_upgrades_applied_bcrypt_release(tmp_path):
    database = tmp_path / "bcrypt-release.db"
    bcrypt_hash = bcrypt.hashpw(b"old-key", bcrypt.gensalt()).decode()
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE alembic_version (
            version_num VARCHAR(32) NOT NULL PRIMARY KEY
        );
        INSERT INTO alembic_version VALUES ('37f5d9b726fe');
        CREATE TABLE agents (
            id INTEGER PRIMARY KEY,
            name VARCHAR NOT NULL UNIQUE,
            model VARCHAR NOT NULL,
            hashed_api_key VARCHAR NOT NULL,
            accuracy_score FLOAT,
            predictions_count INTEGER
        );
        CREATE TABLE markets (
            id INTEGER PRIMARY KEY,
            source VARCHAR NOT NULL,
            question VARCHAR NOT NULL,
            resolution_status VARCHAR
        );
        CREATE TABLE predictions (
            id INTEGER PRIMARY KEY,
            agent_id INTEGER NOT NULL REFERENCES agents(id),
            market_id INTEGER NOT NULL REFERENCES markets(id),
            probability_yes FLOAT NOT NULL,
            confidence_score FLOAT NOT NULL,
            reasoning VARCHAR NOT NULL,
            created_at DATETIME,
            CONSTRAINT uix_agent_market_prediction UNIQUE (agent_id, market_id)
        );
        """
    )
    connection.execute(
        "INSERT INTO agents VALUES (1, 'Bcrypt', 'gpt-4o-mini', ?, 0, 0)",
        (bcrypt_hash,),
    )
    connection.commit()
    connection.close()

    database_url = f"sqlite:///{database}"
    command.upgrade(alembic_config(database_url), "head")

    connection = sqlite3.connect(database)
    market_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(markets)").fetchall()
    }
    preserved_hash = connection.execute(
        "SELECT hashed_api_key FROM agents WHERE id = 1"
    ).fetchone()[0]
    version = connection.execute("SELECT version_num FROM alembic_version").fetchone()[
        0
    ]
    connection.close()

    assert {"source_market_id", "description", "market_probability"} <= market_columns
    assert preserved_hash == bcrypt_hash
    assert version == "8c63c4e1a4f2"
