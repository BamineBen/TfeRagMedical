from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker, AsyncEngine
from sqlalchemy.orm import declarative_base
from sqlalchemy import text
from app.config import settings

engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    pool_pre_ping=True,
    pool_recycle=3600,
)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession,
    expire_on_commit=False, autocommit=False, autoflush=False,
)

Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    import asyncio, logging
    logger = logging.getLogger(__name__)
    from app.models import user, document, chunk, conversation, message, setting, note  # noqa

    for attempt in range(1, 6):
        try:
            # TRANSACTION 1 : pgvector (peut échouer — transaction isolée)
            # Si on met CREATE EXTENSION dans la même transaction que create_all,
            # une erreur sur l'extension corrompt toute la transaction.
            try:
                async with engine.begin() as conn:
                    await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                    logger.info("✓ pgvector activé")
            except Exception as e:
                logger.warning(f"pgvector non disponible (normal en local Windows) : {e}")
                # On continue — FAISS gère les vecteurs, pgvector est facultatif

            # TRANSACTION 2 : création des tables (transaction propre, sans erreur pgvector)
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            # TRANSACTION 3 : migration légère (idempotente)
            try:
                async with engine.begin() as conn:
                    await conn.execute(text(
                        "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
                        "preferred_llm_mode VARCHAR(20) NOT NULL DEFAULT 'local'"
                    ))
            except Exception:
                pass  # Colonne déjà présente — normal

            logger.info("✓ Database initialized")
            return

        except Exception as e:
            if attempt < 5:
                logger.warning(f"DB attempt {attempt}/5: {e}. Retry in 3s...")
                await asyncio.sleep(3)
            else:
                raise


async def close_db() -> None:
    await engine.dispose()