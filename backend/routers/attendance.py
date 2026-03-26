from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.models.database import get_db
from backend.models.models import Attendance, User, Room, UserRole
from backend.routers.auth import get_current_user
from datetime import datetime, timedelta
import pandas as pd
import io
from backend.utils.drive_api import setup_meet_folder, upload_file_to_drive
from backend.utils.redis_utils import get_redis

router = APIRouter(prefix="/attendance", tags=["attendance"])

@router.post("/{room_id}", response_class=HTMLResponse)
async def submit_attendance(
    room_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Only students can submit attendance facility usually, but we record for anyone who clicks.
    # The user said "khusus siswa" for the UI part, but let's just allow the record creation for the clicking user.
    
    time_limit = datetime.utcnow() - timedelta(hours=12)
    stmt = select(Attendance).where(
        Attendance.room_id == room_id, 
        Attendance.user_id == current_user.id,
        Attendance.created_at >= time_limit
    )
    result = await db.execute(stmt)
    if result.scalars().first():
        return """<div class="px-4 py-3 bg-emerald-500/10 text-emerald-400 rounded-2xl text-xs font-bold border border-emerald-500/20 flex items-center gap-2">
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
            Kehadiran Tercatat
        </div>"""

    new_attendance = Attendance(room_id=room_id, user_id=current_user.id)
    db.add(new_attendance)
    await db.commit()
    
    return """<div class="px-4 py-3 bg-emerald-500/20 text-emerald-400 rounded-2xl text-xs font-bold border border-emerald-500/30 flex items-center gap-2 animate-pulse">
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
            Berhasil Absen
        </div>"""

@router.get("/{room_id}/status", response_class=HTMLResponse)
async def get_attendance_status(
    room_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    time_limit = datetime.utcnow() - timedelta(hours=12)
    stmt = select(Attendance).where(
        Attendance.room_id == room_id, 
        Attendance.user_id == current_user.id,
        Attendance.created_at >= time_limit
    )
    result = await db.execute(stmt)
    if result.scalars().first():
        return """<div class="px-4 py-3 bg-emerald-500/10 text-emerald-400 rounded-2xl text-xs font-bold border border-emerald-500/20 flex items-center gap-2">
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
            Kehadiran Tercatat
        </div>"""
    
    return f"""<button hx-post="/attendance/{room_id}" hx-swap="outerHTML" 
        class="px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-2xl text-sm font-bold shadow-lg shadow-blue-900/20 transition-all flex items-center gap-2 active:scale-95">
        <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M12 4v16m8-8H4"/></svg>
        Klik Untuk Kehadiran
    </button>"""

@router.get("/{room_id}/export")
async def export_attendance(
    room_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Only host or admin can export
    room_stmt = select(Room).where(Room.id == room_id)
    room_res = await db.execute(room_stmt)
    room = room_res.scalars().first()
    
    if not room:
        raise HTTPException(status_code=404, detail="Room tidak ditemukan")
        
    role_str = str(current_user.role.value if hasattr(current_user.role, 'value') else current_user.role).upper()
    if room.host_id != current_user.id and role_str not in ["ADMIN", "GURU", "TU"]:
        raise HTTPException(status_code=403, detail="Hanya Host atau Moderator yang dapat mengekspor absen")

    stmt = select(Attendance, User).join(User, Attendance.user_id == User.id).where(Attendance.room_id == room_id)
    result = await db.execute(stmt)
    rows = result.all()
    
    data = []
    for att, user in rows:
        # Convert to WIB
        wib_time = att.created_at + timedelta(hours=7)
        data.append({
            "Email": user.email,
            "Nama Lengkap": user.full_name,
            "Role": user.role.value,
            "Waktu Absen (WIB)": wib_time.strftime("%Y-%m-%d %H:%M:%S")
        })
    
    if not data:
        # Return empty excel or info? Let's just return empty excel with headers.
        df = pd.DataFrame(columns=["Email", "Nama Lengkap", "Role", "Waktu Absen (WIB)"])
    else:
        df = pd.DataFrame(data)
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Absensi Meeting')
    
    output.seek(0)
    
    clean_title = "".join([c if c.isalnum() else "_" for c in room.title])
    filename = f"Absensi_{clean_title}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    
    headers = {
        'Content-Disposition': f'attachment; filename="{filename}"'
    }
    return StreamingResponse(output, headers=headers, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')



@router.post("/{room_id}/sync-drive")
async def sync_attendance_to_drive(
    room_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Export attendance to Excel and upload to BaknusDrive Meet folder.
    """
    try:
        # 1. Verification and data retrieval (same logic as export)
        room_stmt = select(Room).where(Room.id == room_id)
        room_res = await db.execute(room_stmt)
        room = room_res.scalars().first()
        
        if not room:
            raise HTTPException(status_code=404, detail="Room tidak ditemukan")
            
        role_str = str(current_user.role.value if hasattr(current_user.role, 'value') else current_user.role).upper()
        if room.host_id != current_user.id and role_str not in ["ADMIN", "GURU", "TU"]:
            raise HTTPException(status_code=403, detail="Hanya Host atau Moderator yang dapat mensinkronisasi absen")

        # Get Host data for BaknusDrive email target
        host_stmt = select(User).where(User.id == room.host_id)
        host_res = await db.execute(host_stmt)
        host = host_res.scalars().first()
        
        if not host:
            raise HTTPException(status_code=404, detail="Host tidak ditemukan")

        # 2. Get attendance data
        stmt = select(Attendance, User).join(User, Attendance.user_id == User.id).where(Attendance.room_id == room_id)
        result = await db.execute(stmt)
        rows = result.all()
        
        data = []
        for att, user in rows:
            wib_time = att.created_at + timedelta(hours=7)
            data.append({
                "Email": user.email,
                "Nama Lengkap": user.full_name,
                "Role": user.role.value,
                "Waktu Absen (WIB)": wib_time.strftime("%Y-%m-%d %H:%M:%S")
            })
        
        df = pd.DataFrame(data) if data else pd.DataFrame(columns=["Email", "Nama Lengkap", "Role", "Waktu Absen (WIB)"])
        
        # 3. Create Excel in memory
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Absensi Meeting')
        
        excel_content = output.getvalue()
        clean_title = "".join([c if c.isalnum() else "_" for c in room.title])
        filename = f"Absensi_{clean_title}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        
        # 4. Sync to Drive
        # First, ensure meet folder exists for this host
        await setup_meet_folder(teacher_email=host.email)
        
        # Then upload
        sync_res = await upload_file_to_drive(
            file_name=filename,
            file_content=excel_content,
            teacher_email=host.email,
            category="meet"
        )
        
        if "error" in sync_res:
            return JSONResponse(
                content={"detail": f"Gagal sinkron ke Drive: {sync_res['error']}"},
                status_code=500,
                headers={"HX-Trigger": json.dumps({"showToast": {"msg": "Gagal sinkron ke Drive", "type": "error"}})}
            )
            
        return JSONResponse(
            content={"status": "success"},
            headers={"HX-Trigger": json.dumps({"showToast": {"msg": "Absensi berhasil disimpan ke BaknusDrive!", "type": "success"}})}
        )
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"SYNC_DRIVE ERROR: {error_trace}")
        return JSONResponse(
            content={"detail": f"Error: {str(e)}", "trace": error_trace},
            status_code=500
        )


import json

@router.post("/{room_id}/sync-active")
async def sync_active_attendance(
    room_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis)
):
    """
    Moderator only: Force record attendance for all currently active participants in Redis.
    """
    try:
        role_str = str(current_user.role.value if hasattr(current_user.role, 'value') else current_user.role).upper()
        if role_str not in ["ADMIN", "GURU", "TU"]:
            raise HTTPException(status_code=403, detail="Hanya moderator yang dapat melakukan rekap absen")

        # 1. Get all active participant emails from Redis
        active_emails = await redis.smembers(f"room:{room_id}:presence")
        if not active_emails:
            return Response(
                content="Tidak ada peserta aktif yang terdeteksi",
                headers={"HX-Trigger": json.dumps({"showToast": {"msg": "Tidak ada peserta aktif terdeteksi", "type": "warning"}})}
            )

        # 2. Convert emails to strings (handling set and potential bytes)
        email_list = [e.decode('utf-8') if isinstance(e, bytes) else e for e in active_emails]

        # 3. Find users in DB by these emails
        user_stmt = select(User).where(User.email.in_(email_list))
        user_res = await db.execute(user_stmt)
        users = user_res.scalars().all()
        user_ids = [u.id for u in users]

        if not user_ids:
             return Response(content="User tidak ditemukan")

        # 4. Check who already has attendance
        existing_stmt = select(Attendance.user_id).where(
            Attendance.room_id == room_id, 
            Attendance.user_id.in_(user_ids)
        )
        existing_res = await db.execute(existing_stmt)
        already_attended = set(existing_res.scalars().all())

        # 5. Create missing attendance records
        added_count = 0
        for cid in user_ids:
            if cid not in already_attended:
                new_att = Attendance(room_id=room_id, user_id=cid)
                db.add(new_att)
                added_count += 1
        
        if added_count > 0:
            await db.commit()

        trigger_data = {
            "showToast": {
                "msg": f"Berhasil merekap {added_count} peserta baru",
                "type": "success"
            },
            "attendanceUpdate": {}
        }

        return JSONResponse(
            content={"message": f"Synced {added_count} participants", "count": added_count},
            headers={"HX-Trigger": json.dumps(trigger_data)}
        )
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"SYNC_ACTIVE ERROR: {error_trace}")
        return JSONResponse(
            content={"detail": f"Error: {str(e)}", "trace": error_trace},
            status_code=500
        )
