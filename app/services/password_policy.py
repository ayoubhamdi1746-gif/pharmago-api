import re

MIN_LENGTH = 8
MAX_LENGTH = 128

class PasswordError(ValueError):
    pass

COMMON_PASSWORDS = {"password", "password123", "admin", "12345678", "qwerty123", "letmein", "welcome", "Password123", "Password1", "Welcome1", "changeme"}

def validate_password(password: str) -> None:
    if len(password) < MIN_LENGTH:
        raise PasswordError(f"Password must be at least {MIN_LENGTH} characters")
    if len(password) > MAX_LENGTH:
        raise PasswordError(f"Password must not exceed {MAX_LENGTH} characters")
    if not re.search(r"[A-Z]", password):
        raise PasswordError("Password must contain at least one uppercase letter")
    if not re.search(r"[a-z]", password):
        raise PasswordError("Password must contain at least one lowercase letter")
    if not re.search(r"\d", password):
        raise PasswordError("Password must contain at least one digit")
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>_\-+=~`\[\];'\\/]", password):
        raise PasswordError("Password must contain at least one special character")
    normalized = password.lower().replace("!", "").replace("@", "").replace("#", "").replace("$", "").replace("%", "").replace("^", "").replace("&", "").replace("*", "")
    if normalized in COMMON_PASSWORDS:
        raise PasswordError("Password is too common")
