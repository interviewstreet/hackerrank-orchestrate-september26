import sys
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from code.src.pipeline import FinancialAgentPipeline
from code.src.config import OUTPUT_PATH


def main():
    pipeline = FinancialAgentPipeline()
    pipeline.process_all_requests(output_csv_path=OUTPUT_PATH)


if __name__ == "__main__":
    main()
