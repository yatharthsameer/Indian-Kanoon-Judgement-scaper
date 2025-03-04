import os
import time
import json
import logging
import threading
import pandas as pd
import concurrent.futures
from seleniumbase import SB  # pip install seleniumbase

# -------------------------------------------------------------------
# 1) HARDCODED LIST OF CSV FILES
# -------------------------------------------------------------------
CSV_FILES = [
    "Sikkim High Court.csv",
    "Bombay High Court.csv",
    "Delhi High Court.csv",
    "Karnataka High Court.csv",
    "Madras High Court.csv",
    "Gujarat High Court.csv",
    # ... add more as needed
]

# Specify the base output directory
BASE_OUTPUT_DIR = "/Volumes/T7/data"

HEADLESS = True  # Toggle headless mode
MAX_RETRIES = 4  # Times to attempt bypassing Cloudflare
MAX_THREADS = 6  # Max concurrent threads

# **Checkpoint file** where we store last-processed row index per CSV
CHECKPOINT_FILE = "scraping_checkpoint_download.json"

# A lock to prevent race conditions when multiple threads update the checkpoint
checkpoint_lock = threading.Lock()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


# -------------------------------------------------------------------
# 2) CHECKPOINT UTILS
# -------------------------------------------------------------------
def get_checkpoint_value(csv_file: str) -> int:
    """
    Return the next row index to process for 'csv_file'
    from the checkpoint JSON, or 0 if not present.
    Thread-safe via checkpoint_lock.
    """
    with checkpoint_lock:
        if not os.path.exists(CHECKPOINT_FILE):
            return 0
        try:
            with open(CHECKPOINT_FILE, "r") as f:
                data = json.load(f)
                return data.get(csv_file, 0)
        except (json.JSONDecodeError, ValueError):
            logger.warning("Checkpoint file is corrupted or empty. Resetting to 0.")
            return 0


def update_checkpoint_value(csv_file: str, new_value: int):
    """
    Update the checkpoint so that 'csv_file' is recorded
    as processed up to 'new_value' (the next row index to process).
    Thread-safe via checkpoint_lock.
    """
    with checkpoint_lock:
        # Load existing data (or start empty)
        if os.path.exists(CHECKPOINT_FILE):
            try:
                with open(CHECKPOINT_FILE, "r") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, ValueError):
                logger.warning("Checkpoint file corrupted; re-initializing.")
                data = {}
        else:
            data = {}

        data[csv_file] = new_value

        # Write back to JSON
        with open(CHECKPOINT_FILE, "w") as f:
            json.dump(data, f, indent=2)


# -------------------------------------------------------------------
# 3) CLOUDFLARE-BYPASS & INTERACTION HELPERS
# -------------------------------------------------------------------
def open_kanoon_page(sb, url, max_retries=3):
    """
    Opens the page with 'uc_open_with_reconnect()' up to 'max_retries' times,
    checking for typical Cloudflare challenge elements.
    """
    for attempt in range(1, max_retries + 1):
        logger.info(f"[Attempt {attempt}] Opening {url} with reconnect...")
        sb.uc_open_with_reconnect(url, 3)

        # Give time for Cloudflare's "Verifying..."
        time.sleep(3)

        if sb.is_element_visible('input[value*="Verify"]'):
            logger.info("Cloudflare: Found 'Verify' button, clicking...")
            sb.uc_click('input[value*="Verify"]')
            time.sleep(5)
        elif sb.is_element_visible("iframe"):
            logger.info(
                "Cloudflare: Possibly a CAPTCHA iframe, attempting auto‐click..."
            )
            sb.uc_gui_click_captcha()
            time.sleep(5)

        # Check if we've actually reached the doc page
        found_it = False
        for _ in range(10):
            if (
                sb.is_element_visible("[devinid='10']")
                or sb.is_element_visible(
                    "//button[contains(text(), 'Print it on a file/printer')]"
                )
                or sb.is_element_visible(
                    "//a[contains(text(), 'Print it on a file/printer')]"
                )
            ):
                found_it = True
                break
            time.sleep(1)

        if found_it:
            logger.info("Successfully reached the final page!")
            return True
        else:
            logger.warning(
                "Still not on the final doc page; possibly stuck on Cloudflare."
            )

    logger.error(f"Failed to bypass Cloudflare after {max_retries} attempts for {url}")
    return False


