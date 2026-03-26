# BaknusMeet - Official Meeting Solution

A premium video conferencing platform built for SMK Bakti Nusantara 666.

## 🚀 Tech Stack
- **Backend:** Python FastAPI + SQLAlchemy (Async)
- **Frontend:** Next.js 14 (App Router) + Tailwind CSS + Framer Motion
- **Database:** PostgreSQL
- **Cache/Presence:** Redis (Real-time tracking)
- **Auth:** Mailcow IMAP Validation + JWT
- **Video:** Self-hosted Jitsi Meet

## 🛠 Setup & Run

### 1. Requirements
- Docker & Docker Compose
- Mailcow Instance access

### 2. Configuration
Edit `.env` and `jitsi.env` with your credentials:
- `MAILCOW_API_KEY`
- `JWT_SECRET`
- `JITSI_APP_SECRET`

### 3. Running with Docker Compose
```bash
docker-compose up --build
```

### 4. Direct Development Run
**Backend:**
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

## 🔐 Security Features
- **IMAP Validation:** Secure login using official school email.
- **Jitsi JWT:** Only authenticated users can join rooms.
- **Moderation:** Automatic host privileges for teachers.
- **Real-time Presence:** See who's currently in the room.

## 🎨 Design Philosophy
- **Modern & Immersive:** Dark mode, glassmorphism, and smooth transitions.
- **Responsive:** Optimized for desktop, tablet, and mobile.
- **Branded:** Custom elements tailored for Baknus identity.
