"""Backend management CLI.

Run from the project root so the `backend` package is importable:

    python -m backend.cli check                 # verify DB connectivity + schema
    python -m backend.cli load-reference        # load symbols master + index tags
    python -m backend.cli stats                 # row counts per interval
    python -m backend.cli ingest                # full ingestion (Nifty 500, delta)
    python -m backend.cli ingest --dry-run      # validate API for first 5 symbols
    python -m backend.cli ingest-symbols RELIANCE TCS INFY
"""
from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="Equity Swing backend management")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("check", help="Verify DB connectivity and schema")
    sub.add_parser("load-reference", help="Load symbols master + index tags")
    sub.add_parser("stats", help="Row counts per interval")

    p_ing = sub.add_parser("ingest", help="Full ingestion (Nifty 500)")
    p_ing.add_argument("--dry-run", action="store_true", help="Validate API for first 5 symbols")

    p_sel = sub.add_parser("ingest-symbols", help="Ingest a specific list of symbols")
    p_sel.add_argument("symbols", nargs="+")

    p_rec = sub.add_parser(
        "recompute-indicators",
        help="Recompute indicators from stored OHLCV (no API); repairs NaN indicators",
    )
    p_rec.add_argument("--intervals", nargs="+", default=["1day", "1week"])

    args = parser.parse_args()

    if args.command == "check":
        from backend.db import ping
        from backend.database import init_db
        ok = ping()
        print(f"DB reachable: {ok}")
        if ok:
            init_db()
            print("Schema verified: ohlcv present.")
        sys.exit(0 if ok else 1)

    elif args.command == "load-reference":
        from backend.reference import load_all
        print(load_all())

    elif args.command == "stats":
        from backend.database import get_db_stats
        for k, v in get_db_stats().items():
            print(f"{k:20s} {v:>12,}")

    elif args.command == "ingest":
        from backend.data_ingestor import run
        run(dry_run=args.dry_run)

    elif args.command == "ingest-symbols":
        from backend.data_ingestor import run_selective
        run_selective(args.symbols)

    elif args.command == "recompute-indicators":
        from backend.data_ingestor import recompute_indicators
        recompute_indicators(intervals=tuple(args.intervals))

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
