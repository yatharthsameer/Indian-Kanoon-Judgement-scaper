from seleniumbase import SB
import pandas as pd
from urllib.parse import urljoin
import time
import json
import os
import logging
from contextlib import contextmanager


class IndianKanoonScraper:
    def __init__(self, start_year=2020, end_year=2024):
        self.start_year = start_year
        self.end_year = end_year
        self.judgment_links = []
        self.checkpoint_file = "scraping_checkpoint.json"
        self.output_file = "all_judgment_links.csv"
        self.setup_logging()

    def setup_logging(self):
        """Setup logging configuration"""
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[logging.FileHandler("scraper.log"), logging.StreamHandler()],
        )
        self.logger = logging.getLogger(__name__)

    @contextmanager
    def create_driver(self):
        """Create a browser session using SeleniumBase to bypass Cloudflare"""
        try:
            with SB(uc=True) as sb:  # Use undetected ChromeDriver
                self.logger.info(
                    "Opening browser with automatic reconnect to bypass Cloudflare..."
                )
                yield sb  # Pass the SeleniumBase driver

        except Exception as e:
            self.logger.error(f"Failed to create Chrome driver: {str(e)}")
            raise

    def load_checkpoint(self):
        """Load the last saved checkpoint"""
        if os.path.exists(self.checkpoint_file):
            with open(self.checkpoint_file, "r") as f:
                return json.load(f)
        return {
            "last_court": None,
            "last_year": None,
            "last_month": None,
            "processed_courts": [],
        }

    def save_checkpoint(self, court, year, month):
        """Save current progress to checkpoint"""
        checkpoint = {
            "last_court": court,
            "last_year": year,
            "last_month": month,
            "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "processed_courts": self.get_processed_courts(),
        }
        with open(self.checkpoint_file, "w") as f:
            json.dump(checkpoint, f, indent=2)

    def get_processed_courts(self):
        """Get list of fully processed courts"""
        if os.path.exists(self.output_file):
            df = pd.read_csv(self.output_file)
            return df["court"].unique().tolist()
        return []

    def save_links_batch(self, links, mode="a"):
        """Save a batch of links to CSV"""
        if not links:
            return
        df = pd.DataFrame(links)
        header = not os.path.exists(self.output_file) if mode == "a" else True
        df.to_csv(self.output_file, mode=mode, header=header, index=False)
        self.logger.info(f"Saved {len(links)} links to {self.output_file}")

    def get_month_links(self, driver):
        """Extract month links from the page"""
        months = []
        month_names = [
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

        for link in driver.find_elements("tag name", "a"):
            text = link.text.strip()
            if text in month_names:
                months.append({"name": text, "url": link.get_attribute("href")})

        return months

    def bypass_cloudflare(self, sb, url):
        """Handle Cloudflare verification, handling both CAPTCHA and auto-redirect cases."""
        self.logger.info(
            f"Opening {url} with automatic reconnect to bypass Cloudflare..."
        )
        sb.uc_open_with_reconnect(url, 3)  # Try multiple reconnect attempts

        try:
            # Check if redirection has already happened (successful verification)
            for _ in range(10):  # Retry for a few seconds
                if "indiankanoon.org" in sb.get_current_url():
                    self.logger.info("Successfully bypassed Cloudflare! Proceeding...")
                    return  # Exit function if we are on the correct page
                time.sleep(1)

            # If still on verification page, try interacting
            if sb.is_element_visible('input[value*="Verify"]'):
                self.logger.info("Clicking on Cloudflare verification checkbox...")
                sb.uc_click('input[value*="Verify"]')
                time.sleep(5)  # Give time for verification

            elif sb.is_element_visible("iframe"):
                self.logger.info(
                    "Detected an iframe. Attempting to switch and solve CAPTCHA..."
                )
                sb.uc_gui_click_captcha()
                time.sleep(5)  # Allow some time for CAPTCHA processing

            # Check final verification (allowing longer time)
            sb.wait_for_element_visible('img[alt="Indian Kanoon"]', timeout=15)
            self.logger.info("Page loaded successfully after Cloudflare verification.")

        except Exception as e:
            self.logger.error(f"Cloudflare detection failed: {str(e)}")
            raise Exception("Cloudflare detected the bot!")

    def process_month_page(self, sb, month_data, court_data):
        """Process all judgment links for a month"""
        self.logger.info(f"Processing {month_data['name']}...")
        current_url = month_data["url"]
        month_links = []

        while current_url:
            try:
                self.logger.info(f"Processing page for {month_data['name']}...")
                sb.get(current_url)

                links = []
                for element in sb.find_elements("tag name", "a"):
                    href = element.get_attribute("href")
                    text = element.text.strip()
                    if "/doc/" in href and text:
                        links.append(
                            {
                                "court": court_data["court"],
                                "year": self.start_year,  # Update dynamically if needed
                                "month": month_data["name"],
                                "title": text,
                                "url": href,
                            }
                        )

                if links:
                    month_links.extend(links)
                    self.logger.info(f"Found {len(links)} judgment links")

                    if len(month_links) >= 100:
                        self.save_links_batch(month_links)
                        month_links = []

                next_page = None
                for link in sb.find_elements("tag name", "a"):
                    if link.text.strip().lower() == "next":
                        next_page = link.get_attribute("href")
                        break

                if next_page:
                    current_url = next_page
                    time.sleep(2)  # Be polite to the server
                else:
                    if month_links:
                        self.save_links_batch(month_links)
                    current_url = None

            except Exception as e:
                self.logger.error(f"Error processing {month_data['name']}: {str(e)}")
                if month_links:
                    self.save_links_batch(month_links)
                break

    def process_year(self, court_data, year, checkpoint):
        """Process a specific year"""
        self.logger.info(f"\nProcessing {court_data['court']} for year {year}...")

        with self.create_driver() as sb:
            year_url = urljoin(court_data["url"], f"{year}/")
            self.bypass_cloudflare(sb, year_url)

            month_links = self.get_month_links(sb)
            if not month_links:
                self.logger.warning(
                    f"No month links found for {court_data['court']} in {year}"
                )
                return

            for month_data in month_links:
                self.process_month_page(sb, month_data, court_data)
                self.save_checkpoint(court_data["court"], year, month_data["name"])

    def scrape_all(self):
        """Main scraping function"""
        courts_df = pd.read_csv("court_links.csv")
        checkpoint = self.load_checkpoint()

        if checkpoint["processed_courts"]:
            courts_df = courts_df[
                ~courts_df["court"].isin(checkpoint["processed_courts"])
            ]

        for _, court in courts_df.iterrows():
            self.logger.info(f"\nProcessing court: {court['court']}")

            for year in range(self.start_year, self.end_year + 1):
                if checkpoint["last_year"] and year <= checkpoint["last_year"]:
                    continue

                self.process_year(court, year, checkpoint)
                self.save_checkpoint(court["court"], year, None)

            checkpoint["processed_courts"].append(court["court"])
            self.save_checkpoint(court["court"], None, None)


if __name__ == "__main__":
    scraper = IndianKanoonScraper()
    scraper.scrape_all()
