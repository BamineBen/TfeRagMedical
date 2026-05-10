"""
gpu_manager.py — Gestionnaire GPU (désactivé — Ollama sur VPS Contabo).

Le backend GPU Vast.ai a été remplacé par Ollama hébergé sur le VPS Contabo
(161.97.111.13:11434). Ce module expose uniquement un singleton GPUManager
inactif pour maintenir la compatibilité avec dashboard.py.
"""
from enum import Enum


class GPUStatus(str, Enum):
    OFF = "off"


class GPUManager:
    """Stub GPU manager — tous les appels sont des no-ops."""

    @property
    def is_configured(self) -> bool:
        return False

    async def touch(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    async def get_status_info(self) -> dict:
        return {
            "status": GPUStatus.OFF,
            "idle_seconds": 0,
            "idle_shutdown_minutes": 0,
            "error": None,
            "ollama_url": "http://161.97.111.13:11434/v1",
            "ollama_model": "qwen2.5:3b-instruct",
        }


_gpu_manager: GPUManager | None = None


def get_gpu_manager() -> GPUManager:
    global _gpu_manager
    if _gpu_manager is None:
        _gpu_manager = GPUManager()
    return _gpu_manager
