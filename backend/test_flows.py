import sys
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def run_tests():
    try:
        print("1. Testing UI Endpoints...")
        assert client.get("/").status_code == 200
        assert client.get("/admin").status_code == 200
        print("✅ UI Endpoints OK")

        print("2. Testing Market Sync...")
        res = client.post("/api/admin/sync")
        assert res.status_code == 200
        
        markets = client.get("/markets").json()
        assert len(markets) > 0, "No markets found after sync"
        market_id = markets[0]["id"]
        print(f"✅ Synced {len(markets)} markets. Selected Market ID: {market_id}")

        print("3. Testing Agent Creation...")
        # Create a unique agent name
        import time
        agent_name = f"DiagnosticBot_{int(time.time())}"
        res = client.post("/api/admin/agents", json={"name": agent_name, "model": "test-model"})
        assert res.status_code == 200
        
        leaderboard = client.get("/leaderboard").json()
        agent_id = next(a["id"] for a in leaderboard if a["name"] == agent_name)
        print(f"✅ Created agent. Agent ID: {agent_id}")

        print("4. Testing Prediction Submission...")
        pred_data = {
            "agent_id": agent_id,
            "market_id": market_id,
            "probability_yes": 0.75,
            "confidence_score": 0.9,
            "reasoning": "Diagnostic test reasoning."
        }
        res = client.post("/predictions", json=pred_data)
        assert res.status_code == 200
        print("✅ Prediction submitted successfully")

        print("5. Testing Market Resolution...")
        res = client.post(f"/api/admin/markets/{market_id}/resolve?status=RESOLVED_YES")
        assert res.status_code == 200
        
        updated_markets = client.get("/markets").json()
        assert not any(m["id"] == market_id for m in updated_markets), "Market still appears in OPEN list"
        print("✅ Market resolved and correctly removed from OPEN list")

        print("\n🚀 ALL FLOWS VERIFIED SUCCESSFULLY!")
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        sys.exit(1)

if __name__ == "__main__":
    run_tests()
