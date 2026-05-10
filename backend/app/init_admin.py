import os, asyncio, logging
from datetime import datetime, timezone
from app.database import AsyncSessionLocal
from app.models.user import User, UserRole
from passlib.context import CryptContext

logger = logging.getLogger(__name__)
pwd_context = CryptContext(schemes=['bcrypt'], deprecated='auto')
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')

async def init_admin_user():
    try:
        async with AsyncSessionLocal() as db:
            from sqlalchemy import select
            result = await db.execute(select(User).where(User.username == ADMIN_USERNAME))
            existing = result.scalar_one_or_none()
            if existing:
                existing.email = f'{ADMIN_USERNAME}@ragmedical.com'
                existing.hashed_password = pwd_context.hash(ADMIN_PASSWORD)
                existing.role = UserRole.ADMIN
                existing.is_active = True
                await db.commit()
                logger.info(f"✓ Admin {ADMIN_USERNAME} synchronisé")
                return
            admin = User(
                email=f'{ADMIN_USERNAME}@ragmedical.com',
                username=ADMIN_USERNAME,
                hashed_password=pwd_context.hash(ADMIN_PASSWORD),
                full_name='Administrateur', role=UserRole.ADMIN,
                is_active=True, is_verified=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )
            db.add(admin)
            await db.commit()
            logger.info(f"✓ Admin {ADMIN_USERNAME} créé")
    except Exception as e:
        logger.error(f"Erreur init admin: {e}")