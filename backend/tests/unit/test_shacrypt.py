"""SHA-512 crypt against the test vectors of the specification (https://www.akkadia.org/drepper/SHA-crypt.txt)."""

import re

import pytest

from app.security.shacrypt import sha512_crypt

VECTORS = [
    ("saltstring", None, "Hello world!",
     "$6$saltstring$svn8UoSVapNtMuq1ukKS4tPQd8iKwSMHWjl/O817G3uBnIFNjnQJuesI68u4OTLiBFdcbYEdFCoEOfaS35inz1"),
    ("saltstringsaltstring", 10000, "Hello world!",
     "$6$rounds=10000$saltstringsaltst$OW1/O6BYHV6BcXZu8QVeXbDWra3Oeqh0sbHbbMCVNSnCM/UrjmM0Dp8vOuZeHBy/"
     "YTBmSK6H9qs/y3RnOaw5v."),
    ("toolongsaltstring", 5000, "This is just a test",
     "$6$rounds=5000$toolongsaltstrin$lQ8jolhgVRVhY4b5pZKaysCLi0QBxGoNeKQzQ3glMhwllF7oGDZxUhx1yxdYcz/"
     "e1JSbq3y6JMxxl8audkUEm0"),
    ("roundstoolow", 10, "the minimum number is still observed",
     "$6$rounds=1000$roundstoolow$kUMsbe306n21p9R.FRkW3IGn.S9NPN0x50YhH1xhLsPuWGsUSklZt58jaTfF4ZEQpyUNGc0dqbpBYYB"
     "aHHrsX."),
]


@pytest.mark.parametrize(("salt", "rounds", "password", "expected"), VECTORS)
def test_specification_vectors(salt, rounds, password, expected):
    assert sha512_crypt(password, salt, rounds) == expected


def test_random_salt_and_format():
    a, b = sha512_crypt("Passw0rd-123"), sha512_crypt("Passw0rd-123")
    assert a != b
    assert re.fullmatch(r"\$6\$[./0-9A-Za-z]{16}\$[./0-9A-Za-z]{86}", a)
