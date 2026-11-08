from app.security.passwords import hash_password, policy_errors, verify_password


def test_policy():
    assert policy_errors("short") != []
    assert policy_errors("x" * 12) != []  # too few different characters
    assert policy_errors("password1234") != []
    assert policy_errors("alice-is-great-1", "alice") != []
    assert policy_errors("é" * 40) != []  # more than 72 bytes
    assert policy_errors("A-good-long-pass-1", "alice") == []


def test_hash_and_verify():
    h = hash_password("A-good-long-pass-1")
    assert h.startswith("$2b$12$")
    assert verify_password("A-good-long-pass-1", h)
    assert not verify_password("A-good-long-pass-2", h)


def test_verify_never_raises_on_bad_input():
    assert not verify_password("x", "not-a-hash")
    assert not verify_password("x", None)
    assert not verify_password("é" * 80, hash_password("A-good-long-pass-1"))
