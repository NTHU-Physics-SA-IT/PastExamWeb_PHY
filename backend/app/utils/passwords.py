import base64
import hashlib
import hmac
import re

import bcrypt

PASSWORD_MIN_CHARACTERS = 8
PASSWORD_MAX_BYTES = 256
BCRYPT_ROUNDS = 12

_BCRYPT_SHA256_V2_RE = re.compile(
    r"^\$bcrypt-sha256\$v=2,t=(?P<ident>2b),r=(?P<rounds>\d{1,2})"
    r"\$(?P<salt>[./A-Za-z0-9]{22})\$(?P<checksum>[./A-Za-z0-9]{31})$"
)
_BCRYPT_SHA256_V1_RE = re.compile(
    r"^\$bcrypt-sha256\$(?P<ident>2[ab]),(?P<rounds>\d{1,2})"
    r"\$(?P<salt>[./A-Za-z0-9]{22})\$(?P<checksum>[./A-Za-z0-9]{31})$"
)
_BCRYPT_RE = re.compile(r"^\$(?P<ident>2[aby])\$(?P<rounds>\d{2})\$.{53}$")


class PasswordValidationError(ValueError):
    """Raised when a password violates the server-side password policy."""


def password_size_bytes(password: str) -> int:
    return len(password.encode("utf-8"))


def validate_password_size(password: str) -> bytes:
    encoded = password.encode("utf-8")
    if len(encoded) > PASSWORD_MAX_BYTES:
        raise PasswordValidationError(
            f"Password must not exceed {PASSWORD_MAX_BYTES} UTF-8 bytes"
        )
    return encoded


def validate_api_password(password: str | None) -> str | None:
    if password is None:
        return None
    if len(password) < PASSWORD_MIN_CHARACTERS:
        raise PasswordValidationError(
            f"Password must contain at least {PASSWORD_MIN_CHARACTERS} characters"
        )
    validate_password_size(password)
    return password


def _bcrypt_sha256_key(password: bytes, salt: str, *, version: int) -> bytes:
    if version == 1:
        digest = hashlib.sha256(password).digest()
    else:
        digest = hmac.new(salt.encode("ascii"), password, hashlib.sha256).digest()
    return base64.b64encode(digest)


def _standard_bcrypt_hash(
    ident: str,
    rounds: int,
    salt: str,
    checksum: str,
) -> bytes:
    if rounds < 4 or rounds > 31:
        raise ValueError("Invalid bcrypt rounds")
    return f"${ident}${rounds:02d}${salt}{checksum}".encode("ascii")


def hash_password(password: str) -> str:
    password_bytes = validate_password_size(password)
    bcrypt_config = bcrypt.gensalt(rounds=BCRYPT_ROUNDS, prefix=b"2b").decode("ascii")
    _, ident, rounds_text, salt = bcrypt_config.split("$")
    rounds = int(rounds_text)
    key = _bcrypt_sha256_key(password_bytes, salt, version=2)
    standard_hash = bcrypt.hashpw(key, bcrypt_config.encode("ascii")).decode("ascii")
    checksum = standard_hash[-31:]
    return (
        f"$bcrypt-sha256$v=2,t={ident},r={rounds}"
        f"${salt}${checksum}"
    )


def verify_password_hash(password: str, password_hash: str) -> bool:
    try:
        password_bytes = validate_password_size(password)
    except PasswordValidationError:
        return False

    wrapped_match = _BCRYPT_SHA256_V2_RE.fullmatch(password_hash)
    version = 2
    if wrapped_match is None:
        wrapped_match = _BCRYPT_SHA256_V1_RE.fullmatch(password_hash)
        version = 1

    try:
        if wrapped_match is not None:
            fields = wrapped_match.groupdict()
            rounds = int(fields["rounds"])
            expected_hash = _standard_bcrypt_hash(
                fields["ident"],
                rounds,
                fields["salt"],
                fields["checksum"],
            )
            key = _bcrypt_sha256_key(
                password_bytes,
                fields["salt"],
                version=version,
            )
            return bcrypt.checkpw(key, expected_hash)

        if _BCRYPT_RE.fullmatch(password_hash):
            # Raw bcrypt hashes created before bcrypt 5 used bcrypt's historical
            # first-72-byte semantics. Keep that behavior only for verification;
            # authenticate_user() immediately upgrades a successful legacy login
            # to the length-safe bcrypt_sha256 format.
            legacy_password = password_bytes[:72]
            return bcrypt.checkpw(legacy_password, password_hash.encode("ascii"))
    except (TypeError, ValueError):
        return False

    return False


def password_hash_needs_update(password_hash: str) -> bool:
    wrapped_match = _BCRYPT_SHA256_V2_RE.fullmatch(password_hash)
    if wrapped_match is not None:
        return int(wrapped_match.group("rounds")) < BCRYPT_ROUNDS
    return bool(
        _BCRYPT_SHA256_V1_RE.fullmatch(password_hash)
        or _BCRYPT_RE.fullmatch(password_hash)
    )
