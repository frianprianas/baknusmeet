import httpx
from typing import List, Optional
import logging

logger = logging.getLogger(__name__)

async def get_mailcow_mailbox_data(email: str, api_url: str, api_key: str) -> Optional[dict]:
    """
    Fetch mailbox details from Mailcow API.
    Used for profile synchronization (Name, Tags, Active Status).
    """
    if not api_url or not api_key:
        logger.warning("Mailcow API credentials not configured.")
        return None

    try:
        # Example: http://mail.domain.com/api/v1/get/mailbox/email@domain.com
        # Headers: X-API-Key: YOUR_KEY
        clean_url = api_url.rstrip("/")
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{clean_url}/api/v1/get/mailbox/{email}",
                headers={"X-API-Key": api_key},
                timeout=5.0
            )
            
            if response.status_code == 200:
                data = response.json()
                logger.debug(f"API success for {email}")
                
                # data is usually the mailbox info or a list containing them
                if isinstance(data, list) and len(data) > 0:
                    data = data[0]
                elif not isinstance(data, dict):
                    logger.warning(f"Unexpected data format from Mailcow for {email}")
                    return None
                
                return data
            else:
                logger.error(f"Mailcow API error for {email}: {response.status_code} - {response.text}")
                return None
    except Exception as e:
        logger.error(f"Failed to fetch mailbox data for {email}: {e}")
        return None

async def get_all_mailcow_users(api_url: str, api_key: str) -> List[dict]:
    """
    Fetch all mailboxes from Mailcow.
    Returns a list of dictionaries containing email, name, and tags.
    """
    if not api_url or not api_key:
        return []

    try:
        clean_url = api_url.rstrip("/")
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{clean_url}/api/v1/get/mailbox/all",
                headers={"X-API-Key": api_key},
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict):
                    return list(data.values())
            return []
    except Exception as e:
        logger.error(f"Failed to fetch all users from Mailcow: {e}")
        return []

async def get_mailcow_avatar_bytes(email: str, api_url: str, api_key: str) -> Optional[bytes]:
    """
    Fetch the avatar image bytes from Mailcow for the given email.
    Uses the API key if configured.
    """
    # The user provided host: baknusmail.smkbn666.sch.id
    # We use that if it's available, otherwise fallback to settings
    avatar_host = "https://baknusmail.smkbn666.sch.id"

    try:
        async with httpx.AsyncClient() as client:
            # Try with baknusmail domain first
            url = f"{avatar_host}/api/auth/avatar/{email}"
            response = await client.get(
                url,
                headers={"X-API-Key": api_key},
                timeout=10.0
            )
            
            if response.status_code == 200:
                return response.content
            
            # Fallback to configured API host if different
            if avatar_host.rstrip("/") not in api_url:
                clean_url = api_url.rstrip("/")
                url = f"{clean_url}/api/auth/avatar/{email}"
                response = await client.get(
                    url,
                    headers={"X-API-Key": api_key},
                    timeout=5.0
                )
                if response.status_code == 200:
                    return response.content
                    
            return None
    except Exception as e:
        logger.error(f"Failed to fetch avatar bytes for {email}: {e}")
        return None
