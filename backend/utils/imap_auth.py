import imaplib
import ssl
from typing import Optional, Dict

class IMAPAuth:
    def __init__(self, host: str, port: int, use_ssl: bool = True):
        self.host = host
        self.port = port
        self.use_ssl = use_ssl

    def _sync_authenticate(self, email: str, password: str) -> bool:
        try:
            if self.use_ssl:
                context = ssl.create_default_context()
                mail = imaplib.IMAP4_SSL(self.host, self.port, ssl_context=context)
            else:
                mail = imaplib.IMAP4(self.host, self.port)

            mail.login(email, password)
            mail.logout()
            return True
        except imaplib.IMAP4.error as e:
            print(f"IMAP Auth Error: {e}")
            return False
        except Exception as e:
            print(f"General Auth Error: {e}")
            return False

    async def authenticate(self, email: str, password: str) -> bool:
        """
        Validate credentials via IMAP synchronously in a thread pool 
        to prevent blocking the FastAPI ASGI event loop!
        """
        import asyncio
        return await asyncio.to_thread(self._sync_authenticate, email, password)

async def validate_credentials(email: str, password: str, settings) -> bool:
    auth_handler = IMAPAuth(
        host=settings.MAIL_HOST,
        port=settings.IMAP_PORT,
        use_ssl=settings.MAIL_SECURE
    )
    return await auth_handler.authenticate(email, password)
