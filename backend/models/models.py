from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum as SQLEnum, Text, JSON
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime
import enum
import uuid

Base = declarative_base()

class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    TU = "TU"
    GURU = "GURU"
    SISWA = "SISWA"

class RoomStatus(str, enum.Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=False)
    role = Column(SQLEnum(UserRole), default=UserRole.SISWA)
    is_active = Column(Integer, default=1) # 1=Active, 0=Inactive
    created_at = Column(DateTime, default=datetime.utcnow)

    rooms_hosted = relationship("Room", back_populates="host")
    participations = relationship("Participant", back_populates="user")

class Room(Base):
    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    host_id = Column(Integer, ForeignKey("users.id"))
    jitsi_room_id = Column(String, unique=True, index=True, default=lambda: str(uuid.uuid4()))
    scheduled_at = Column(DateTime, nullable=True)
    duration = Column(Integer, default=60) # minutes
    status = Column(SQLEnum(RoomStatus), default=RoomStatus.SCHEDULED)
    created_at = Column(DateTime, default=datetime.utcnow)

    host = relationship("User", back_populates="rooms_hosted")
    participants = relationship("Participant", back_populates="room", cascade="all, delete-orphan")
    sessions = relationship("Session", back_populates="room", cascade="all, delete-orphan")
    attendance_records = relationship("Attendance", back_populates="room", cascade="all, delete-orphan")

class Participant(Base):
    __tablename__ = "participants"

    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    joined_at = Column(DateTime, default=datetime.utcnow)
    left_at = Column(DateTime, nullable=True)

    room = relationship("Room", back_populates="participants")
    user = relationship("User", back_populates="participations")

class Session(Base):
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id"))
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)

    room = relationship("Room", back_populates="sessions")

class Attendance(Base):
    __tablename__ = "attendance"

    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    room = relationship("Room", back_populates="attendance_records")
    user = relationship("User")
