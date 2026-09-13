"""
Buy or Wait?
HackerRank Orchestrate - Main Entry Point

This file is the executable entry point for the project.

Run:
    python main.py

The actual orchestration logic lives inside src/.
"""

import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Project root
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Application entry point
# ---------------------------------------------------------------------------

def main() -> int:
    """
    Start the Buy or Wait financial agent.
    """

    try:
        from src.main import run

        return run()

    except KeyboardInterrupt:
        print("\nExecution interrupted by user.")
        return 130

    except Exception as exc:
        print(f"\nERROR: Application failed.")
        print(f"Reason: {exc}")

        # Useful during hackathon development.
        import traceback
        traceback.print_exc()

        return 1


if __name__ == "__main__":
    raise SystemExit(main())
