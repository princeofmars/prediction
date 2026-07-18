import os
import json
import requests
from openai import OpenAI
import anthropic
import time

API_BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000")

def run_agents():
    print("🤖 Waking up Prediction Agent Orchestrator...")
    
    agent_creds = os.environ.get("AGENT_CREDENTIALS")
    if not agent_creds:
        print("⚠️ No AGENT_CREDENTIALS found.")
        return
        
    try:
        active_agents = json.loads(agent_creds)
    except Exception:
        print("❌ Invalid AGENT_CREDENTIALS JSON format.")
        return

    try:
        markets = requests.get(f"{API_BASE}/markets", timeout=5).json()
    except Exception as e:
        print(f"❌ Failed to reach API: {e}")
        return

    if not markets:
        return

    for agent in active_agents:
        print(f"\n👤 Orchestrating Agent: {agent.get('model', 'unknown')}")
        
        for market in markets:
            prompt = f"""
            You are an elite prediction market AI.
            Predict the probability of this resolving to YES.
            Market: {market['question']}
            Source: {market['source']}
            
            Respond strictly in valid JSON format:
            {{"probability_yes": 0.5, "confidence_score": 0.8, "reasoning": "brief explanation"}}
            """

            model_name = agent.get('model', 'gpt-4o-mini')
            prediction_data = None
            
            try:
                if "claude" in model_name.lower():
                    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
                    msg = client.messages.create(
                        model=model_name,
                        max_tokens=1024,
                        messages=[{"role": "user", "content": prompt}]
                    )
                    # Simple extraction
                    text = msg.content[0].text
                    start = text.find('{')
                    end = text.rfind('}') + 1
                    prediction_data = json.loads(text[start:end])
                elif "gpt" in model_name.lower():
                    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", "dummy-key"))
                    response = client.chat.completions.create(
                        model=model_name,
                        messages=[{"role": "user", "content": prompt}],
                        response_format={"type": "json_object"},
                        timeout=15
                    )
                    prediction_data = json.loads(response.choices[0].message.content)
                else:
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
                print(f"❌ Inference failed for market {market['id']}: {e}")
                continue

            if not prediction_data: continue

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
                print(f"   ✅ [Market {market['id']}] Prob: {prediction_data['probability_yes']}")
            except requests.exceptions.HTTPError as e:
                if res.status_code != 409:
                    print(f"❌ Submit failed: {res.text}")
                    
            time.sleep(1)

if __name__ == "__main__":
    run_agents()
