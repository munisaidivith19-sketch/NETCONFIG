"""Seed (or refresh) the catalog in MongoDB from app/data/catalog.json.

Usage (from backend/):
    .venv\\Scripts\\python scripts\\seed_catalog.py            # upsert
    .venv\\Scripts\\python scripts\\seed_catalog.py --reset    # also remove entries not in the file
    .venv\\Scripts\\python scripts\\seed_catalog.py --file my_catalog.json
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.db import connect, ensure_indexes  # noqa: E402
from app.services import audit  # noqa: E402
from app.services.catalog import CATALOG_FILE, load_file, seed  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the NetConfig Studio catalog.")
    parser.add_argument("--file", type=Path, default=CATALOG_FILE)
    parser.add_argument("--reset", action="store_true", help="remove catalog entries that are not in the file")
    args = parser.parse_args()

    settings = Settings()
    db = connect(settings)[settings.mongo_db]
    ensure_indexes(db)
    counts = seed(db, load_file(args.file), reset=args.reset)
    audit.record(db, "catalog.seed", details={"file": args.file.name, "reset": args.reset, **counts})
    print("Seeded:", ", ".join(f"{k}={v}" for k, v in counts.items()))
    print("Note: the bundled catalog is SAMPLE data and is marked unverified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
