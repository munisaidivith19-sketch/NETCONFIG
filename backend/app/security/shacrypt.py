"""SHA-512 crypt ("$6$" password hashes), for Junos "encrypted-password" (docs/drivers/juniper_junos.md).

Junos asks for a plain-text password interactively, so a scripted push must send a ready-made hash instead.
Python's own ``crypt`` module is Unix-only (and removed in 3.13), so this is the published algorithm:
Ulrich Drepper, "Unix crypt using SHA-256 and SHA-512" (https://www.akkadia.org/drepper/SHA-crypt.txt).
tests/unit/test_shacrypt.py checks it against the test vectors in that specification.

A hash is still a secret: the line that carries it is masked like every other password line (8.3).
"""

import hashlib
import secrets

ITOA64 = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
ROUNDS_DEFAULT, ROUNDS_MIN, ROUNDS_MAX = 5000, 1000, 999_999_999
# Order in which the 64 digest bytes are encoded, three at a time (specification step 22, SHA-512).
_ORDER = [(0, 21, 42), (22, 43, 1), (44, 2, 23), (3, 24, 45), (25, 46, 4), (47, 5, 26), (6, 27, 48),
          (28, 49, 7), (50, 8, 29), (9, 30, 51), (31, 52, 10), (53, 11, 32), (12, 33, 54), (34, 55, 13),
          (56, 14, 35), (15, 36, 57), (37, 58, 16), (59, 17, 38), (18, 39, 60), (40, 61, 19), (62, 20, 41)]


def _repeat(digest: bytes, length: int) -> bytes:
    return (digest * (length // len(digest) + 1))[:length]


def _b64(b2: int, b1: int, b0: int, n: int) -> str:
    w = (b2 << 16) | (b1 << 8) | b0
    out = []
    for _ in range(n):
        out.append(ITOA64[w & 0x3F])
        w >>= 6
    return "".join(out)


def sha512_crypt(password: str, salt: str | None = None, rounds: int | None = None) -> str:
    p = password.encode("utf-8")
    s = (salt if salt is not None else "".join(secrets.choice(ITOA64) for _ in range(16))).encode()[:16]
    n = ROUNDS_DEFAULT if rounds is None else min(max(rounds, ROUNDS_MIN), ROUNDS_MAX)

    b = hashlib.sha512(p + s + p).digest()
    a = hashlib.sha512(p + s + _repeat(b, len(p)))
    length = len(p)
    while length:
        a.update(b if length & 1 else p)
        length >>= 1
    da = a.digest()
    p_seq = _repeat(hashlib.sha512(p * len(p)).digest(), len(p))
    s_seq = _repeat(hashlib.sha512(s * (16 + da[0])).digest(), len(s))

    c = da
    for i in range(n):
        ctx = hashlib.sha512(p_seq if i & 1 else c)
        if i % 3:
            ctx.update(s_seq)
        if i % 7:
            ctx.update(p_seq)
        ctx.update(c if i & 1 else p_seq)
        c = ctx.digest()

    encoded = "".join(_b64(c[x], c[y], c[z], 4) for x, y, z in _ORDER) + _b64(0, 0, c[63], 2)
    prefix = "$6$" + (f"rounds={n}$" if rounds is not None else "")
    return f"{prefix}{s.decode()}${encoded}"
