from fastapi import APIRouter, Depends, HTTPException, status, Request, Form, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from datetime import datetime, timedelta
from typing import Optional
import os
import base64

from backend.models.database import get_db
from backend.models.models import User, UserRole, Room, RoomStatus
from backend.schemas.schemas import RoomCreate, RoomResponse, RoomUpdate
from backend.routers.auth import get_current_user
from backend.utils.jitsi_jwt import generate_jitsi_jwt
from backend.config import settings
from backend.utils.drive_api import setup_meet_folder, upload_file_to_drive

router = APIRouter(prefix="/rooms", tags=["rooms"])

# Module-level Jinja2Templates — single shared instance to avoid cache issues
_templates = Jinja2Templates(directory="backend/templates")


async def _check_schedule_conflict(
    db: AsyncSession,
    scheduled_at: datetime,
    duration_minutes: int,
    exclude_room_id: Optional[int] = None
) -> Optional[Room]:
    """
    Cek apakah ada room lain yang jadwalnya overlap dengan [scheduled_at, scheduled_at + duration].
    Room dianggap overlap jika interval waktu mereka saling berpotongan.
    """
    new_end = scheduled_at + timedelta(minutes=duration_minutes)

    # Ambil semua room yang belum ended
    query = select(Room).where(Room.status != RoomStatus.ENDED)
    if exclude_room_id:
        query = query.where(Room.id != exclude_room_id)

    result = await db.execute(query)
    rooms = result.scalars().all()

    for existing in rooms:
        if existing.scheduled_at is None:
            continue
        existing_end = existing.scheduled_at + timedelta(minutes=existing.duration or 120)
        # Overlap: existing starts before new ends AND existing ends after new starts
        if existing.scheduled_at < new_end and existing_end > scheduled_at:
            return existing  # konflik ditemukan

    return None


