from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def user_or_ip_key(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            from app.services.auth_service import decode_token
            payload = decode_token(auth[7:])
            if payload and payload.get("sub"):
                return f"user:{payload['sub']}"
        except Exception:
            pass
    return get_remote_address(request)


limiter = Limiter(key_func=user_or_ip_key)
