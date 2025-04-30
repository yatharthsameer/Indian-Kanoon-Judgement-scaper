import os
import json
import time
import logging
import threading
from datetime import datetime, timedelta
from urllib.parse import quote_plus
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from seleniumbase import SB

# ----------------------- Global Settings ----------------------- #
START_YEAR = 2024  # <=== change this at will
END_YEAR = 2024  # scrape up to this year (inclusive)
INTERVAL_DAYS = 3  # 3‑day windows (1,2,3) – increase if desired
MAX_WORKERS = 1  # parallel courts

COURT_CSV = "court_links.csv"  # must contain a column named "court_id"
CHECKPOINT_FILE = "date_scraper_checkpoint.json"
LOG_FILE = "date_scraper.log"

# ---------------------------------------------------------------- #


class DateRangeScraper:
    def __init__(self):
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
        self._setup_logging()
        self.check_lock = threading.Lock()

    # --------------- Logging & Checkpoint helpers --------------- #
    def _setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()],
        )
        self.logger = logging.getLogger("scraper")

    def _load_checkpoint(self):
        with self.check_lock:
            if not os.path.isfile(CHECKPOINT_FILE):
                return {}
            try:
                with open(CHECKPOINT_FILE, "r") as f:
                    return json.load(f)
            except Exception:
                self.logger.warning("Checkpoint corrupt – starting fresh")
                return {}

    def _save_checkpoint(self, data):
        with self.check_lock:
            with open(CHECKPOINT_FILE, "w") as f:
                json.dump(data, f, indent=2)

    # ---------------- Cloudflare bypass ----------------- #
    def _bypass_cloudflare(self, sb, url):
        self.logger.info(f"Opening {url}")
        sb.uc_open_with_reconnect(url, 3)
        # Quick success check
        for _ in range(10):
            if "indiankanoon.org" in sb.get_current_url():
                return
            time.sleep(1)
        # Fallback – try clicking verify
        try:
            if sb.is_element_visible('input[value*="Verify"]'):
                sb.uc_click('input[value*="Verify"]')
                time.sleep(4)
            elif sb.is_element_visible("iframe"):
                sb.uc_gui_click_captcha()
                time.sleep(6)
        except Exception:
            pass

    # ---------------- CSV Saving ----------------- #
    def _save_links(self, links, csv_path):
        if not links:
            return
        df = pd.DataFrame(links)
        header = not os.path.isfile(csv_path)
        df.to_csv(csv_path, mode="a", header=header, index=False)
        self.logger.info(f"Saved {len(links)} links -> {csv_path}")

    # --------------- Core scraping utilities --------------- #
    @staticmethod
    def _fmt_date(dt: datetime) -> str:
        """Return D-M-YYYY (no leading zeros) as IK expects."""
        return f"{dt.day}-{dt.month}-{dt.year}"

    def _build_search_url(
        self, court_id: str, from_dt: datetime, to_dt: datetime
    ) -> str:
        q = f"doctypes:{court_id} fromdate:{self._fmt_date(from_dt)} todate: {self._fmt_date(to_dt)}"
        return f"https://indiankanoon.org/search/?formInput={quote_plus(q)}"

    def _scrape_interval(
        self, sb, court_id: str, from_dt: datetime, to_dt: datetime, csv_path: str
    ):
        url = self._build_search_url(court_id, from_dt, to_dt)
        self.logger.info(
            f"[{court_id}] {self._fmt_date(from_dt)} → {self._fmt_date(to_dt)} | {url}"
        )
        self._bypass_cloudflare(sb, url)

        links_batch = []
        while True:
            try:
                # Collect links on current page
                for a in sb.find_elements("tag name", "a"):
                    href = a.get_attribute("href")
                    if href and "/doc/" in href:
                        title = a.text.strip()
                        if not title:
                            continue
                        yr = from_dt.year
                        month = self.month_names[from_dt.month - 1]
                        links_batch.append(
                            {
                                "court": court_id,
                                "year": yr,
                                "month": month,
                                "title": title,
                                "url": href,
                            }
                        )
                if len(links_batch) >= 100:
                    self._save_links(links_batch, csv_path)
                    links_batch = []

                # pagination
                next_link = None
                for a in sb.find_elements("tag name", "a"):
                    if a.text.strip().lower() == "next":
                        next_link = a.get_attribute("href")
                        break
                if next_link:
                    sb.get(next_link)
                    time.sleep(1)
                else:
                    break
            except Exception as e:
                self.logger.error(f"[{court_id}] error during page scrape: {e}")
                break
        # final flush
        self._save_links(links_batch, csv_path)

    # --------------- Per‑court worker --------------- #
    def _worker(self, court_id: str):
        csv_path = f"{court_id}.csv"
        cp = self._load_checkpoint()
        last_date_str = cp.get(court_id, {}).get("last_from_date")
        if last_date_str:
            start_dt = datetime.strptime(last_date_str, "%Y-%m-%d") + timedelta(
                days=INTERVAL_DAYS
            )
        else:
            start_dt = datetime(START_YEAR, 1, 1)
        end_dt_global = datetime(END_YEAR, 12, 31)

        with SB(uc=True, headless=False) as sb:
            cur = start_dt
            while cur <= end_dt_global:
                to_dt = cur + timedelta(days=INTERVAL_DAYS - 1)
                if to_dt > end_dt_global:
                    to_dt = end_dt_global
                try:
                    self._scrape_interval(sb, court_id, cur, to_dt, csv_path)
                    # checkpoint update
                    cp.setdefault(court_id, {})["last_from_date"] = cur.strftime(
                        "%Y-%m-%d"
                    )
                    self._save_checkpoint(cp)
                except Exception as ex:
                    self.logger.error(f"[{court_id}] critical interval error: {ex}")
                    break
                cur += timedelta(days=INTERVAL_DAYS)
        self.logger.info(f"[{court_id}] done up to {end_dt_global.date()}")

    # --------------- Orchestrator --------------- #
    def run(self):
        courts_df = pd.read_csv(COURT_CSV)  # must have court_id column
        if "court_id" not in courts_df.columns:
            raise ValueError("courts.csv must contain a 'court_id' column")
        court_ids = courts_df["court_id"].unique().tolist()
        self.logger.info(f"Loaded {len(court_ids)} courts. Starting threads …")

        pool = ThreadPoolExecutor(max_workers=MAX_WORKERS)
        futures = [pool.submit(self._worker, cid) for cid in court_ids]
        try:
            for f in as_completed(futures):
                f.result()
        except KeyboardInterrupt:
            self.logger.info("CTRL‑C detected – shutting down …")
            for f in futures:
                f.cancel()
        finally:
            pool.shutdown(wait=False)
            self.logger.info("All workers finished.")


if __name__ == "__main__":
    DateRangeScraper().run()