@router.post("/", response_class=HTMLResponse)
async def create_room(
    request: Request,
    title: str = Form(...),
    scheduled_at_str: str = Form(...),       # format: "YYYY-MM-DDTHH:MM" (datetime-local)
    duration: int = Form(120),               # durasi dalam menit, default 120
    host_id: Optional[int] = Form(None),     # Optional moderator assignment (Admin Only)
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role not in [UserRole.ADMIN, UserRole.TU, UserRole.GURU]:
        raise HTTPException(status_code=403, detail="Hanya Admin, TU, atau Guru yang dapat membuat ruangan")

    # Override host_id if current_user is admin and host_id is provided
    actual_host_id = current_user.id
    if current_user.role == UserRole.ADMIN and host_id:
        actual_host_id = host_id

    # Parse datetime dari form (format datetime-local: "2026-03-24T08:00")
    try:
        scheduled_at = datetime.strptime(scheduled_at_str, "%Y-%m-%dT%H:%M")
    except ValueError:
        return _templates.TemplateResponse(request, "fragments/room_list.html", {
            "rooms": [], "curr_user_id": current_user.id,
            "is_admin": current_user.role == UserRole.ADMIN,
            "error": f"Format tanggal/jam tidak valid: {scheduled_at_str}"
        })

    # Validasi: jadwal tidak boleh di masa lalu
    now = datetime.utcnow() + timedelta(hours=7)  # WIB offset
    if scheduled_at < now - timedelta(minutes=5):
        ctx = await _build_list_ctx(request, current_user, db)
        ctx["toast_error"] = "Jadwal tidak boleh di masa lalu."
        return _templates.TemplateResponse(request, "fragments/room_list.html", ctx)

    # Validasi durasi: maks 120 menit (2 jam)
    if not (30 <= duration <= 120):
        ctx = await _build_list_ctx(request, current_user, db)
        ctx["toast_error"] = "Durasi meeting maksimal adalah 2 jam (120 menit)."
        return _templates.TemplateResponse(request, "fragments/room_list.html", ctx)

    # Cek konflik jadwal
    conflict = await _check_schedule_conflict(db, scheduled_at, duration)
    if conflict:
        # Peringatan error harus dengan jam WIB
        conflict_wib = conflict.scheduled_at + timedelta(hours=7)
        conflict_end = conflict_wib + timedelta(minutes=conflict.duration or 120)
        ctx = await _build_list_ctx(request, current_user, db)
        ctx["toast_error"] = (
            f"Jadwal bentrok dengan room \"{conflict.title}\" "
            f"({conflict_wib.strftime('%d/%m/%Y %H:%M')} – "
            f"{conflict_end.strftime('%H:%M')}). Pilih waktu lain."
        )
        return _templates.TemplateResponse(request, "fragments/room_list.html", ctx)

    # Tentukan status: jika dijadwalkan dalam 5 menit ke depan, langsung ACTIVE
    scheduled_utc = scheduled_at - timedelta(hours=7)  # konversi WIB → UTC
    diff_minutes = (scheduled_at - now).total_seconds() / 60
    room_status = RoomStatus.ACTIVE if diff_minutes <= 5 else RoomStatus.SCHEDULED

    room = Room(
        title=title,
        host_id=actual_host_id,
        jitsi_room_id=f"baknus-{os.urandom(8).hex()}",
        scheduled_at=scheduled_utc,
        duration=duration,
        status=room_status
    )
    db.add(room)
    await db.commit()
    await db.refresh(room)

    # Automatically sync meet link to BaknusDrive for host
    try:
        # Get Host data
        host_stmt = select(User).where(User.id == actual_host_id)
        host_res = await db.execute(host_stmt)
        host = host_res.scalars().first()
        
        if host:
            base_url = str(request.base_url).rstrip("/")
            meet_url = f"{base_url}/room/{room.id}"
            file_name = f"Link_Meeting_{room.title.replace(' ', '_')}.txt"
            content = f"Meeting: {room.title}\nHost: {host.full_name}\nLink: {meet_url}\nSchedule: {scheduled_at.strftime('%d %b %Y, %H:%M')} WIB".encode('utf-8')
            
            await setup_meet_folder(teacher_email=host.email)
            await upload_file_to_drive(file_name, content, host.email, category="meet")
    except Exception as drive_err:
        print(f"FAILED TO AUTO-SYNC TO DRIVE: {drive_err}")

    return await list_rooms_htmx(request, current_user, db)


async def _build_list_ctx(request, current_user, db):
    """Helper untuk membangun context daftar room."""
    from sqlalchemy.orm import joinedload
    if current_user.role == UserRole.ADMIN:
        query = select(Room).options(joinedload(Room.host)).order_by(Room.scheduled_at.asc())
    elif current_user.role in [UserRole.TU, UserRole.GURU]:
        query = select(Room).where(Room.host_id == current_user.id).options(joinedload(Room.host)).order_by(Room.scheduled_at.asc())
    else:
        query = select(Room).where(Room.status != RoomStatus.ENDED).options(joinedload(Room.host)).order_by(Room.scheduled_at.asc())

    result = await db.execute(query)
    rooms = result.scalars().unique().all()
    return {
        "rooms": rooms,
        "curr_user_id": current_user.id,
        "is_admin": current_user.role == UserRole.ADMIN,
        "timedelta": timedelta
    }


@router.get("/list", response_class=HTMLResponse)
async def list_rooms_htmx(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    ctx = await _build_list_ctx(request, current_user, db)
    return _templates.TemplateResponse(request, "fragments/room_list.html", ctx)


@router.put("/{room_id}", response_class=HTMLResponse)
async def update_room(
    request: Request,
    room_id: int,
    title: str = Form(...),
    scheduled_at_str: Optional[str] = Form(None),
    duration: Optional[int] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Room).where(Room.id == room_id))
    room = result.scalars().first()

    if not room:
        raise HTTPException(status_code=404, detail="Room tidak ditemukan")

    if room.host_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Hanya host atau Admin yang dapat mengubah ruangan")

    room.title = title

    if scheduled_at_str:
        try:
            new_sched = datetime.strptime(scheduled_at_str, "%Y-%m-%dT%H:%M")
            new_dur = duration or room.duration or 120
            conflict = await _check_schedule_conflict(db, new_sched, new_dur, exclude_room_id=room_id)
            if conflict:
                conflict_wib = conflict.scheduled_at + timedelta(hours=7)
                conflict_end = conflict_wib + timedelta(minutes=conflict.duration or 120)
                ctx = await _build_list_ctx(request, current_user, db)
                ctx["toast_error"] = (
                    f"Jadwal bentrok dengan room \"{conflict.title}\" "
                    f"({conflict_wib.strftime('%d/%m/%Y %H:%M')} – "
                    f"{conflict_end.strftime('%H:%M')})."
                )
                return _templates.TemplateResponse(request, "fragments/room_list.html", ctx)
            room.scheduled_at = new_sched - timedelta(hours=7)
        except ValueError:
            pass

    if duration:
        if not (30 <= duration <= 120):
            ctx = await _build_list_ctx(request, current_user, db)
            ctx["toast_error"] = "Durasi meeting maksimal adalah 2 jam (120 menit)."
            return _templates.TemplateResponse(request, "fragments/room_list.html", ctx)
        room.duration = duration

    await db.commit()
    return await list_rooms_htmx(request, current_user, db)


@router.delete("/{room_id}", response_class=HTMLResponse)
async def delete_room(
    request: Request,
    room_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    try:
        result = await db.execute(select(Room).where(Room.id == room_id))
        room = result.scalars().first()

        if not room:
            raise HTTPException(status_code=404, detail="Room tidak ditemukan")

        if room.host_id != current_user.id and current_user.role != UserRole.ADMIN:
            raise HTTPException(status_code=403, detail="Hanya host atau Admin yang dapat menghapus ruangan")

        await db.delete(room)
        await db.commit()
    except Exception as e:
        await db.rollback()
        print(f"DELETE ERROR: {e}")
        ctx = await _build_list_ctx(request, current_user, db)
        ctx["toast_error"] = f"Gagal menghapus room: {str(e)}"
        return _templates.TemplateResponse(request, "fragments/room_list.html", ctx)

    return await list_rooms_htmx(request, current_user, db)


@router.get("/{room_id}/info")
async def get_room_info(
    request: Request,
    room_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Room).where(Room.id == room_id))
    room = result.scalars().first()
    if not room:
        raise HTTPException(status_code=404, detail="Room tidak ditemukan")

    now = datetime.utcnow()
    if room.scheduled_at:
        if now < room.scheduled_at:
            return {"error": "early", "wib_time": (room.scheduled_at + timedelta(hours=7)).strftime('%d %b %Y, %H:%M WIB')}
        
        end_time = room.scheduled_at + timedelta(minutes=room.duration or 120)
        if now > end_time:
            return {"error": "ended"}
        
        exp_timestamp = int(end_time.timestamp())
    else:
        exp_timestamp = int((now + timedelta(minutes=120)).timestamp())

    # Fix: Aggressive role check using raw string value
    user_role_str = str(current_user.role.value if hasattr(current_user.role, 'value') else current_user.role)
    is_moderator = user_role_str in ["ADMIN", "GURU", "TU"]
    print(f"\n[JITSI SECURITY] User: {current_user.email} | Detected Role: {user_role_str} | Is Moderator: {is_moderator}")

    jitsi_domain = settings.JITSI_PUBLIC_URL.replace("https://", "").replace("http://", "").split(":")[0].split("/")[0]
    # Ensure avatar use public HTTPS domain to avoid Mixed Content
    base_url = f"https://{jitsi_domain}"
    avatar_proxy_url = f"{base_url}/auth/avatar-proxy/{current_user.email}"

    token = generate_jitsi_jwt(
        app_id=settings.JITSI_APP_ID,
        app_secret=settings.JITSI_APP_SECRET,
        room_name=room.jitsi_room_id,
        user_email=current_user.email,
        user_name=current_user.full_name,
        is_moderator=is_moderator,
        sub=jitsi_domain,
        exp_timestamp=exp_timestamp
    )

    return {
        "token": token,
        "is_moderator": is_moderator,
        "jitsi_room_id": room.jitsi_room_id,
        "jitsi_base_url": settings.JITSI_PUBLIC_URL,
        "user_email": current_user.email,
        "user_name": current_user.full_name,
        "avatar_url": avatar_proxy_url
    }



@router.post("/{room_id}/sync-link")
async def sync_link_to_drive(
    request: Request,
    room_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Save meeting link (.txt file) to BaknusDrive.
    """
    room_stmt = select(Room).where(Room.id == room_id)
    room_res = await db.execute(room_stmt)
    room = room_res.scalars().first()
    
    if not room:
        raise HTTPException(status_code=404, detail="Room tidak ditemukan")
        
    if current_user.role not in [UserRole.ADMIN, UserRole.TU, UserRole.GURU]:
        raise HTTPException(status_code=403, detail="Anda tidak memiliki izin")

    # Get Host data
    host_stmt = select(User).where(User.id == room.host_id)
    host_res = await db.execute(host_stmt)
    host = host_res.scalars().first()
    
    if not host:
        raise HTTPException(status_code=404, detail="Host tidak ditemukan")

    # Generate actual link
    base_url = str(request.base_url).rstrip("/")
    # We use room ID to generate the local app link
    meet_url = f"{base_url}/room/{room.id}"
    
    # Save as file to Drive
    file_name = f"Link_Meeting_{room.title.replace(' ', '_')}.txt"
    content = f"Meeting: {room.title}\nHost: {host.full_name}\nLink: {meet_url}\nSchedule: {room.scheduled_at + timedelta(hours=7)} WIB".encode('utf-8')
    
    # Ensure folder
    await setup_meet_folder(teacher_email=host.email)
    
    # Upload
    sync_res = await upload_file_to_drive(file_name, content, host.email, category="meet")

    if "error" in sync_res:
        return Response(
            content=f"Gagal simpan link ke Drive: {sync_res['error']}",
            status_code=500,
            headers={"HX-Trigger": '{"showToast": {"msg": "❌ Gagal simpan link ke Drive", "type": "error"}}'}
        )
        
    return Response(
        content="Success",
        headers={"HX-Trigger": '{"showToast": {"msg": "✅ Link Meeting berhasil disimpan ke BaknusDrive!", "type": "success"}}'}
    )


@router.post("/{room_id}/screenshot")
async def save_screenshot(
    room_id: int,
    data: dict,  # Expects { "image_data": "data:image/jpeg;base64,..." }
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Capture a screenshot from the meeting and save it to BaknusDrive.
    Accessible only by Moderators (Admin, Guru, TU).
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.GURU, UserRole.TU]:
        raise HTTPException(status_code=403, detail="Hanya Moderator yang dapat mengambil dokumentasi screenshot")

    # 1. Retrieve Room
    result = await db.execute(select(Room).where(Room.id == room_id))
    room = result.scalars().first()
    if not room:
        raise HTTPException(status_code=404, detail="Room tidak ditemukan")

    # 2. Retrieve Host to get drive target
    host_stmt = select(User).where(User.id == room.host_id)
    host_res = await db.execute(host_stmt)
    host = host_res.scalars().first()
    if not host:
        raise HTTPException(status_code=404, detail="Host tidak ditemukan untuk sinkronisasi")

    # 3. Decode base64 image
    try:
        image_data = data.get("image_data")
        if not image_data or "," not in image_data:
            raise HTTPException(status_code=400, detail="Data gambar tidak valid")
            
        header, encoded = image_data.split(",", 1)
        file_bytes = base64.b64decode(encoded)
        
        # Determine extension from header or default to jpg
        ext = "jpg"
        if "png" in header: ext = "png"
        elif "webp" in header: ext = "webp"
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Gagal memproses data gambar: {str(e)}")

    # 4. Create filename (Consistent for overwriting)
    clean_title = "".join([c if c.isalnum() else "_" for c in room.title])
    filename = f"Snapshot_{clean_title}.{ext}"

    # 5. Sync to Drive
    try:
        # Ensure meet folder exists
        await setup_meet_folder(teacher_email=host.email)
        
        # Upload (Overwrite logic handled by BaknusDrive API if name is identical)
        sync_res = await upload_file_to_drive(
            file_name=filename,
            file_content=file_bytes,
            teacher_email=host.email,
            category="meet"
        )
        
        if "error" in sync_res:
             raise HTTPException(status_code=500, detail=f"Drive API Error: {sync_res['error']}")
             
        return {"status": "success", "message": "Dokumentasi berhasil disimpan", "filename": filename}
        
    except Exception as e:
        print(f"SCREENSHOT SYNC ERROR: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{room_id}/save-chat")
async def save_chat_history(
    room_id: int,
    data: dict,  # Expects { "chat_content": "..." }
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Save the meeting chat history as a .txt file to BaknusDrive.
    Accessible only by Moderators (Admin, Guru, TU).
    """
    if str(current_user.role.value if hasattr(current_user.role, 'value') else current_user.role) not in ["ADMIN", "GURU", "TU"]:
        raise HTTPException(status_code=403, detail="Hanya moderator yang dapat menyimpan riwayat chat")

    room_stmt = select(Room).where(Room.id == room_id)
    room_res = await db.execute(room_stmt)
    room = room_res.scalars().first()
    if not room:
        raise HTTPException(status_code=404, detail="Room tidak ditemukan")

    chat_content = data.get("chat_content", "")
    if not chat_content:
        raise HTTPException(status_code=400, detail="Riwayat chat kosong")

    # Generate filename with timestamp
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_title = "".join([c if c.isalnum() else "_" for c in room.title])
    # Use prefix in filename to force subfolder creation (if supported by Drive)
    # Most systems interpret '/' in filename as a subdirectory
    file_name = f"Chat/CHAT_{safe_title}_{timestamp}.txt"

    # Upload to BaknusDrive
    try:
        # Ensure folder exists
        await setup_meet_folder(teacher_email=current_user.email)
        
        file_bytes = chat_content.encode('utf-8')
        sync_res = await upload_file_to_drive(
            file_name=file_name,
            file_content=file_bytes,
            teacher_email=current_user.email,
            category="meet",
            folder="Chat"
        )

        # Broad success: if sync_res is returned and not an explicit error dict with status >= 400
        if isinstance(sync_res, dict) and sync_res.get("status", 200) < 400:
             return {"status": "success", "file_name": file_name}
        
        # If it truly failed with an error message
        error_msg = sync_res.get("error", sync_res.get("message", "Gagal menyimpan ke Drive"))
        raise HTTPException(status_code=500, detail=error_msg)
            
    except Exception as e:
        print(f"SAVE_CHAT_ERROR: {e}")
        # Always return JSON even on true exception
        raise HTTPException(status_code=500, detail=str(e))
