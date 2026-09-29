from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "MARGIN"
    DATABASE_URL: str
    SECRET_KEY: str
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_BOOKS_BASE_URL: str = "https://www.googleapis.com/books/v1"
    GOOGLE_BOOKS_API_KEY: str = ""
    OPEN_LIBRARY_BASE_URL: str = "https://openlibrary.org"

    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_TLS: bool = True
    MAIL_FROM: str = "no-reply@margin.app"
    FRONTEND_BASE_URL: str = "http://localhost:5173"
    PASSWORD_RESET_TOKEN_TTL_MINUTES: int = 30
    # Sessions are stateless JWTs with no revocation, so this lifetime is the
    # window a stolen token stays usable. Keep it short.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Catalog releases (scripts.load_catalog_release). A tag is fetched from
    # <CATALOG_RELEASES_URL>/<tag>/<tag>.tar.gz into CATALOG_RELEASES_DIR.
    CATALOG_RELEASES_URL: str = "https://github.com/devkevintoledo-tech/margin/releases/download"
    CATALOG_RELEASES_DIR: str = "releases"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
