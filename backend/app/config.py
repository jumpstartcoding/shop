"""Application settings, read from environment variables (see .env.example)."""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = Field(default="development", description="development | test | production")
    database_url: str = "postgresql+psycopg://postgres@127.0.0.1:5433/shop"

    # Public URL of the site (CloudFront domain). Used to build customer links.
    public_base_url: str = "http://localhost:5173"

    # CloudFront adds this header on every /api request; the app rejects requests without it.
    # Leave empty in local development to disable the check.
    origin_secret: SecretStr = SecretStr("")

    session_idle_days: int = 7
    session_absolute_days: int = 30
    login_max_failures: int = 10
    login_lock_minutes: int = 15

    log_level: str = "INFO"

    # Files (signed PDFs, signatures, logo, later photos).
    # "local" writes under files_dir (development/tests); "s3" uses files_bucket.
    storage_backend: str = "local"
    files_dir: str = ".files"
    files_bucket: str = ""
    aws_region: str = "us-east-1"

    # Email. "file" writes .eml files to <files_dir>/outbox for local development;
    # "ses" sends through Amazon SES; "disabled" records the attempt and sends nothing.
    email_backend: str = "file"
    email_from: str = "Shop <no-reply@example.com>"

    # Customer links
    estimate_link_days: int = 45
    invoice_link_days: int = 180
    # Public form abuse limit: submissions per IP address per hour.
    public_submissions_per_hour: int = 5

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def cookie_secure(self) -> bool:
        # Browsers drop Secure cookies on plain-http localhost in some cases; production is HTTPS-only.
        return self.environment != "development"

    @property
    def on_lambda(self) -> bool:
        import os

        return bool(os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))


@lru_cache
def get_settings() -> Settings:
    return Settings()
