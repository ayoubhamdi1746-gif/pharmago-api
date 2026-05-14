"""
create_founders.py — Crée les 2 comptes co-founders super_admin sur Railway.
Usage: railway run python create_founders.py
"""

import os
import hashlib
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Import models
from app.models.user import User
from app.models.billing import PharmacySubscription, SubscriptionPlan

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)

FOUNDERS = [
    {
        "username": "ayoub",
        "email": "ayoubhamdi1746@gmail.com",
        "password": "soniahamdi1921",
        "role": "super_admin",
    },
    {
        "username": "eya",
        "email": "eyarzeigui218@gmail.com",
        "password": "blaj_bac2025",
        "role": "super_admin",
    },
]


async def run():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("❌ DATABASE_URL not set")
        return

    engine = create_async_engine(database_url, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        # Create pharmacy subscription for co-founders
        existing_sub = await session.execute(
            select(PharmacySubscription).where(PharmacySubscription.plan == SubscriptionPlan.PRO)
        )
        if not existing_sub.scalar_one_or_none():
            pharmacy_id = str(uuid.uuid4())
            session.add(PharmacySubscription(
                id=uuid.UUID(pharmacy_id),
                pharmacy_id=uuid.UUID(pharmacy_id),
                pharmacy_name="PharmaGo HQ",
                city="Tunis",
                responsible_name="Co-Founders",
                plan=SubscriptionPlan.PRO,
                price_tnd=Decimal("0.00"),
                started_at=datetime.utcnow(),
                expires_at=datetime.utcnow() + timedelta(days=3650),
                is_active=True,
                delivery_count_this_month=0,
                delivery_limit=None,
                total_delivery_earnings=Decimal("0.00"),
            ))

        for founder in FOUNDERS:
            existing = await session.execute(
                select(User).where(User.username == founder["username"])
            )
            user = existing.scalar_one_or_none()

            identity_id = hashlib.sha256(
                f"{founder['username']}:{founder['email']}".encode()
            ).hexdigest()

            if user:
                user.role = founder["role"]
                user.email = founder["email"]
                user.identity_id = identity_id
                user.hashed_password = pwd_context.hash(founder["password"])
                user.is_active = True
                print(f"✅ {founder['username']} mis à jour → super_admin")
            else:
                session.add(User(
                    id=str(uuid.uuid4()),
                    username=founder["username"],
                    email=founder["email"],
                    role=founder["role"],
                    identity_id=identity_id,
                    hashed_password=pwd_context.hash(founder["password"]),
                    is_active=True,
                ))
                print(f"✅ {founder['username']} créé")

        # Delete demo admin account
        demo_admin = await session.execute(
            select(User).where(User.username == "admin")
        )
        demo_user = demo_admin.scalar_one_or_none()
        if demo_user:
            demo_user.is_active = False
            print("🗑️  compte admin demo désactivé (soft delete)")
        else:
            print("ℹ️  aucun compte admin demo à supprimer")

        await session.commit()

    await engine.dispose()
    print("\n🎉 Toutes les opérations terminées.")


if __name__ == "__main__":
    import asyncio
    asyncio.run(run())