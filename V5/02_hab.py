"""
HAB Raw Combiner (SIMPLIFIED)

This script ONLY:
• Loads Historical months (Jan–Jun)
• Loads Previous month (July)
• Loads Current month (Aug)
• Appends everything together
• Adds ONE column -> data_lineage
• Saves ONE combined CSV

Reads monthly source files from S3 (falls back to local /data if not found).
Also pushes the final combined CSV to S3 as "hab_combined".

NO extra columns.
NO rules.
NO trust score.
NO timestamps.
NO hashes.
NO parquet.
"""

import logging
import os
import sys
import argparse
import pandas as pd

# Initialize logging IMMEDIATELY before any other calls
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", force=True)

# Make aws_utils importable regardless of where this script is run from
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from aws_utils import read_csv_from_s3, upload_to_s3


class HABRawCombiner:
    def __init__(self, data_dir: str = ".", output_dir: str = "."):
        self.data_dir = data_dir
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    # ---------- LOADERS ----------
    def load_month_file(self, filename: str, lineage: str) -> pd.DataFrame:
        """Load a monthly file. Tries S3 first, falls back to local disk."""
        table_name = filename.replace(".csv", "")  # e.g. "credit_bureau_data_january_"

        logging.info("Loading %s -> %s (checking S3)", lineage, table_name)
        df = read_csv_from_s3(table_name)

        if df is None or df.empty:
            path = os.path.join(self.data_dir, filename)
            if not os.path.exists(path):
                logging.warning("Not found in S3 or locally: %s", filename)
                return pd.DataFrame()
            logging.info("Not in S3 — falling back to local file: %s", path)
            df = pd.read_csv(path, low_memory=False)
        else:
            logging.info("Loaded from S3: %s", table_name)

        # THE ONLY COLUMN WE ADD
        df["data_lineage"] = lineage

        logging.info("Loaded %d rows", len(df))
        return df

    # ---------- BUILD HISTORICAL ----------
    def build_historical(self) -> pd.DataFrame:
        monthly_files = [
            "credit_bureau_data_january_.csv",
            "credit_bureau_data_february_.csv",
            "credit_bureau_data_march_.csv",
            "credit_bureau_data_april_.csv",
            "credit_bureau_data_may_.csv",
            "credit_bureau_data_june_.csv",
            "credit_bureau_data_july_.csv",
            "credit_bureau_data_august_.csv",
            "credit_bureau_data_september_.csv",
            "credit_bureau_data_october_.csv",
        ]

        parts = []
        for file in monthly_files:
            df = self.load_month_file(file, "HISTORICAL")
            if not df.empty:
                parts.append(df)

        if not parts:
            return pd.DataFrame()

        historical_df = pd.concat(parts, ignore_index=True)
        logging.info("Historical rows: %d", len(historical_df))
        return historical_df

    # ---------- COMBINE ----------
    def combine_all(self) -> pd.DataFrame:
        logging.info("Building Historical dataset...")
        h_df = self.build_historical()

        logging.info("Loading Previous month (November)...")
        a_df = self.load_month_file("credit_bureau_data_november_.csv", "PREVIOUS_MONTH")

        logging.info("Loading Current month (December)...")
        b_df = self.load_month_file("credit_bureau_data_december_.csv", "CURRENT_MONTH")

        parts = [df for df in [h_df, a_df, b_df] if not df.empty]

        if not parts:
            logging.error("No data found!")
            return pd.DataFrame()

        final_df = pd.concat(parts, ignore_index=True)
        logging.info("FINAL ROW COUNT: %d", len(final_df))

        return final_df

    # ---------- SAVE ----------
    def save_csv(self, df: pd.DataFrame):
        import tempfile, shutil

        output_path = os.path.join(self.output_dir, "hab_combined.csv")
        pipeline_dir = os.path.dirname(__file__)
        pipeline_output_path = os.path.join(pipeline_dir, "hab_combined.csv")

        # Write to Windows temp first — avoids OneDrive VFS locking during
        # large incremental writes, then do a fast atomic copy to final location.
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".csv")
        os.close(tmp_fd)
        try:
            logging.info("Writing %d rows to temp -> %s", len(df), tmp_path)
            df.to_csv(tmp_path, index=False)
            shutil.copy2(tmp_path, output_path)
            logging.info("Saved -> %s", output_path)
            if os.path.abspath(pipeline_output_path) != os.path.abspath(output_path):
                shutil.copy2(tmp_path, pipeline_output_path)
                logging.info("Also saved -> %s", pipeline_output_path)
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

        logging.info("Saved %d rows locally", len(df))

        # Also push the combined file to S3 so downstream scripts (and any
        # other environment) can read it without needing the local file.
        ok = upload_to_s3(df, "hab_combined")
        if ok:
            logging.info("Uploaded hab_combined to S3")
        else:
            logging.warning("S3 upload of hab_combined failed — local copy still saved")

        return output_path


# ---------- MAIN ----------
def main(args):
    logging.info("=== HAB SIMPLE COMBINER START ===")

    combiner = HABRawCombiner(args.data_dir, args.output_dir)

    final_df = combiner.combine_all()

    if final_df.empty:
        logging.error("No data to save.")
        return

    output_file = combiner.save_csv(final_df)

    logging.info("=== FULL PIPELINE COMPLETE ===")



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Combine HAB data into single CSV")
    parser.add_argument("--data-dir", default="../data", help="Directory with monthly CSV files")
    parser.add_argument("--output-dir", default=".", help="Directory to save combined CSV")
    args = parser.parse_args()

    main(args)