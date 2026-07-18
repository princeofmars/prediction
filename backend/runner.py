import os
import json
import requests
from openai import OpenAI
import time

API_BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000")

def run_agents():
    print("🤖 Waking up Prediction Agent Orchestrator...")
    
    # 1. Fetch Agents and their secure API keys (in a real system, these would be managed by the agent runtime, not pulled from a public leaderboard)
    # For this runner, we assume the environment passes a list of agent credentials
    agent_creds = os.environ.get("AGENT_CREDENTIALS")
    if not agent_creds:
        print("⚠️ No AGENT_CREDENTIALS environment variable found. Format: '[{\"id\": 1, \"model\": \"gpt-4o-mini\", \"api_key\": \"...\"}]'")
        return
        
    try:
        active_agents = json.loads(agent_creds)
    except Exception as e:
        print("❌ Invalid AGENT_CREDENTIALS JSON format.")
        return

    # 2. Get Open Markets
    try:
        markets = requests.get(f"{API_BASE}/markets", timeout=5).json()
    except Exception as e:
        print(f"❌ Failed to reach API: {e}")
        return

    if not markets:
        print("⚠️ No open markets found.")
        return

    # 3. Multi-Agent Orchestration
    for agent in active_agents:
        print(f"\n👤 Orchestrating Agent: {agent.get('model', 'unknown')}")
        
        for market in markets:
            prompt = f"""
            You are an elite, highly analytical prediction market AI.
            Evaluate the following market question and predict the probability of it resolving to YES.
            
            Market Question: {market['question']}
            Source: {market['source']}
            
            Respond strictly in valid JSON format:
            - "probability_yes": float between 0.0 and 1.0
            - "confidence_score": float between 0.0 and 1.0
            - "reasoning": concise string explaining your rationale.
            """

            model_name = agent.get('model', 'gpt-4o-mini')
            
            try:
                if "gpt" in model_name or "claude" in model_name: # Handle APIs
                    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", "dummy-key"))
                    response = client.chat.completions.create(
                        model=model_name,
                        messages=[{"role": "user", "content": prompt}],
                        response_format={"type": "json_object"},
                        timeout=15
                    )
                    prediction_data = json.loads(response.choices[0].message.content)
                else: # Fallback to local Ollama using dynamic model name
                    ollama_payload = {
                        "model": model_name,
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": False,
                        "format": "json"
                    }
                    response = requests.post("http://127.0.0.1:11434/api/chat", json=ollama_payload, timeout=20)
                    response.raise_for_status()
                    prediction_data = json.loads(response.json()["message"]["content"])
                    
            except Exception as e:
                print(f"❌ Inference failed for market {market['id']} using {model_name}: {e}")
                continue

            # 4. Post authenticated prediction
            payload = {
                "market_id": market["id"],
                "probability_yes": prediction_data["probability_yes"],
                "confidence_score": prediction_data["confidence_score"],
                "reasoning": prediction_data["reasoning"]
            }
            
            headers = {"X-Agent-Key": agent.get("api_key")}
            
            try:
                res = requests.post(f"{API_BASE}/predictions", json=payload, headers=headers, timeout=5)
                res.raise_for_status()
                print(f"   ✅ [Market {market['id']}] Prob: {prediction_data['probability_yes']} | Reason: {prediction_data['reasoning'][:50]}...")
            except requests.exceptions.HTTPError as e:
                # 409 means already predicted, ignore silently. Other errors log.
                if res.status_code != 409:
                    print(f"❌ Failed to submit prediction: {res.text}")
                    
            time.sleep(1) # Rate limit protection

if __name__ == "__main__":
    run_agents()
