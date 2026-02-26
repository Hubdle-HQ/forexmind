"""
ForexMind API configuration.

Use get_api_base_url() in Streamlit, scripts, or any client that calls the backend.
"""
import os
from pathlib import Path

# Load .env from project root
_env_path = Path(__file__).resolve().parent / ".env"
if _env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(_env_path)

# Dev = local backend; Prod = Railway
API_URLS = {
    "dev": "http://localhost:8000",
    "prod": "https://forexmind-production.up.railway.app",
}


def get_api_base_url() -> str:
    """
    Return the backend API base URL.
    - Set API_BASE_URL in .env to override (e.g. prod when testing against Railway).
    - Default: dev (localhost:8000).
    """
    return os.getenv("API_BASE_URL", API_URLS["dev"])
