import pandas as pd

# Hardcoded list of CSV files to process
csv_files = [
    "Jammu & Kashmir High Court.csv",
    "Jammu & Kashmir High Court - Srinagar Bench.csv",
    "Supreme Court of India.csv",
    "Supreme Court - Daily Orders.csv",
]  # Add more filenames as needed


def remove_url_duplicates(file_path):
    try:
        # Read the CSV file into a pandas DataFrame
        df = pd.read_csv(file_path)

        # Drop duplicates based on the 'url' column, keeping only the first occurrence
        df_unique = df.drop_duplicates(subset="url", keep="first")

        # Overwrite the original CSV with the cleaned DataFrame
        df_unique.to_csv(file_path, index=False)
        print(f"Duplicates removed. Updated CSV saved to {file_path}")

    except Exception as e:
        print(f"Error processing {file_path}: {e}")


if __name__ == "__main__":
    for csv_file in csv_files:
        remove_url_duplicates(csv_file)
