from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, func
from app.database import Base


class PasswordResetOTP(Base):
    __tablename__ = "password_reset_otps"

    email = Column(String(255), primary_key=True)
    otp_hash = Column(String(255), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
