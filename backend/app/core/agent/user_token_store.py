"""
user_token_store.py — UserTokenStore
Section 5 : Persistance des tokens OAuth2 Google par utilisateur.

Correspond à UserTokenStore du diagramme.
Stocke les credentials Google de chaque médecin sur disque (JSON).
Chemin : /app/data/google_tokens/{user_id}.json
"""
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Docker : /app/data/google_tokens  |  Windows local : data/google_tokens (relatif)
_DEFAULT_DIR = (
    "data/google_tokens" if sys.platform == "win32" else "/app/data/google_tokens"
)
_STORAGE_DIR = Path(os.getenv("GOOGLE_TOKENS_DIR", _DEFAULT_DIR))


class UserTokenStore:
    """
    Stockage fichier des tokens Google OAuth2 par user_id.
    Correspond à UserTokenStore du diagramme.
    Thread-safe en lecture/écriture car chaque user a son propre fichier.
    """

    def __init__(self, storage_dir: Optional[Path] = None):
        self.storage_dir = storage_dir or _STORAGE_DIR
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, user_id: int) -> Path:
        return self.storage_dir / f"{user_id}.json"

    def save_tokens(self, user_id: int, credentials) -> None:
        """
        Persiste les credentials Google d'un utilisateur.
        credentials : instance GoogleCredentials
        """
        data = {
            "client_id":     credentials.client_id,
            "client_secret": credentials.client_secret,
            "redirect_uri":  credentials.redirect_uri,
            "refresh_token": credentials.refresh_token,
            "access_token":  credentials.access_token,
            "expires_at":    credentials.expires_at.isoformat() if credentials.expires_at else None,
        }
        with open(self._path(user_id), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.info("[UserTokenStore] Tokens sauvegardés pour user %d", user_id)

    def load_tokens(self, user_id: int):
        """
        Charge les credentials Google depuis le disque.
        Retourne None si non trouvé.
        """
        path = self._path(user_id)
        if not path.exists():
            return None
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            # Import local pour éviter les imports circulaires
            from app.core.agent.calendar_service import GoogleCredentials
            expires_at = None
            if data.get("expires_at"):
                expires_at = datetime.fromisoformat(data["expires_at"])
            return GoogleCredentials(
                client_id=data["client_id"],
                client_secret=data["client_secret"],
                redirect_uri=data.get("redirect_uri", ""),
                refresh_token=data.get("refresh_token", ""),
                access_token=data.get("access_token", ""),
                expires_at=expires_at,
            )
        except Exception as exc:
            logger.error("[UserTokenStore] Erreur chargement user %d : %s", user_id, exc)
            return None

    def delete_tokens(self, user_id: int) -> None:
        """Supprime les tokens d'un utilisateur (révocation)."""
        path = self._path(user_id)
        if path.exists():
            path.unlink()
            logger.info("[UserTokenStore] Tokens supprimés pour user %d", user_id)

    def has_tokens(self, user_id: int) -> bool:
        """Vérifie si un utilisateur a des tokens stockés."""
        path = self._path(user_id)
        if not path.exists():
            return False
        creds = self.load_tokens(user_id)
        return creds is not None and bool(creds.refresh_token)
