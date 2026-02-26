"""
Supabase client singleton. Load .env and create one client instance.
Do not create a new client per request.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client, Client

# Load .env from project root (parent of backend/)
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_env_path)

_supabase: Client | None = None


def get_supabase() -> Client:
    """Return the singleton Supabase client."""
    global _supabase
    if _supabase is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if not url or not key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env")
        _supabase = create_client(url, key)
    return _supabase


def test_connection() -> None:
    """Run a simple SELECT on pipeline_health to verify the connection."""
    try:
        get_supabase().table("pipeline_health").select("*").limit(1).execute()
        print("Success: Supabase connection verified.")
    except Exception as e:
        print(f"Error: {e}")
