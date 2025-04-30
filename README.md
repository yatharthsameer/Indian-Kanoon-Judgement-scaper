# Court Judgement Scraper

## Setup

### Environment Variables
```bash
export CHROME_BINARY=~/chrome/opt/google/chrome/google-chrome
export CHROMEDRIVER_BINARY=~/chromedriver/chromedriver
export PATH=$HOME/chrome/opt/google/chrome:$HOME/chromedriver:$PATH
```

### Verify Installation
```bash
$CHROME_BINARY --version
$CHROMEDRIVER_BINARY --version
```

## Usage

### Step 1: Run the Scraper
```bash
nohup python3 scraper.py > log.txt 2>&1 &
```
This will collect links to the documents.

### Step 2: Clean the Data
Before proceeding to download, run the duplicate removal script on the judgement links:
```bash
python remove_duplicates.py
```
This step is crucial to ensure we don't download duplicate documents.

### Step 3: Download Documents
Run the download script:
```bash
python download.py
```

#### Download Configuration
- You can modify the list of courts to download in `download.py`
- Configure the number of threads for parallel downloads
- **Important**: Do not use more than 4 threads

## Data Cleaning Tools

### Removing Duplicates

The `remove_duplicates.py` script helps you remove duplicate rows from CSV files. It can process individual files or entire directories of CSV files.

#### Features:
- Removes duplicate rows from CSV files
- Processes all CSV files in a directory and its subdirectories
- Provides statistics about the number of duplicates removed
- Can overwrite existing files or save to new locations

#### Usage:

1. **Process all CSV files in current directory:**
   ```bash
   python remove_duplicates.py
   ```

2. **Process a specific CSV file:**
   ```python
   from remove_duplicates import remove_duplicates_from_csv
   
   # Overwrite the original file
   remove_duplicates_from_csv("path/to/your/file.csv")
   
   # Save to a new file
   remove_duplicates_from_csv("path/to/your/file.csv", "path/to/output.csv")
   ```

3. **Process all CSV files in a specific directory:**
   ```python
   from remove_duplicates import process_directory
   
   process_directory("path/to/your/directory")
   ```

#### Requirements:
- Python 3.x
- pandas

#### Output:
The script will print statistics for each processed file:
- Initial number of rows
- Final number of rows
- Number of duplicates removed 