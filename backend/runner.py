import json
import os
import time

import anthropic
import requests
from openai import OpenAI


API_BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000")


def extract_json(text):
    start = text.find("{")
    end = text.rfind("}") + 1
    if start < 0 or end <= start:
        raise ValueError("Model response did not contain a JSON object")
    return json.loads(text[start:end])


def build_prompt(market):
    return f"""
You are a calibrated prediction-market forecaster. Estimate the probability
that the market resolves YES. Treat the resolution rules as authoritative and
distinguish your estimate from the current crowd probability.

Question: {market["question"]}
Description: {market.get("description") or "Not provided"}
Resolution rules/source: {market.get("resolution_rules") or "Not provided"}
Close date: {market.get("end_date") or "Not provided"}
Current Polymarket YES probability: {market.get("market_probability")}
Market URL: {market.get("source_url") or "Not provided"}

Respond with one JSON object only:
{{"probability_yes": 0.5, "confidence_score": 0.8, "reasoning": "brief, evidence-based explanation"}}
""".strip()


def forecast(model_name, prompt):
    if "claude" in model_name.lower():
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        message = client.messages.create(
            model=model_name,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return extract_json(message.content[0].text)

    if "gpt" in model_name.lower():
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            timeout=15,
        )
        return json.loads(response.choices[0].message.content)

    response = requests.post(
        os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434/api/chat"),
        json={
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "format": "json",
        },
        timeout=20,
    )
    response.raise_for_status()
    return extract_json(response.json()["message"]["content"])


def validate_forecast(data):
    probability = float(data["probability_yes"])
    confidence = float(data["confidence_score"])
    reasoning = str(data["reasoning"]).strip()
    if not 0 <= probability <= 1 or not 0 <= confidence <= 1:
        raise ValueError("Probability and confidence must be between 0 and 1")
    if len(reasoning) < 5:
        raise ValueError("Reasoning is too short")
    return {
        "probability_yes": probability,
        "confidence_score": confidence,
        "reasoning": reasoning,
    }


def run_agents():
    raw_credentials = os.environ.get("AGENT_CREDENTIALS")
    if not raw_credentials:
        print("No AGENT_CREDENTIALS found.")
        return

    try:
        active_agents = json.loads(raw_credentials)
        if not isinstance(active_agents, list):
            raise ValueError("credentials must be a list")
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"Invalid AGENT_CREDENTIALS: {exc}")
        return

    try:
        response = requests.get(f"{API_BASE}/markets", timeout=5)
        response.raise_for_status()
        markets = response.json()
    except (requests.RequestException, ValueError) as exc:
        print(f"Failed to reach API: {exc}")
        return

    for agent in active_agents:
        model_name = agent.get("model")
        api_key = agent.get("api_key")
        if not model_name or not api_key:
            print("Skipping agent with missing model or api_key")
            continue

        for market in markets:
            try:
                prediction = validate_forecast(
                    forecast(model_name, build_prompt(market))
                )
            except Exception as exc:
                print(f"Inference failed for market {market['id']}: {exc}")
                continue

            prediction["market_id"] = market["id"]
            try:
                response = requests.post(
                    f"{API_BASE}/predictions",
                    json=prediction,
                    headers={"X-Agent-Key": api_key},
                    timeout=5,
                )
                if response.status_code == 409:
                    continue
                response.raise_for_status()
                print(
                    f"Submitted market {market['id']}: "
                    f"{prediction['probability_yes']:.1%} YES"
                )
            except requests.RequestException as exc:
                print(f"Submit failed for market {market['id']}: {exc}")

            time.sleep(1)


if __name__ == "__main__":
    run_agents()