def click_print_button(sb):
    """
    Optionally click the 'Print it on a file/printer' link to load a 'printer-friendly' page.
    If not found, we simply proceed.
    """
    try:
        if sb.is_element_visible("[devinid='10']"):
            logger.info("Clicking element with devinid='10'...")
            sb.click("[devinid='10']")
            return True
        elif sb.is_element_visible(
            "//button[contains(text(), 'Print it on a file/printer')]"
        ):
            logger.info("Clicking 'Print it on a file/printer' button (XPath)...")
            sb.click("//button[contains(text(), 'Print it on a file/printer')]")
            return True
        elif sb.is_element_visible(
            "//a[contains(text(), 'Print it on a file/printer')]"
        ):
            logger.info("Clicking 'Print it on a file/printer' link (XPath)...")
            sb.click("//a[contains(text(), 'Print it on a file/printer')]")
            return True
        else:
            logger.warning("No 'Print it on a file/printer' button/link found.")
            return False
    except Exception as e:
        logger.error(f"Error clicking print button: {e}")
        return False


def save_as_html(sb, html_path):
    """
    Saves the current page's HTML source to 'html_path'.
    """
    try:
        logger.info(f"Saving HTML => {html_path}")
        time.sleep(3)  # brief pause, ensuring the page is fully loaded
        page_source = sb.get_page_source()
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(page_source)
        logger.info(f"Saved HTML: {html_path}")
        return True
    except Exception as e:
        logger.error(f"Error saving HTML: {e}")
        return False


# -------------------------------------------------------------------
# 4) THREAD FUNCTION: Process a Single CSV
# -------------------------------------------------------------------
def process_csv(csv_file):
    """
    Reads `csv_file`, uses the global checkpoint to resume from last known row,
    and for each row:
      - Open page & bypass Cloudflare
      - Optionally click "Print it on a file/printer"
      - Save final HTML
      - Update checkpoint to row_idx+1
    """
    if not os.path.exists(csv_file):
        logger.error(f"CSV file not found: {csv_file}")
        return

    df = pd.read_csv(csv_file)
    total_rows = len(df)
    logger.info(f"[{csv_file}] has {total_rows} total rows.")

    # Read the current checkpoint for this CSV
    start_idx = get_checkpoint_value(csv_file)
    if start_idx >= total_rows:
        logger.info(f"[{csv_file}] Already completed all {total_rows} rows. Skipping.")
        return

    logger.info(f"[{csv_file}] Resuming from row index {start_idx} (0-based).")

    # For the directory structure, we won't create them all here.
    # We'll create them row-by-row as needed: BASE_OUTPUT_DIR/court/year/month/
    with SB(uc=True, headless=HEADLESS) as sb:
        for row_idx in range(start_idx, total_rows):
            row = df.iloc[row_idx]

            court = str(row["court"]).strip()
            year = str(row["year"]).strip()
            month = str(row["month"]).strip()
            url = str(row["url"]).strip()

            doc_id = url.rstrip("/").split("/")[-1]

            # Build subdirectory: <base>/<court>/<year>/<month>
            court_dir = os.path.join(BASE_OUTPUT_DIR, court)
            year_dir = os.path.join(court_dir, year)
            month_dir = os.path.join(year_dir, month)
            os.makedirs(month_dir, exist_ok=True)

            html_filename = f"{doc_id}.html"
            html_path = os.path.join(month_dir, html_filename)

            logger.info(f"\n[{csv_file}] Row {row_idx+1}/{total_rows}: {url}")
            logger.info(f"Saving to => {html_path}")

            try:
                # 1) Bypass Cloudflare
                if not open_kanoon_page(sb, url, max_retries=MAX_RETRIES):
                    logger.error(f"Skipping {url} (Cloudflare/page load failure)")
                else:
                    # 2) Click "Print it on a file/printer" if found
                    clicked = click_print_button(sb)
                    # 3) Save HTML
                    if not save_as_html(sb, html_path):
                        logger.error(f"Skipping {url} due to HTML save failure")
                    else:
                        logger.info(f"Successfully saved HTML for {url}")

            except Exception as ex:
                logger.error(f"ERROR processing {url}: {ex}")

            # IMPORTANT: Update checkpoint so we don't re-download on restart
            update_checkpoint_value(csv_file, row_idx + 1)

    logger.info(f"[{csv_file}] Completed up to row {row_idx+1}")


# -------------------------------------------------------------------
# 5) MAIN: Launch Threads with 5-Second Stagger
# -------------------------------------------------------------------
def main():
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        futures = []
        for csv_file in CSV_FILES:
            future = executor.submit(process_csv, csv_file)
            futures.append(future)
            # Stagger the thread starts by 5 seconds
            time.sleep(5)

        for f in concurrent.futures.as_completed(futures):
            try:
                f.result()
            except Exception as exc:
                logger.error(f"A thread encountered an exception: {exc}")


if __name__ == "__main__":
    main()
