"""Copy the local database to another MongoDB (for example Atlas for the public demo, docs/DEPLOY_RENDER.md).

Usage (from backend/):  .venv\\Scripts\\python scripts\\copy_database.py [--target-db netconfig_demo] [--replace]

The target connection string is typed at a hidden prompt (it holds the Atlas password), never passed as an
argument or saved. Sessions are never copied: they are live login tokens.
Without --replace, a collection that already has data in the target is left alone, except users: accounts
whose username is not there yet are added. --replace empties each target collection first.
"""

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pymongo import MongoClient  # noqa: E402

from app.db import ensure_indexes  # noqa: E402

SKIP = {"sessions"}  # live login tokens: a copy would be a valid stolen session on the other server


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy the NetConfig Studio database to another MongoDB.")
    parser.add_argument("--source-uri", default="mongodb://127.0.0.1:27017")
    parser.add_argument("--source-db", default="netconfig")
    parser.add_argument("--target-db", default="netconfig_demo")
    parser.add_argument("--replace", action="store_true", help="empty each target collection before copying")
    args = parser.parse_args()

    target_uri = getpass.getpass("Target connection string (hidden): ").strip()
    if not target_uri.startswith(("mongodb://", "mongodb+srv://")):
        print("Error: that is not a MongoDB connection string.")
        return 1

    source = MongoClient(args.source_uri, tz_aware=True, serverSelectionTimeoutMS=5000)[args.source_db]
    target_client = MongoClient(target_uri, tz_aware=True, serverSelectionTimeoutMS=15000)
    try:
        target_client.admin.command("ping")
    except Exception as exc:  # noqa: BLE001 - shown to the user; the message never contains the password
        print(f"Error: cannot reach the target ({type(exc).__name__}). Check the password and Atlas Network Access.")
        return 1
    target = target_client[args.target_db]
    ensure_indexes(target)  # same unique indexes and TTLs as the app creates

    print(f"Copying {args.source_db} -> {args.target_db}")
    for name in sorted(source.list_collection_names()):
        if name in SKIP:
            print(f"  {name:20} skipped (login tokens are never copied)")
            continue
        docs = list(source[name].find())
        if args.replace:
            target[name].delete_many({})
        existing = target[name].count_documents({})
        if existing and name == "users":
            have = {u["username"] for u in target.users.find({}, {"username": 1})}
            docs = [d for d in docs if d["username"] not in have]
        elif existing:
            print(f"  {name:20} skipped ({existing} documents already there; use --replace to overwrite)")
            continue
        if docs:
            target[name].insert_many(docs, ordered=True)  # same _id and order: the audit hash chain stays valid
        print(f"  {name:20} {len(docs)} copied")
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
