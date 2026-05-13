import secrets
import bcrypt as _bcrypt


def generate_otp() -> tuple[str, str]:
    otp = str(secrets.randbelow(900000) + 100000)
    hashed = _bcrypt.hashpw(otp.encode(), _bcrypt.gensalt()).decode()
    return otp, hashed


def verify_otp(otp: str, otp_hash: str) -> bool:
    try:
        return _bcrypt.checkpw(otp.encode(), otp_hash.encode())
    except ValueError:
        return False
