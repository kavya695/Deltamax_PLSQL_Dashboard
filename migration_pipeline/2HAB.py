# Oracle conversion: original script retained; dataframe persistence redirected to Oracle.
"""
HAB Raw Combiner (SIMPLIFIED)

This script ONLY:
• Loads Historical months (Jan–Jun)
• Loads Previous month (July)
• Loads Current month (Aug)
• Appends everything together
• Adds ONE column -> data_lineage
• Saves ONE combined Oracle stage

NO extra columns.
NO rules.
NO trust score.
NO timestamps.
NO hashes.
NO parquet.
"""

import logging
import os
import argparse
import pandas as pd
from oracle_compat import install, read_frame, write_frame
install()

# Initialize logging IMMEDIATELY before any other calls
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", force=True)

# ============================================================
# ORACLE STAGE CONFIGURATION (Oracle-only persistence)
# ============================================================


class HABRawCombiner:
    def __init__(self, data_dir: str = ".", output_dir: str = "."):
        self.data_dir = data_dir
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    # ---------- LOADERS ----------
    def load_month_file(self, filename: str, lineage: str) -> pd.DataFrame:
        path = os.path.join(self.data_dir, filename)

        if not os.path.exists(path):
            logging.warning("File not found: %s", path)
            return pd.DataFrame()

        logging.info("Loading %s -> %s", lineage, filename)
        df = read_frame(path)

        # Add lineage and source-month metadata for downstream checks.
        df["data_lineage"] = lineage
        # Keep the source month so schema changes across months are not
        # mistaken for missing values during later quality checks.
        df["source_month"] = filename.removeprefix("credit_bureau_data_").removesuffix("_.csv").lower()

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

        logging.info("Loading Previous month (July)...")
        a_df = self.load_month_file("credit_bureau_data_july_.csv", "PREVIOUS_MONTH")

        logging.info("Loading Current month (August)...")
        b_df = self.load_month_file("credit_bureau_data_august_.csv", "CURRENT_MONTH")

        parts = [df for df in [h_df, a_df, b_df] if not df.empty]

        if not parts:
            logging.error("No data found!")
            return pd.DataFrame()

        final_df = pd.concat(parts, ignore_index=True)
        logging.info("FINAL ROW COUNT: %d", len(final_df))

        return final_df

    # ---------- SAVE ----------
    def save_oracle_stage(self, df: pd.DataFrame):
        output_path = os.path.join(self.output_dir, "hab_combined.csv")

        logging.info("Saving combined data to Oracle stage -> %s", output_path)
        write_frame(output_path, df)

        logging.info("Saved %d rows", len(df))
        return output_path


# ---------- MAIN ----------
def main(args):
    logging.info("=== HAB SIMPLE COMBINER START ===")

    combiner = HABRawCombiner(args.data_dir, args.output_dir)

    final_df = combiner.combine_all()

    if final_df.empty:
        logging.error("No data to save.")
        return

    # 1) Save CSV locally
    output_file = combiner.save_oracle_stage(final_df)

    logging.info("=== FULL PIPELINE COMPLETE ===")



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Combine HAB data into single CSV")
    parser.add_argument("--data-dir", default=".", help="Directory with monthly CSV files")
    parser.add_argument("--output-dir", default=".", help="Directory to save combined CSV")
    args = parser.parse_args()

    main(args)
