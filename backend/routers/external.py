from fastapi import APIRouter, Depends, HTTPException, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional

from backend.models.database import get_db
from backend.models.models import Room, User
from backend.config import settings

router = APIRouter(prefix="/api/external", tags=["external"])

async def verify_api_key(x_api_key: Optional[str] = Header(None)):
    if not x_api_key or x_api_key != settings.MEET_SECRET_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return x_api_key

@router.get("/rooms/active")
async def get_active_rooms(
    request: Request,
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(verify_api_key)
):
    """
    Returns a list of active meeting rooms for integration with other Baknus apps (e.g., BaknusClass).
    """
    # Simply get all rooms and their hosts
    # In a real scenario, you might filter by "is_active" or "created_at"
    # For now, we return all rooms as per user request to see the list.
    stmt = select(Room, User).join(User, Room.host_id == User.id).order_by(Room.created_at.desc())
    result = await db.execute(stmt)
    rows = result.all()
    
    base_url = str(request.base_url).rstrip("/")
    
    rooms_list = []
    for room, host in rows:
        rooms_list.append({
            "id": room.id,
            "title": room.title,
            "host_name": host.full_name,
            "host_email": host.email,
            "created_at": room.created_at.isoformat(),
            "join_url": f"{base_url}/room/{room.id}"
        })
        
    return rooms_list
