"""Create a user (first admin included). The password is typed with getpass, never passed as an argument.

Usage (from backend/):  .venv\\Scripts\\python scripts\\create_user.py admin --role admin
Reset a password:       .venv\\Scripts\\python scripts\\create_user.py admin --reset
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
from app.security.sessions import revoke_all_for_user  # noqa: E402
from app.services import audit  # noqa: E402
from app.services.users import create_user, find_by_username, set_password  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a NetConfig Studio user.")
    parser.add_argument("username")
    parser.add_argument("--role", choices=["admin", "engineer", "viewer"], default="admin")
    parser.add_argument("--reset", action="store_true",
                        help="reset the password of an existing user (also clears lockout and sessions)")
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

    if args.reset:
        user = find_by_username(db, args.username)
        if user is None:
            print(f"Error: no user named '{args.username}'.")
            return 1
        try:
            set_password(db, settings, user, password)
        except ApiError as exc:
            print(f"Error: {exc.message}")
            return 1
        # A reset also clears any lockout and logs out every existing session of that user.
        db.users.update_one({"_id": user["_id"]}, {"$set": {"failed_logins": 0, "locked_until": None}})
        revoked = revoke_all_for_user(db, user["_id"])
        audit.record(db, "user.password_reset", target={"type": "user", "id": str(user["_id"])},
                     details={"username": args.username, "via": "create_user.py", "sessions_revoked": revoked})
        print(f"Password reset for '{args.username}'. {revoked} session(s) signed out.")
        return 0

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
