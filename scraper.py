import os
import time
import json
import logging
import threading
import pandas as pd
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
from seleniumbase import SB  # or "from seleniumbase import BaseCase" if needed


class IndianKanoonScraper:
    def __init__(self, start_year=2020, end_year=2024, max_workers=5):
        self.start_year = start_year
        self.end_year = end_year
        self.checkpoint_file = "scraping_checkpoint.json"
        self.setup_logging()

        # A threading lock to protect read/write to the checkpoint
        self.checkpoint_lock = threading.Lock()
        self.max_workers = max_workers

        self.month_names = [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ]

    def setup_logging(self):
        """Setup logging configuration."""
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[logging.FileHandler("scraper.log"), logging.StreamHandler()],
        )
        self.logger = logging.getLogger(__name__)

    def load_checkpoint(self):
        """Thread-safe load of the checkpoint file, returning a dict keyed by court."""
        with self.checkpoint_lock:
            if (
                not os.path.exists(self.checkpoint_file)
                or os.stat(self.checkpoint_file).st_size == 0
            ):
                return {}
            try:
                with open(self.checkpoint_file, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, ValueError):
                self.logger.warning(
                    "Checkpoint file is empty/corrupted. Resetting checkpoint."
                )
                return {}

    def save_checkpoint(self, checkpoint_data):
        """Thread-safe save of the entire checkpoint dictionary."""
        with self.checkpoint_lock:
            with open(self.checkpoint_file, "w") as f:
                json.dump(checkpoint_data, f, indent=2)

    def bypass_cloudflare(self, sb, url):
        """Handle Cloudflare verification with multiple reconnect attempts."""
        self.logger.info(
            f"Opening {url} with automatic reconnect to bypass Cloudflare..."
        )
        sb.uc_open_with_reconnect(url, 3)

        try:
            for _ in range(10):
                if "indiankanoon.org" in sb.get_current_url():
                    self.logger.info("Successfully bypassed Cloudflare!")
                    return
                time.sleep(1)

            # Attempt direct verification steps
            if sb.is_element_visible('input[value*="Verify"]'):
                self.logger.info("Clicking Cloudflare verification checkbox...")
                sb.uc_click('input[value*="Verify"]')
                time.sleep(5)
            elif sb.is_element_visible("iframe"):
                self.logger.info("Detected an iframe, solving CAPTCHA...")
                sb.uc_gui_click_captcha()
                time.sleep(5)

            sb.wait_for_element_visible('img[alt="Indian Kanoon"]', timeout=15)
            self.logger.info("Page loaded successfully after Cloudflare verification.")

        except Exception as e:
            self.logger.error(f"Cloudflare detection failed: {str(e)}")
            raise Exception("Cloudflare detected the bot!") from e

    def get_month_links(self, sb):
        """Extract month links from the page."""
        months = []
        for link in sb.find_elements("tag name", "a"):
            text = link.text.strip()
            if text in self.month_names:
                months.append({"name": text, "url": link.get_attribute("href")})
        return months

    def save_links_batch(self, links, csv_file):
        """Append a batch of links to the court-specific CSV file."""
        if not links:
            return
        df = pd.DataFrame(links)
        write_header = not os.path.exists(csv_file)
        df.to_csv(csv_file, mode="a", header=write_header, index=False)
        self.logger.info(f"Saved {len(links)} links to {csv_file}")

    def process_month_page(self, sb, month_data, court_name, year, csv_file):
        """Process all judgment links for a month, paginating until no 'Next' link."""
        self.logger.info(f"[{court_name}] Processing {month_data['name']} {year}...")
        current_url = month_data["url"]
        month_links = []

        while current_url:
            try:
                sb.get(current_url)
                self.logger.info(
                    f"[{court_name}] Loaded {month_data['name']} {year} page."
                )

                # Collect doc links
                links_this_page = []
                for element in sb.find_elements("tag name", "a"):
                    href = element.get_attribute("href")
                    text = element.text.strip()
                    if "/doc/" in href and text:
                        links_this_page.append(
                            {
                                "court": court_name,
                                "year": year,
                                "month": month_data["name"],
                                "title": text,
                                "url": href,
                            }
                        )

                if links_this_page:
                    month_links.extend(links_this_page)
                    self.logger.info(
                        f"[{court_name}] Found {len(links_this_page)} links on this page."
                    )
                    # Save in batches of 100
                    if len(month_links) >= 100:
                        self.save_links_batch(month_links, csv_file)
                        month_links = []

                # Find "Next" link
                next_page = None
                for link in sb.find_elements("tag name", "a"):
                    if link.text.strip().lower() == "next":
                        next_page = link.get_attribute("href")
                        break

                if next_page:
                    current_url = next_page
                    time.sleep(2)
                else:
                    # Save leftover links
                    if month_links:
                        self.save_links_batch(month_links, csv_file)
                    current_url = None

            except Exception as e:
                self.logger.error(
                    f"[{court_name}] Error in month {month_data['name']} {year}: {str(e)}"
                )
                if month_links:
                    self.save_links_batch(month_links, csv_file)
                break

    def scrape_court(self, court_data):
        """
        Scrape all years/months for a single court in one thread.
        Creates/updates a CSV named <court_name>.csv
        Updates checkpoint as we go.
        """
        court_name = court_data["court"]
        court_url = court_data["url"]
        csv_file = f"{court_name}.csv"

        # Load checkpoint for this court
        checkpoint_data = self.load_checkpoint()
        if court_name not in checkpoint_data:
            checkpoint_data[court_name] = {
                "last_year": None,
                "last_month": None,
                "is_done": False,
            }

        court_checkpoint = checkpoint_data[court_name]
        if court_checkpoint.get("is_done", False):
            self.logger.info(f"[{court_name}] Already marked done. Skipping.")
            return

        last_year = court_checkpoint["last_year"]
        last_month = court_checkpoint["last_month"]

        try:
            with SB(uc=True) as sb:
                for year in range(self.start_year, self.end_year + 1):
                    # Skip entire years < last_year
                    if last_year is not None and year < last_year:
                        continue

                    # Bypass Cloudflare and fetch month links
                    year_url = urljoin(court_url, f"{year}/")
                    self.bypass_cloudflare(sb, year_url)
                    month_links = self.get_month_links(sb)
                    if not month_links:
                        self.logger.warning(
                            f"[{court_name}] No months found for year {year}. Skipping."
                        )
                        continue

                    # Figure out which month index to start from if continuing partial year
                    start_month_idx = 0
                    if last_year == year and last_month in self.month_names:
                        skip_idx = self.month_names.index(last_month)
                        start_month_idx = skip_idx + 1
                        if start_month_idx > 11:
                            # We already finished this entire year
                            continue

                    # Process months from start_month_idx onward
                    for mdata in month_links[start_month_idx:]:
                        self.process_month_page(sb, mdata, court_name, year, csv_file)
                        # Update checkpoint after finishing each month
                        court_checkpoint["last_year"] = year
                        court_checkpoint["last_month"] = mdata["name"]
                        self.save_checkpoint(checkpoint_data)
                        last_year = year
                        last_month = mdata["name"]

                # Mark done once we've processed all years
                court_checkpoint["is_done"] = True
                self.save_checkpoint(checkpoint_data)
                self.logger.info(f"[{court_name}] Scraping complete.")

        except Exception as ex:
            self.logger.error(f"[{court_name}] Critical error: {str(ex)}")

    def scrape_all(self):
        """
        Main scraping function:
        1) Read 'court_links.csv'
        2) Prioritize undone courts
        3) Spawn up to max_workers threads
        4) Handle Ctrl+C (KeyboardInterrupt) gracefully
        """
        # First, read the court links
        courts_df = pd.read_csv("court_links.csv")

        # Load checkpoint so we can see which are done vs. not done
        checkpoint_data = self.load_checkpoint()

        # Tag each row with is_done status from the checkpoint
        def is_done_for_row(row):
            c_name = row["court"]
            if c_name not in checkpoint_data:
                return False
            return checkpoint_data[c_name].get("is_done", False)

        courts_df["is_done"] = courts_df.apply(is_done_for_row, axis=1)

        # Sort so that is_done == False appear first
        courts_df = courts_df.sort_values(by="is_done", ascending=True)

        self.logger.info(
            f"Total Courts: {len(courts_df)}. "
            f"Undone: {len(courts_df[courts_df['is_done'] == False])}, "
            f"Done: {len(courts_df[courts_df['is_done'] == True])}"
        )

        # Optionally filter out the done courts so we don't even schedule them:
        # courts_df = courts_df[courts_df['is_done'] == False]

        # We'll catch KeyboardInterrupt so we can gracefully shut down
        executor = ThreadPoolExecutor(max_workers=self.max_workers)
        futures = []
        try:
            # Submit tasks
            for _, row in courts_df.iterrows():
                futures.append(executor.submit(self.scrape_court, row))

            # As tasks complete, we can catch exceptions
            for f in as_completed(futures):
                try:
                    f.result()
                except Exception as e:
                    self.logger.error(f"Threaded task error: {str(e)}")
        except KeyboardInterrupt:
            self.logger.info("CTRL+C detected! Attempting graceful shutdown...")
            # Optionally, cancel any outstanding futures
            for f in futures:
                f.cancel()
        finally:
            # Shutdown the executor, waiting on tasks that aren’t cancelled
            executor.shutdown(wait=False)
            # We could do a final checkpoint save if needed
            # But since we save after each month, we’re likely good:
            self.logger.info("Shutdown complete. Checkpoints should be up to date.")


if __name__ == "__main__":
    scraper = IndianKanoonScraper(start_year=2020, end_year=2024, max_workers=2)
    scraper.scrape_all()
