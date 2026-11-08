"""Time-sortable unique ids (ULID layout: 48-bit ms timestamp + 80 random bits)."""

import secrets
import time

_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"  # Crockford base32, lowercase


def new_id() -> str:
    value = (int(time.time() * 1000) << 80) | secrets.randbits(80)
    chars = []
    for _ in range(26):
        value, rem = divmod(value, 32)
        chars.append(_ALPHABET[rem])
    return "".join(reversed(chars))


def is_valid_id(value: str) -> bool:
    return len(value) == 26 and all(c in _ALPHABET for c in value)
