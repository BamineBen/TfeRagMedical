"""
settings.py — Endpoints FastAPI pour la configuration système (admin uniquement).

Gère les toggles on/off des services cloud (Gemini, Mistral, outils LLM)
stockés dans la table `system_settings`.

Les clés API ne sont jamais retournées en clair — seulement un aperçu masqué
(4 premiers + 6 derniers caractères) pour confirmer qu'une clé est configurée.
"""
from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentAdminUser, DBSession
from app.config import settings
from app.models.setting import SystemSetting

router = APIRouter()


class SettingsResponse(BaseModel):
    """État actuel des services cloud."""
    gemini_enabled     : bool
    gemini_configured  : bool
    gemini_key_preview : str|None

    mistral_enabled     : bool
    mistral_configured  : bool
    mistral_key_preview : str|None

    ollama_url     : str              # URL du serveur Ollama (VPS)
    ollama_model   : str              # Modèle qwen actif

    tools_enabled : bool


class SettingsUpdate(BaseModel):
    """Mettre à jour les toggles (tous optionnels)."""
    gemini_enabled  : bool|None = None
    mistral_enabled : bool|None = None
    tools_enabled   : bool|None = None


#  Helpers DRY 

def _mask_key(key: str|None) -> str|None:
    """
    Masque une clé API pour l'affichage.
    Affiche les 4 premiers et 6 derniers caractères, remplace le reste par ****.
    Retourne None si la clé est absente ou trop courte.
    """
    if not key or len(key) < 12:
        return None
    return f"{key[:4]}****{key[-6:]}"


async def _get_toggle(db, key: str, default: str = "true") -> bool:
    """Lit un toggle booléen depuis la table system_settings."""
    row = (await db.execute(select(SystemSetting).where(SystemSetting.key == key))).scalar_one_or_none()
    return (row.value if row else default).lower() == "true"


#  Endpoints 

@router.get("", response_model=SettingsResponse)
async def get_settings(db: DBSession, _: CurrentAdminUser):
    """Retourne la configuration actuelle des services cloud."""
    return SettingsResponse(
        gemini_enabled     = await _get_toggle(db, "gemini_enabled"),
        gemini_configured  = bool(settings.GEMINI_API_KEY),
        gemini_key_preview = _mask_key(settings.GEMINI_API_KEY),
        mistral_enabled     = await _get_toggle(db, "mistral_enabled"),
        mistral_configured  = bool(settings.MISTRAL_API_KEY),
        mistral_key_preview = _mask_key(settings.MISTRAL_API_KEY),
        ollama_url   = settings.LOCAL_LLM_BASE_URL,
        ollama_model = settings.LOCAL_LLM_MODEL_NAME,
        tools_enabled = await _get_toggle(db, "tools_enabled"),
    )


@router.put("", response_model=SettingsResponse)
async def update_settings(update: SettingsUpdate, db: DBSession, current_user: CurrentAdminUser):
    """
    Met à jour les toggles des services cloud.
    Crée les clés si elles n'existent pas encore (INSERT OR UPDATE).
    """
    changes = {k: str(v).lower() for k, v in update.model_dump().items() if v is not None}

    for key, value in changes.items():
        row = (await db.execute(select(SystemSetting).where(SystemSetting.key == key))).scalar_one_or_none()
        if row:
            row.value      = value
            row.updated_by = current_user.id
        else:
            db.add(SystemSetting(key=key, value=value, updated_by=current_user.id))

    await db.commit()
    return await get_settings(db, current_user)
