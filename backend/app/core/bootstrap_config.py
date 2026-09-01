from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class BootstrapSettings(BaseSettings):
    """Configuration owned only by the explicit dev/test bootstrap command."""

    BOOTSTRAP_ADMIN_PASSWORD: SecretStr = Field(min_length=1)

    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        extra="ignore",
    )
