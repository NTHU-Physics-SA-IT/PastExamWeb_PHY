import pytest
from pydantic import ValidationError

from app.core.bootstrap_config import BootstrapSettings
from app.core.config import Settings, settings
from app.db.migration_safety import redact_text


def test_normal_settings_do_not_own_bootstrap_password() -> None:
    assert "DEFAULT_ADMIN_PASSWORD" not in Settings.model_fields
    assert "BOOTSTRAP_ADMIN_PASSWORD" not in Settings.model_fields


def test_obsolete_process_key_does_not_restore_normal_runtime_authority(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DEFAULT_ADMIN_PASSWORD", "synthetic-obsolete-value")

    normal_settings = Settings(_env_file=None)

    assert "DEFAULT_ADMIN_PASSWORD" not in normal_settings.model_fields_set
    assert not hasattr(normal_settings, "DEFAULT_ADMIN_PASSWORD")


def test_bootstrap_settings_require_explicit_password(monkeypatch) -> None:
    monkeypatch.delenv("BOOTSTRAP_ADMIN_PASSWORD", raising=False)

    with pytest.raises(ValidationError):
        BootstrapSettings(_env_file=None)


def test_bootstrap_settings_keep_password_secret(monkeypatch) -> None:
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "synthetic-bootstrap-only")

    bootstrap_settings = BootstrapSettings(_env_file=None)

    assert (
        bootstrap_settings.BOOTSTRAP_ADMIN_PASSWORD.get_secret_value()
        == "synthetic-bootstrap-only"
    )
    assert "synthetic-bootstrap-only" not in repr(bootstrap_settings)


def test_migration_redaction_does_not_load_bootstrap_password(monkeypatch) -> None:
    secrets = {
        "DB_PASSWORD": "synthetic-db-redaction",
        "SECRET_KEY": "synthetic-signing-redaction",
        "OAUTH_CLIENT_SECRET": "synthetic-oauth-redaction",
        "MINIO_SECRET_KEY": "synthetic-minio-redaction",
    }
    for name, value in secrets.items():
        monkeypatch.setattr(settings, name, value)

    redacted = redact_text("|".join(secrets.values()))

    assert all(value not in redacted for value in secrets.values())
    assert redacted.count("[REDACTED]") == len(secrets)
