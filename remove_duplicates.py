import pandas as pd
import os
from pathlib import Path

# List of CSV files to process
CSV_FILES_TO_PROCESS = [
    "supremecourt.csv",  # Add your CSV files here
]


def remove_duplicates_from_csv(input_file, output_file=None):
    """
    Remove duplicate rows from a CSV file and save the result.

    Args:
        input_file (str): Path to the input CSV file
        output_file (str, optional): Path to save the deduplicated CSV file.
                                   If None, will overwrite the input file.
    """
    # Read the CSV file
    df = pd.read_csv(input_file)

    # Get initial row count
    initial_rows = len(df)

    # Remove duplicates
    df_deduplicated = df.drop_duplicates()

    # Get final row count
    final_rows = len(df_deduplicated)

    # Calculate number of duplicates removed
    duplicates_removed = initial_rows - final_rows

    # Save the deduplicated data
    if output_file is None:
        output_file = input_file

    df_deduplicated.to_csv(output_file, index=False)

    print(f"Processed {input_file}:")
    print(f"Initial rows: {initial_rows}")
    print(f"Final rows: {final_rows}")
    print(f"Duplicates removed: {duplicates_removed}")
    print("-" * 50)



if __name__ == "__main__":
    # Process only the specified CSV files
    for csv_file in CSV_FILES_TO_PROCESS:
        if os.path.exists(csv_file):
            remove_duplicates_from_csv(csv_file)
        else:
            print(f"Warning: File {csv_file} not found")
