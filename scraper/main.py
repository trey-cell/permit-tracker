"""
main.py
-------
Entry point for the Permit Tracker.
  1. Loads enabled municipalities from config
  2. Scrapes each Accela portal
  3. Updates the Google Sheet
  4. Sends email alert if any permit changed
"""

import os
import sys
import logging
import yaml
from pathlib import Path
from dotenv import load_dotenv

# Load .env file if present (local dev only — GitHub Actions uses secrets)
load_dotenv(Path(__file__).parent.parent / ".env")

from accela_scraper import scrape_municipality
from sheets_updater import update_sheet
from notifier import send_change_alert

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


def load_config() -> dict:
    config_path = Path(__file__).parent.parent / "config" / "municipalities.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def main():
    logger.info("=" * 60)
    logger.info("  Coastal Edge Permit Tracker — Starting Run")
    logger.info("=" * 60)

    config = load_config()
    municipalities = config.get("municipalities", {})

    all_records = []
    for key, muni_config in municipalities.items():
        if not muni_config.get("enabled", False):
            logger.info(f"Skipping {muni_config['name']} (disabled in config)")
            continue

        logger.info(f"\n── Scraping {muni_config['name']} ──")
        try:
            records = scrape_municipality(muni_config)
            all_records.extend(records)
            logger.info(f"  ✓ {len(records)} permits found in {muni_config['name']}")
        except Exception as e:
            logger.error(f"  ✗ Failed to scrape {muni_config['name']}: {e}")

    if not all_records:
        logger.warning("No permits found across any municipality. Exiting.")
        return

    logger.info(f"\nTotal permits scraped: {len(all_records)}")

    # Update Google Sheet and detect changes
    logger.info("\nUpdating Google Sheet...")
    changed = update_sheet(all_records)

    if changed:
        logger.info(f"\n🚨 {len(changed)} permit(s) changed — sending alert...")
        send_change_alert(changed)
    else:
        logger.info("\n✓ No changes detected — all permits unchanged.")

    logger.info("\nRun complete.")


if __name__ == "__main__":
    main()
