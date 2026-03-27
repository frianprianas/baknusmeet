import logging
import traceback
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import json
import os

from backend.config import settings
from backend.models.database import engine, get_db
from backend.models.models import Base, User, UserRole
from backend.routers import auth, rooms, participants, admin, attendance, external
from backend.routers.auth import get_current_user
from backend.utils.redis_utils import init_redis, get_redis

app = FastAPI(title="BaknusMeet")

@app.exception_handler(HTTPException)
async def auth_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == 401:
        # If it's an HTMX request, we might need a different header, but for simple links, redirect is fine.
        return RedirectResponse(
            url=f"/login?next={request.url}", 
            status_code=status.HTTP_303_SEE_OTHER
        )
    if str(request.url.path).startswith("/api") or request.headers.get("accept") == "application/json":
        return JSONResponse(content={"detail": str(exc.detail)}, status_code=exc.status_code)
    return HTMLResponse(content=str(exc.detail), status_code=exc.status_code)

from fastapi import status # Import status if not present

# Templates and Static Files
templates = Jinja2Templates(directory="backend/templates")
app.mount("/static", StaticFiles(directory="backend/static"), name="static")

# CORS setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Startup event
@app.on_event("startup")
async def startup():
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await init_redis()
    except Exception as e:
        print(f"STARTUP ERROR: {e}")
        traceback.print_exc()
        raise e

# Include routers
app.include_router(auth.router)
app.include_router(rooms.router)
app.include_router(participants.router)
app.include_router(admin.router)
app.include_router(attendance.router)
app.include_router(external.router)

@app.get("/")
async def root(request: Request):
    token = request.cookies.get("access_token")
    if token:
        return RedirectResponse(url="/dashboard", status_code=302)
    return RedirectResponse(url="/login", status_code=302)

@app.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"request": request})

@app.get("/dashboard")
async def dashboard_page(request: Request, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # Fetch potential moderators (GURU or TU) for room creation (used by Admin)
    moderators = []
    if current_user.role == UserRole.ADMIN:
        result = await db.execute(
            select(User).where(User.role.in_([UserRole.GURU, UserRole.TU])).order_by(User.full_name)
        )
        moderators = result.scalars().all()
        
    return templates.TemplateResponse(request, "dashboard.html", {
        "user": current_user,
        "moderators": moderators
    })

@app.get("/admin/management")
async def admin_management_page(request: Request, current_user: User = Depends(get_current_user)):
    if current_user.role != UserRole.ADMIN:
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse(request, "admin_management.html", {"user": current_user})

@app.get("/room/{room_id}")
async def room_page(request: Request, room_id: int, current_user: User = Depends(get_current_user)):
    return templates.TemplateResponse(request, "room.html", {"room_id": room_id, "user": current_user})

# WebSocket Presence Manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[int, list[WebSocket]] = {}
    async def connect(self, room_id: int, websocket: WebSocket):
        await websocket.accept()
        if room_id not in self.active_connections:
            self.active_connections[room_id] = []
        self.active_connections[room_id].append(websocket)
    def disconnect(self, room_id: int, websocket: WebSocket):
        if room_id in self.active_connections:
            try:
                self.active_connections[room_id].remove(websocket)
            except ValueError:
                pass
            # Clean up empty room lists to prevent memory leak
            if not self.active_connections[room_id]:
                del self.active_connections[room_id]
    async def broadcast_presence_update(self, room_id: int, redis):
        try:
            active_users = await redis.smembers(f"room:{room_id}:presence")
            message = json.dumps({"type": "presence", "count": len(active_users), "users": list(active_users)})
            if room_id in self.active_connections:
                dead = []
                for connection in self.active_connections[room_id]:
                    try:
                        await connection.send_text(message)
                    except Exception:
                        dead.append(connection)
                for d in dead:
                    self.disconnect(room_id, d)
        except Exception as e:
            print(f"WS broadcast error: {e}")

manager = ConnectionManager()

@app.websocket("/ws/presence/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: int):
    redis = await get_redis()
    await manager.connect(room_id, websocket)
    try:
        await manager.broadcast_presence_update(room_id, redis)
        while True:
            # Timeout after 120s of silence to kill zombie connections
            import asyncio
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=120.0)
            except asyncio.TimeoutError:
                # Client went silent, send a ping to check if alive
                try:
                    await websocket.send_text(json.dumps({"type": "ping"}))
                except Exception:
                    break  # Connection is dead
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WS error for room {room_id}: {e}")
    finally:
        # ALWAYS clean up, no matter what exception
        manager.disconnect(room_id, websocket)
        try:
            await manager.broadcast_presence_update(room_id, redis)
        except Exception:
            pass

