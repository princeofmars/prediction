import os
import json
import requests
from openai import OpenAI
import time

API_BASE = "http://127.0.0.1:8000"
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", "dummy-key"))

def run_agent():
    print("🤖 Waking up Prediction Agent Runner...")
    
    # 1. Get Agents from Leaderboard
    try:
        agents = requests.get(f"{API_BASE}/leaderboard").json()
    except requests.exceptions.ConnectionError:
        print("❌ Error: FastAPI server is not running. Start it with `uv run uvicorn main:app` first.")
        return

    if not agents:
        print("⚠️ No agents found. Please create one in the admin dashboard first (http://127.0.0.1:8000/admin).")
        return
    
    # Use the first available agent
    agent = agents[0]
    print(f"👤 Active Agent: {agent['name']} (ID: {agent['id']}, Model: {agent['model']})")

    # 2. Get Open Markets
    markets = requests.get(f"{API_BASE}/markets").json()
    if not markets:
        print("⚠️ No open markets found. Please sync markets in the admin dashboard.")
        return

    print(f"📊 Found {len(markets)} open markets. Analyzing...")

    for market in markets:
        print(f"\n🧠 Market: {market['question']}")
        
        # Nexus-style Prompt combining numerical/probabilistic constraints and text reasoning
        prompt = f"""
        You are an elite, highly analytical prediction market AI.
        Evaluate the following market question and predict the probability of it resolving to YES.
        
        Market Question: {market['question']}
        Source: {market['source']}
        
        Respond strictly in valid JSON format with the following keys:
        - "probability_yes": float between 0.0 and 1.0
        - "confidence_score": float between 0.0 and 1.0
        - "reasoning": concise string explaining your rationale based on current trends and probabilities.
        """

        try:
            if not os.environ.get("OPENAI_API_KEY"):
                print("⚠️ OPENAI_API_KEY not set. Using LOCAL OLLAMA (Model: phi3).")
                # Local Ollama Inference
                ollama_payload = {
                    "model": "phi3",
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "format": "json"
                }
                try:
                    response = requests.post("http://127.0.0.1:11434/api/chat", json=ollama_payload)
                    response.raise_for_status()
                    prediction_data = json.loads(response.json()["message"]["content"])
                except Exception as e:
                    print(f"❌ Failed to connect to local Ollama. Is Ollama running? Error: {e}")
                    continue
            else:
                # OpenAI Inference
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"}
                )
                prediction_data = json.loads(response.choices[0].message.content)

            # 3. Post the Prediction back to our platform
            payload = {
                "agent_id": agent["id"],
                "market_id": market["id"],
                "probability_yes": prediction_data["probability_yes"],
                "confidence_score": prediction_data["confidence_score"],
                "reasoning": prediction_data["reasoning"]
            }
            
            res = requests.post(f"{API_BASE}/predictions", json=payload)
            res.raise_for_status()
            
            print(f"   ↳ 🎯 Prob: {prediction_data['probability_yes']*100}% | Conf: {prediction_data['confidence_score']}")
            print(f"   ↳ 📝 Reasoning: {prediction_data['reasoning']}")
            
        except Exception as e:
            print(f"❌ Error processing market {market['id']}: {e}")
            
        time.sleep(1) # Prevent rate-limiting

if __name__ == "__main__":
    run_agent()
