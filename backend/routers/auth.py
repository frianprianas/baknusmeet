from fastapi import APIRouter, Depends, HTTPException, status, Response, Request, Form
import httpx
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import timedelta
from jose import jwt, JWTError
from typing import Optional

from backend.models.database import get_db
from backend.models.models import User, UserRole
from backend.schemas.schemas import AuthLogin, Token, UserResponse, UserCreate
from backend.utils.imap_auth import validate_credentials
from backend.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="backend/templates")

from backend.utils.mailcow_api import get_mailcow_mailbox_data, get_mailcow_avatar_bytes

@router.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    # Auto-append domain if missing (Simplifying login for students/staff)
    if "@" not in email:
        email = f"{email}@smk.baktinusantara666.sch.id"

    # 1. Validate with IMAP
    try:
        is_valid = await validate_credentials(email, password, settings)
    except Exception as e:
        return templates.TemplateResponse(request=request, name="login.html", context={"error": "Koneksi ke server Mailcow gagal."})
        
    if not is_valid:
        return templates.TemplateResponse(request=request, name="login.html", context={"error": "Email atau password salah."})
    
    # 2. Get data from Mailcow API for role and profile assignment
    mailbox = await get_mailcow_mailbox_data(email, settings.MAILCOW_API_URL, settings.MAILCOW_API_KEY)
    
    tags = []
    full_name = email.split("@")[0].replace(".", " ").title()
    is_active = 1
    
    if mailbox:
        tags = mailbox.get("tags", [])
        full_name = mailbox.get("name", full_name)
        is_active = 1 if mailbox.get("active", True) else 0

    # Mapping logic (Case-insensitive)
    tags_lower = [t.lower() for t in tags]
    if "admin" in tags_lower:
        role = UserRole.ADMIN
    elif "tu" in tags_lower:
        role = UserRole.TU
    elif "guru" in tags_lower:
        role = UserRole.GURU
    else:
        role = UserRole.SISWA

    # 3. Get user from local DB
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalars().first()
    
    # 4. Create or update user
    if not user:
        user = User(
            email=email,
            full_name=full_name,
            role=role,
            is_active=is_active
        )
        db.add(user)
    else:
        # Sync profile if it changed in Mailcow
        user.full_name = full_name
        user.role = role
        user.is_active = is_active
    
    await db.commit()
    await db.refresh(user)

    # 5. Generate JWT
    access_token = create_access_token(data={"sub": user.email})
    
    # Check for next redirect
    next_url = request.query_params.get("next") or "/dashboard"
    if "/login" in next_url: next_url = "/dashboard"
    
    # Redirect with cookie
    response = RedirectResponse(url=next_url, status_code=303)
    response.set_cookie(key="access_token", value=access_token, httponly=True, max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)
    
    return response

@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("access_token")
    return response

async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    token = request.cookies.get("access_token")
    auth_header = request.headers.get("Authorization")
    
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
    )
    
    if not token:
        raise credentials_exception
        
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
        
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalars().first()
    if user is None:
        raise credentials_exception
    
    if user.is_active == 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Akun Anda dinonaktifkan oleh administrator",
        )
    return user

@router.get("/avatar-proxy/{email}")
async def avatar_proxy(email: str):
    """
    Proxy the avatar image from Mailcow to avoid CORS and Privacy issues.
    """
    from backend.utils.mailcow_api import get_mailcow_avatar_bytes
    try:
        image_bytes = await get_mailcow_avatar_bytes(email, settings.MAILCOW_API_URL, settings.MAILCOW_API_KEY)
        if not image_bytes:
            # Fallback to UI-Avatars if mailcow avatar is not found
            async with httpx.AsyncClient() as client:
                res = await client.get(f"https://ui-avatars.com/api/?name={email}&background=random")
                if res.status_code == 200:
                    return Response(content=res.content, media_type="image/png")
            raise HTTPException(status_code=404)
        
        return Response(content=image_bytes, media_type="image/jpeg") # Mailcow usually returns JPEG/PNG
    except Exception as e:
        print(f"PROXY ERROR: {e}")
        raise HTTPException(status_code=500, detail=str(e))
