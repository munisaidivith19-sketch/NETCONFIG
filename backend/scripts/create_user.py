"""Create a user (first admin included). The password is typed with getpass, never passed as an argument.

Usage (from backend/):  .venv\\Scripts\\python scripts\\create_user.py admin --role admin
"""

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.db import connect, ensure_indexes  # noqa: E402
from app.errors import ApiError  # noqa: E402
from app.security.passwords import policy_errors  # noqa: E402
from app.services import audit  # noqa: E402
from app.services.users import create_user  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a NetConfig Studio user.")
    parser.add_argument("username")
    parser.add_argument("--role", choices=["admin", "engineer", "viewer"], default="admin")
    args = parser.parse_args()

    settings = Settings()
    db = connect(settings)[settings.mongo_db]
    ensure_indexes(db)

    while True:
        password = getpass.getpass("Password (min 12 characters): ")
        problems = policy_errors(password, args.username)
        if problems:
            print("  " + " ".join(problems))
            continue
        if getpass.getpass("Repeat password: ") != password:
            print("  Passwords do not match.")
            continue
        break

    try:
        doc = create_user(db, settings, args.username, password, args.role)
    except ApiError as exc:
        print(f"Error: {exc.message}")
        return 1
    audit.record(db, "user.create", target={"type": "user", "id": str(doc["_id"])},
                 details={"username": args.username, "role": args.role, "via": "create_user.py"})
    print(f"Created {args.role} '{args.username}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
