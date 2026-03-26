import httpx
import logging
from typing import Optional, Dict, Any, BinaryIO
from backend.config import settings

logger = logging.getLogger(__name__)

async def setup_meet_folder(teacher_email: Optional[str] = None) -> Dict[str, Any]:
    """
    Initialize Meet folder in BaknusDrive.
    If teacher_email is None, it sets up for ALL teachers (bulk).
    """
    url = f"{settings.DRIVE_BASE_URL.rstrip('/')}/meet/setup"
    payload = {"email": teacher_email} if teacher_email else {}
    headers = {
        "X-Meet-API-Key": settings.MEET_SECRET_KEY,
        "Content-Type": "application/json"
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers, timeout=10.0)
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Drive API Setup Error: {response.status_code} - {response.text}")
                return {"error": response.text, "status": response.status_code}
    except Exception as e:
        logger.error(f"Failed to call Drive API Setup: {e}")
        return {"error": str(e)}

async def upload_file_to_drive(
    file_name: str, 
    file_content: bytes, 
    teacher_email: str,
    category: str = "meet",
    folder: str = ""
) -> Dict[str, Any]:
    """
    Upload a file to BaknusDrive under a specific teacher's folder and category.
    """
    # Assuming endpoint: /api/meet/upload (following the pattern)
    # We might need to adjust based on actual Drive API documentation
    url = f"{settings.DRIVE_BASE_URL.rstrip('/')}/{category}/upload"
    
    headers = {
        "X-Meet-API-Key": settings.MEET_SECRET_KEY,
    }
    
    files = {
        "file": (file_name, file_content)
    }
    data = {
        "email": teacher_email,
        "folder": folder
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url, 
                data=data, 
                files=files, 
                headers=headers, 
                timeout=30.0
            )
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Drive API Upload Error: {response.status_code} - {response.text}")
                return {"error": response.text, "status": response.status_code}
    except Exception as e:
        logger.error(f"Failed to call Drive API Upload: {e}")
        return {"error": str(e)}

async def upload_meet_link(room_title: str, room_id: int, teacher_email: str) -> Dict[str, Any]:
    """
    Saves a meeting link as a file in BaknusDrive.
    """
    # Create a simple .url or .txt file content
    meet_url = f"https://baknusmeet.smkbn666.sch.id/room/{room_id} (Example URL)"
    # We should probably get the actual base URL from settings or request
    
    file_name = f"Link_Meeting_{room_title.replace(' ', '_')}.txt"
    content = f"Meeting: {room_title}\nLink: {meet_url}\nGenerated at: {settings.DRIVE_BASE_URL}".encode('utf-8')
    
    return await upload_file_to_drive(file_name, content, teacher_email, category="meet")
