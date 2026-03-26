from pydantic_settings import BaseSettings
import os
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    MAIL_HOST: str = os.getenv("MAIL_HOST", "mail.smk.baktinusantara666.sch.id")
    IMAP_PORT: int = int(os.getenv("IMAP_PORT", "993"))
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "465"))
    MAIL_SECURE: bool = os.getenv("MAIL_SECURE", "true").lower() == "true"
    MAILCOW_API_URL: str = os.getenv("MAILCOW_API_URL", "http://mail.smk.baktinusantara666.sch.id")
    MAILCOW_API_KEY: str = os.getenv("MAILCOW_API_KEY", "")
    JWT_SECRET: str = os.getenv("JWT_SECRET", "super-secret-key-change-it")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))
    
    # Use Jitsi Public URL from env, with fallback
    JITSI_PUBLIC_URL: str = os.getenv("JITSI_PUBLIC_URL", os.getenv("JITSI_BASE_URL", "https://meet.jit.si"))
    JITSI_APP_ID: str = os.getenv("JITSI_APP_ID", "baknusmeet-app-id")
    JITSI_APP_SECRET: str = os.getenv("JITSI_APP_SECRET", "jitsi-app-secret-key")

    # BaknusDrive Integration
    DRIVE_BASE_URL: str = os.getenv("DRIVE_BASE_URL", "https://baknusdrive.smkbn666.sch.id/api")
    MEET_SECRET_KEY: str = os.getenv("MEET_SECRET_KEY", "BAKNUS_MEET_SECRET")

settings = Settings()
