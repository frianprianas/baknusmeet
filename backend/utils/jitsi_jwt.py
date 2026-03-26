import time
from jose import jwt
from typing import Optional

def generate_jitsi_jwt(
    app_id: str,
    app_secret: str,
    room_name: str,
    user_email: str,
    user_name: str,
    is_moderator: bool = False,
    expiry_minutes: int = 240,
    sub: str = "192.168.100.222",
    exp_timestamp: Optional[int] = None
) -> str:
    """
    Generate JWT for Jitsi-Meet authentication based on the standard Jitsi JWT format.
    """
    now = int(time.time())
    
    # Standard Jitsi JWT Claims with room validation
    # Add clock skew buffer (1 minute)
    iat = now - 60
    nbf = iat
    exp_val = exp_timestamp if exp_timestamp is not None else now + (expiry_minutes * 60)
    
    payload = {
        "aud": app_id,
        "iss": app_id,
        "sub": sub, 
        "room": room_name,
        "iat": iat,
        "nbf": nbf,
        "exp": exp_val,
        "context": {
            "user": {
                "name": user_name,
                "email": user_email,
                "avatar": f"https://baknusmail.smkbn666.sch.id/api/auth/avatar/{user_email}",
                "id": user_email,
                "affiliation": "owner" if is_moderator else "member"
            },
            "features": {
                "livestreaming": is_moderator,
                "recording": is_moderator,
                "transcription": is_moderator,
                "outbound-call": False
            }
        }
    }
    
    token = jwt.encode(payload, app_secret, algorithm="HS256")
    return token
