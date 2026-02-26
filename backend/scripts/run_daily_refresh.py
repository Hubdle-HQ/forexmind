"""
Cron entry point: run daily refresh and exit.
For Railway cron — set Cron Schedule to "0 20 * * *" (6am AEST = 8pm UTC).
"""
import logging
import sys
from pathlib import Path

_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    from monitoring.daily_refresh import run_daily_refresh

    results = run_daily_refresh()
    logger.info("Daily refresh complete: %s", results)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.exception("Daily refresh failed: %s", e)
        sys.exit(1)
