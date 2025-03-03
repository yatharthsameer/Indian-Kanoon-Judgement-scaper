import os
import time
import logging
import base64
import pandas as pd
import concurrent.futures
from seleniumbase import SB  # pip install seleniumbase

# -------------------------------------------------------------------
# 1) HARDCODED LIST OF (CSV_FILE, OUTPUT_DIR) PAIRS
# -------------------------------------------------------------------
CSV_FILES = [
    ("Sikkim High Court.csv", "Sikkim_High_Court"),
    ("Bombay High Court.csv", "Bombay_High_Court"),
    ("Delhi High Court.csv", "Delhi_High_Court"),
    ("Karnataka High Court.csv", "Karnataka_High_Court"),
    ("Madras High Court.csv", "Madras_High_Court"),
    ("Gujarat High Court.csv", "Gujarat_High_Court"),
    # ("Calcutta High Court.csv", "Calcutta_High_Court"),
    # ("Rajasthan High Court.csv", "Rajasthan_High_Court"),
    # ("Patna High Court.csv", "Patna_High_Court"),
    # ("Andhra Pradesh High Court.csv", "Andhra_Pradesh_High_Court"),
    # ("Allahabad High Court.csv", "Allahabad_High_Court"),
    # ("Punjab-Haryana High Court.csv", "Punjab_Haryana_High_Court"),
    # ("Jharkhand High Court.csv", "Jharkhand_High_Court"),
    # ("Kerala High Court.csv", "Kerala_High_Court"),
    # ("Orissa High Court.csv", "Orissa_High_Court"),
    # ("Chhattisgarh High Court.csv", "Chhattisgarh_High_Court"),
    # ("Jammu-Kashmir High Court.csv", "Jammu_Kashmir_High_Court"),
    # ("Himachal Pradesh High Court.csv", "Himachal_Pradesh_High_Court"),
    # Add more as needed
]

HEADLESS = True  # Toggle headless mode
MAX_RETRIES = 4  # Number of times to attempt bypassing Cloudflare
MAX_THREADS = 6  # Maximum concurrent threads

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


# -------------------------------------------------------------------
# 2) HELPER FUNCTIONS (same as your single-thread code)
# -------------------------------------------------------------------
def open_kanoon_page(sb, url, max_retries=3):
    """Tries up to 'max_retries' times to fully load the final doc page,
    which we detect by waiting for some 'print' button or unique element."""
    for attempt in range(1, max_retries + 1):
        logger.info(f"[Attempt {attempt}] Opening {url} with reconnect...")
        sb.uc_open_with_reconnect(url, 3)

        # Give time for Cloudflare's "Verifying…" step
        time.sleep(3)

        # Check for typical Cloudflare challenge elements
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

        # Poll up to 10s for the real doc's "print" button or link
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
    """Attempts to click the 'Print it on a file/printer' button/link."""
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
        elif sb.is_element_visible("button:contains('Print it on a file/printer')"):
            logger.info("Clicking 'Print it on a file/printer' button (CSS)...")
            sb.click("button:contains('Print it on a file/printer')")
            return True
        elif sb.is_element_visible("a:contains('Print it on a file/printer')"):
            logger.info("Clicking 'Print it on a file/printer' link (CSS)...")
            sb.click("a:contains('Print it on a file/printer')")
            return True
        else:
            logger.warning("No 'Print it on a file/printer' button/link found.")
            return False
    except Exception as e:
        logger.error(f"Error clicking print button: {e}")
        return False


def save_as_pdf(sb, pdf_path):
    """Saves the current page as a PDF using Chrome's DevTools Protocol."""
    try:
        logger.info(f"Saving PDF => {pdf_path}")
        time.sleep(5)  # Wait for the print view to fully load

        pdf_data = sb.driver.execute_cdp_cmd(
            "Page.printToPDF",
            {
                "printBackground": True,
                "paperWidth": 8.5,
                "paperHeight": 11,
                "marginTop": 0.4,
                "marginBottom": 0.4,
                "marginLeft": 0.4,
                "marginRight": 0.4,
                "scale": 0.9,
            },
        )

        with open(pdf_path, "wb") as f:
            f.write(base64.b64decode(pdf_data["data"]))

        logger.info(f"Saved {pdf_path} successfully.")
        return True
    except Exception as e:
        logger.error(f"Error saving PDF: {e}")
        return False


# -------------------------------------------------------------------
# 3) FUNCTION TO PROCESS A SINGLE CSV FILE (runs in one thread)
# -------------------------------------------------------------------
def process_csv(csv_file, output_dir):
    """Reads `csv_file`, scrapes each URL, and saves PDFs into `output_dir`."""
    try:
        if not os.path.exists(csv_file):
            logger.error(f"CSV file not found: {csv_file}")
            return

        os.makedirs(output_dir, exist_ok=True)
        df = pd.read_csv(csv_file)

        logger.info(f"Starting processing for {csv_file} -> {output_dir}")
        with SB(uc=True, headless=HEADLESS) as sb:
            for idx, row in df.iterrows():
                court = str(row["court"])
                year = str(row["year"])
                month = str(row["month"])[:3]  # e.g. "Dec"
                url = str(row["url"])

                doc_id = url.rstrip("/").split("/")[-1]
                pdf_filename = f"{court}_{year}_{month}_{doc_id}.pdf".replace(" ", "_")
                pdf_path = os.path.join(output_dir, pdf_filename)

                logger.info(f"\n--- Processing: {court}, {year}, {month}, {url} ---")
                try:
                    if not open_kanoon_page(sb, url, max_retries=MAX_RETRIES):
                        logger.error(
                            f"Skipping {url} due to Cloudflare/page load failure"
                        )
                        continue

                    if not click_print_button(sb):
                        logger.error(
                            f"Skipping {url} due to print button click failure"
                        )
                        continue

                    if not save_as_pdf(sb, pdf_path):
                        logger.error(f"Skipping {url} due to PDF save failure")
                        continue

                    logger.info(f"Successfully processed {url}")

                except Exception as ex:
                    logger.error(f"ERROR processing {url}: {ex}")

        logger.info(f"Finished processing for {csv_file}")

    except Exception as e:
        logger.error(f"Unexpected error in thread for {csv_file}: {e}")


# -------------------------------------------------------------------
# 4) MAIN FUNCTION: LAUNCH THREADS WITH A 5-SECOND STAGGER
# -------------------------------------------------------------------
def main():
    # List of (csv_file, output_dir) to process
    csv_files = [
        ("Sikkim High Court.csv", "Sikkim_High_Court"),
        ("Bombay High Court.csv", "Bombay_High_Court"),
        ("Delhi High Court.csv", "Delhi_High_Court"),
        # etc.
    ]

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        futures = []
        for csv_file, out_dir in csv_files:
            # Submit a thread to process this CSV
            futures.append(executor.submit(process_csv, csv_file, out_dir))
            # Stagger the thread starts by sleeping 5 seconds before the next
            time.sleep(5)

        # Optionally wait for them to complete
        for future in concurrent.futures.as_completed(futures):
            try:
                future.result()  # Raises any exception from process_csv()
            except Exception as exc:
                logger.error(f"A thread encountered an exception: {exc}")


if __name__ == "__main__":
    main()
