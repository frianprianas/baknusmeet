from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional, List
from backend.models.models import UserRole, RoomStatus

class UserBase(BaseModel):
    email: EmailStr
    full_name: str
    role: UserRole

class UserCreate(UserBase):
    pass

class UserResponse(UserBase):
    id: int
    created_at: datetime
    class Config:
        from_attributes = True

class RoomBase(BaseModel):
    title: str
    scheduled_at: Optional[datetime] = None
    duration: int = 60

class RoomCreate(RoomBase):
    pass

class RoomUpdate(BaseModel):
    title: Optional[str] = None
    status: Optional[RoomStatus] = None
    scheduled_at: Optional[datetime] = None
    duration: Optional[int] = None

class RoomResponse(RoomBase):
    id: int
    host_id: int
    jitsi_room_id: str
    status: RoomStatus
    created_at: datetime
    class Config:
        from_attributes = True

class ParticipantResponse(BaseModel):
    id: int
    room_id: int
    user_id: int
    joined_at: datetime
    left_at: Optional[datetime] = None
    user: Optional[UserResponse] = None
    class Config:
        from_attributes = True

class AuthLogin(BaseModel):
    email: EmailStr
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse

class TokenData(BaseModel):
    email: Optional[str] = None
