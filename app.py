#!/usr/bin/env python3
"""
Personal Finance AI Co-Pilot ("Buy or Wait?") Web Application Launcher
"""
import argparse
import sys
import webbrowser
from pathlib import Path

# Add repo root to pythonpath
REPO_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

from copilot.backend.server import create_server
from code.src.config import DATASET_DIR


def main():
    parser = argparse.ArgumentParser(description="Personal Financial Decision AI Co-Pilot")
    parser.add_argument("--host", default="127.0.0.1", help="Host address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on (default: 8000)")
    parser.add_argument("--dataset", type=Path, default=DATASET_DIR, help="Path to dataset directory")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically open browser")
    args = parser.parse_args()

    print(f"\n=======================================================")
    print(f" 🛡️  Personal Finance AI Co-Pilot ('Buy or Wait?')")
    print(f"=======================================================")
    print(f" Starting server on: http://{args.host}:{args.port}")
    print(f" Dataset source:     {args.dataset}")
    print(f" Press Ctrl+C to stop the server.")
    print(f"=======================================================\n")

    server = create_server(host=args.host, port=args.port, dataset_dir=args.dataset)

    if not args.no_browser:
        try:
            webbrowser.open(f"http://{args.host}:{args.port}")
        except Exception:
            pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server... Goodbye!")
        server.server_close()


if __name__ == "__main__":
    main()
