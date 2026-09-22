from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "MARGIN"
    DATABASE_URL: str
    SECRET_KEY: str
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_BOOKS_BASE_URL: str = "https://www.googleapis.com/books/v1"
    GOOGLE_BOOKS_API_KEY: str = ""

    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_TLS: bool = True
    MAIL_FROM: str = "no-reply@margin.app"
    FRONTEND_BASE_URL: str = "http://localhost:5173"
    PASSWORD_RESET_TOKEN_TTL_MINUTES: int = 30

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
