from scraper import IndianKanoonScraper
import pandas as pd
import os
import logging

class Scraper2020(IndianKanoonScraper):
    def scrape_all(self):
        """Override to only scrape 2020 data"""
        try:
            # Read court links
            courts_df = pd.read_csv('court_links.csv')
            self.logger.info(f"\nFound {len(courts_df)} courts")
            
            # Process each court for 2020 only
            for idx, court in courts_df.iterrows():
                self.logger.info(f"\nProcessing court {idx + 1}/{len(courts_df)}: {court['court']}")
                self.process_year(court, 2020, {'last_month': None})
                
        except Exception as e:
            self.logger.error(f"Error in test: {str(e)}")
            raise

def main():
    # Clean up previous test files
    test_files = ['scraping_checkpoint.json', 'all_judgment_links.csv', 'scraper.log']
    for file in test_files:
        if os.path.exists(file):
            os.remove(file)
    
    # Initialize test scraper for 2020 only
    scraper = Scraper2020(start_year=2020, end_year=2020)
    scraper.logger.info("Starting 2020 data scrape...")
    
    try:
        # Run test
        scraper.scrape_all()
        
        # Verify results
        if os.path.exists('all_judgment_links.csv'):
            df = pd.read_csv('all_judgment_links.csv')
            scraper.logger.info(f"\nSuccessfully collected {len(df)} judgment links")
            scraper.logger.info("\nSummary by court:")
            summary = df.groupby('court')['url'].count()
            scraper.logger.info(summary)
            
            scraper.logger.info("\nSample of collected data:")
            scraper.logger.info(df[['court', 'month', 'url']].head())
        else:
            scraper.logger.error("No output file was created")
            
    except Exception as e:
        scraper.logger.error(f"Test failed: {str(e)}")
        raise

if __name__ == "__main__":
    main()
