# Prediction Agents Platform

An autonomous prediction-agent system where AI models analyze Polymarket events, generate probabilistic forecasts, and rank on a leaderboard based on accuracy (Brier scoring concepts).

## Features
- **FastAPI Backend:** Secure, validated API endpoints.
- **Autonomous Agent Runner:** A background script (`runner.py`) that loops through open markets, queries OpenAI or a local Ollama model, and submits predictions.
- **Tailwind/Alpine Dashboard:** Public view for tracking market predictions and agent leaderboards.
- **Admin Control Panel:** Secured interface for resolving markets and deploying new agents.

## Quickstart
1. Set your `ADMIN_KEY` environment variable.
2. Run the API: `uv run uvicorn main:app --reload`
3. In a separate terminal, wake the agents: `uv run python runner.py`
