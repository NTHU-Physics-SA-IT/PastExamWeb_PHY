import pytest

from app.utils.passwords import (
    PASSWORD_MAX_BYTES,
    PasswordValidationError,
    hash_password,
    password_hash_needs_update,
    password_size_bytes,
    validate_api_password,
    verify_password_hash,
)

LEGACY_BCRYPT_SHA256_HASH = (
    "$bcrypt-sha256$v=2,t=2b,r=4$abcdefghijklmnopqrstuO"
    "$RujgWw4UZ3x6Of0ArAkTpGRNyZUhYCi"
)
LEGACY_BCRYPT_SHA256_V1_HASH = (
    "$bcrypt-sha256$2b,4$abcdefghijklmnopqrstuO"
    "$mMCWLXBhZLkY2iSS.hnU6uoviXOhxjq"
)
LEGACY_BCRYPT_HASH = (
    "$2b$04$abcdefghijklmnopqrstuOFeWHo6yW/rrUEe9j8D8ueOhu.9wpWwO"
)
LONG_LEGACY_BCRYPT_HASH = (
    "$2b$04$abcdefghijklmnopqrstuOimWHTbDXoN4bgLP.DY6j9.IWtcwBKwa"
)


@pytest.mark.parametrize(
    "password",
    [
        "NormalPass123!",
        "中文密碼測試123",
        "a" * 72,
        "a" * 73,
        "密" * 24,
        "密" * 25,
    ],
)
def test_bcrypt_sha256_round_trip_handles_utf8_and_bcrypt_boundary(password):
    password_hash = hash_password(password)

    assert password_hash.startswith("$bcrypt-sha256$v=2,t=2b,r=12$")
    assert verify_password_hash(password, password_hash) is True
    assert verify_password_hash(f"{password}x", password_hash) is False


def test_password_policy_counts_utf8_bytes_without_truncating():
    assert password_size_bytes("密" * 24) == 72
    assert password_size_bytes("密" * 25) == 75
    assert validate_api_password("密" * 25) == "密" * 25

    with pytest.raises(PasswordValidationError, match="256 UTF-8 bytes"):
        validate_api_password("a" * (PASSWORD_MAX_BYTES + 1))


def test_legacy_passlib_bcrypt_sha256_hash_still_verifies():
    assert verify_password_hash("LegacyPass123!", LEGACY_BCRYPT_SHA256_HASH) is True
    assert verify_password_hash("WrongPass123!", LEGACY_BCRYPT_SHA256_HASH) is False


def test_legacy_passlib_bcrypt_sha256_v1_hash_still_verifies():
    assert verify_password_hash("LegacyPass123!", LEGACY_BCRYPT_SHA256_V1_HASH) is True
    assert verify_password_hash("WrongPass123!", LEGACY_BCRYPT_SHA256_V1_HASH) is False


def test_legacy_standard_bcrypt_hash_still_verifies():
    assert verify_password_hash("LegacyPass123!", LEGACY_BCRYPT_HASH) is True
    assert verify_password_hash("WrongPass123!", LEGACY_BCRYPT_HASH) is False


def test_long_legacy_bcrypt_password_verifies_for_lazy_upgrade():
    assert verify_password_hash("a" * 73, LONG_LEGACY_BCRYPT_HASH) is True
    assert verify_password_hash(f"b{'a' * 72}", LONG_LEGACY_BCRYPT_HASH) is False
    assert password_hash_needs_update(LONG_LEGACY_BCRYPT_HASH) is True


def test_current_hash_does_not_need_update():
    assert password_hash_needs_update(hash_password("NormalPass123!")) is False


def test_malformed_hash_is_rejected():
    assert verify_password_hash("NormalPass123!", "not-a-password-hash") is False
