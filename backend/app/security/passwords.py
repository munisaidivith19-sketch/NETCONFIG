"""Password hashing (bcrypt, cost >= 12) and the password policy (CLAUDE.md 8.2)."""

import bcrypt

MIN_LENGTH = 12
MAX_BYTES = 72  # bcrypt only uses the first 72 bytes; refuse longer passwords instead of truncating

COMMON = {
    "password1234", "123456789012", "qwertyuiopas", "administrator", "letmein12345",
    "welcome12345", "changeme1234", "cisco1234567", "passw0rd1234", "netconfig123",
}

# A valid hash of a random value, used so an unknown username costs the same time as a wrong password.
_DUMMY_HASH = bcrypt.hashpw(b"dummy-password-for-timing", bcrypt.gensalt(12))


def policy_errors(password: str, username: str = "") -> list[str]:
    errors = []
    if len(password) < MIN_LENGTH:
        errors.append(f"Use at least {MIN_LENGTH} characters.")
    if len(password.encode("utf-8")) > MAX_BYTES:
        errors.append(f"Use at most {MAX_BYTES} bytes.")
    if password.lower() in COMMON:
        errors.append("This password is too common.")
    if username and username.lower() in password.lower():
        errors.append("The password must not contain the username.")
    if password and len(set(password)) < 4:
        errors.append("Use more different characters.")
    return errors


def hash_password(password: str, rounds: int = 12) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds)).decode("ascii")


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        candidate = password.encode("utf-8")
        if len(candidate) > MAX_BYTES:
            bcrypt.checkpw(b"x", _DUMMY_HASH)
            return False
        if not password_hash:
            bcrypt.checkpw(candidate, _DUMMY_HASH)
            return False
        return bcrypt.checkpw(candidate, password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False
