import pandas as pd

# Load your output and the sample dataset
output = pd.read_csv("../output.csv")
sample = pd.read_csv("../dataset/sample_requests.csv")

# Merge on request_id to compare only rows that exist in sample
merged = output.merge(sample, on="request_id", suffixes=("_out", "_sample"))

# Columns to check
columns_to_check = ["amount_safe_to_pay", "affordability_status"]

for col in columns_to_check:
    mismatches = merged[merged[f"{col}_out"] != merged[f"{col}_sample"]]
    print(f"\n{col} mismatches: {len(mismatches)}")
    if not mismatches.empty:
        print(mismatches[["request_id", f"{col}_out", f"{col}_sample"]])
