from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from typing import List
from datetime import datetime, timedelta

from backend.models.database import get_db
from backend.models.models import User, UserRole, Room, RoomStatus, Attendance, Participant
from backend.routers.auth import get_current_user
from backend.utils.mailcow_api import get_all_mailcow_users
from backend.config import settings

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="backend/templates")

@router.get("/sync", response_class=HTMLResponse)
async def sync_users(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Hanya Admin yang dapat melakukan sinkronisasi")

    mailcow_users = await get_all_mailcow_users(settings.MAILCOW_API_URL, settings.MAILCOW_API_KEY)
    
    synced_count = 0
    for m_user in mailcow_users:
        email = m_user.get("username") or m_user.get("email")
        if not email: continue
        
        full_name = m_user.get("name") or email.split("@")[0].replace(".", " ").title()
        tags = m_user.get("tags", [])
        tags_lower = [t.lower() for t in tags]
        
        # Mapping logic
        if "admin" in tags_lower:
            role = UserRole.ADMIN
        elif "tu" in tags_lower:
            role = UserRole.TU
        elif "guru" in tags_lower:
            role = UserRole.GURU
        else:
            role = UserRole.SISWA

        # Check existing
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalars().first()
        
        if not user:
            user = User(email=email, full_name=full_name, role=role, is_active=1)
            db.add(user)
        else:
            user.role = role
        
        synced_count += 1
    
    await db.commit()
    return f"<div class='p-4 bg-green-50 text-green-700 rounded-xl mb-4'>Berhasil sinkronisasi {synced_count} pengguna dari Mailcow.</div>"

@router.get("/users", response_class=HTMLResponse)
async def list_users_admin(
    request: Request,
    page: int = 1,
    search: str = "",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Access denied")

    limit = 10
    offset = (page - 1) * limit
    
    query = select(User)
    if search:
        query = query.where(User.email.ilike(f"%{search}%") | User.full_name.ilike(f"%{search}%"))
    
    query = query.order_by(User.role, User.email).limit(limit).offset(offset)
    result = await db.execute(query)
    users = result.scalars().all()
    
    # Check if there's a next page (simple check)
    has_next = len(users) == limit
    
    return templates.TemplateResponse(request, "fragments/admin_user_list.html", {
        "users": users, 
        "user": current_user,
        "page": page,
        "search": search,
        "has_next": has_next
    })

@router.post("/users/{user_id}/toggle", response_class=HTMLResponse)
async def toggle_user_active(
    user_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) :
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Access denied")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if user.id == current_user.id:
         return f"<span class='text-red-500 text-xs'>Tidak bisa menonaktifkan diri sendiri</span>"

    user.is_active = 0 if user.is_active == 1 else 1
    await db.commit()
    
    status_text = "Aktif" if user.is_active == 1 else "Non-aktif"
    dot_color = "bg-green-500" if user.is_active == 1 else "bg-red-400"
    btn_class = "bg-green-50 text-green-700 border-green-100 hover:bg-green-100" if user.is_active == 1 else "bg-red-50 text-red-600 border-red-100 hover:bg-red-100"
    
    return f"""<button hx-post='/admin/users/{user.id}/toggle' hx-target='closest div' hx-swap='innerHTML'
        class='inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[10px] font-bold border transition-all {btn_class}'>
        <span class='w-1.5 h-1.5 rounded-full {dot_color}'></span>
        {status_text}
    </button>"""


@router.get("/archive", response_class=HTMLResponse)
async def archive_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Access denied")
    return templates.TemplateResponse(request, "admin_archive.html", {"user": current_user})


@router.get("/archive/rooms", response_class=HTMLResponse)
async def list_archived_rooms(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Access denied")

    # A room is 'expired' if its scheduled_at + duration is in the past
    now = datetime.utcnow()
    result = await db.execute(
        select(Room).options(selectinload(Room.host)).order_by(Room.scheduled_at.desc())
    )
    all_rooms = result.scalars().all()

    expired_rooms = []
    for room in all_rooms:
        if room.scheduled_at:
            end_time = room.scheduled_at + timedelta(minutes=room.duration or 120)
            if end_time < now:
                expired_rooms.append(room)
        # Also include rooms manually marked as ENDED
        elif room.status == RoomStatus.ENDED:
            expired_rooms.append(room)

    return templates.TemplateResponse(request, "fragments/archive_room_list.html", {
        "rooms": expired_rooms,
        "user": current_user,
        "now": now,
    })


@router.get("/archive/rooms/{room_id}/participants", response_class=HTMLResponse)
async def get_room_participants(
    room_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Access denied")

    # Load attendance records for this room
    result = await db.execute(
        select(Attendance)
        .where(Attendance.room_id == room_id)
        .options(selectinload(Attendance.user))
        .order_by(Attendance.created_at)
    )
    records = result.scalars().all()

    return templates.TemplateResponse(request, "fragments/archive_participants.html", {
        "records": records,
        "room_id": room_id,
    })
