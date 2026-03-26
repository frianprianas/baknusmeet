from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime

from backend.models.database import get_db
from backend.models.models import User, Participant
from backend.routers.auth import get_current_user
from backend.utils.redis_utils import get_redis

router = APIRouter(prefix="/participants", tags=["participants"])

@router.post("/{room_id}/join")
async def join_room(
    room_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis)
):
    # 1. Update DB Tracking
    participant = Participant(user_id=current_user.id, room_id=room_id, joined_at=datetime.utcnow())
    db.add(participant)
    
    # 2. Update Redis Presence
    await redis.sadd(f"room:{room_id}:presence", current_user.email)
    await redis.expire(f"room:{room_id}:presence", 3600)  # TTL
    
    await db.commit()
    return {"message": "Joined"}

@router.get("/{room_id}/presence-badge", response_class=HTMLResponse)
async def get_presence_badge(
    room_id: int,
    redis = Depends(get_redis)
):
    active_users = await redis.smembers(f"room:{room_id}:presence")
    count = len(active_users)
    
    return f"""
    <div class="flex items-center gap-3">
        <svg viewBox="0 0 24 24" class="w-4 h-4 text-blue-400 fill-current"><path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5s-3 1.34-3 3 1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/></svg>
        <span class="text-xs font-black text-blue-200 uppercase tracking-widest">{count} Peserta</span>
    </div>
    """
