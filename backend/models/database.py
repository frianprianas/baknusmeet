from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://user:password@localhost:5432/baknusmeet")

engine = create_async_engine(
    DATABASE_URL, 
    echo=False, 
    pool_size=10, 
    max_overflow=20, 
    pool_timeout=30,
    pool_recycle=600,       # Recycle connections every 10 minutes (prevents stale TCP)
    pool_pre_ping=True,     # Test connection health before using it
)
AsyncSessionLocal = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
