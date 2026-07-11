"""
CLI entry point for the equity swing data ingestor.

Usage:
    python main.py ingest            # Full ingestion (delta on subsequent runs)
    python main.py ingest --dry-run  # Validate credentials only, no DB writes
"""
import sys
import argparse
from loguru import logger


def main():
    parser = argparse.ArgumentParser(description="Equity Swing — Data Ingestor")
    subparsers = parser.add_subparsers(dest="command")

    ingest_parser = subparsers.add_parser("ingest", help="Run data ingestion")
    ingest_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate API access for first 5 symbols; do not write to database",
    )

    args = parser.parse_args()

    if args.command == "ingest":
        from src.data_ingestor import run
        run(dry_run=args.dry_run)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
