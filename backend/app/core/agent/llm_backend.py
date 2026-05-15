"""
llm_backend.py — Interface LLMBackend
Section 5 : Abstraction du modèle de langage utilisé par l'agent.

Correspond à l'interface LLMBackend du diagramme.
Implémentation concrète : OllamaLLMBackend (utilise le LLM existant du projet).
"""
import logging
from abc import ABC, abstractmethod
from typing import AsyncGenerator

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

INTENT_SYSTEM_PROMPT = """Tu es un classificateur d'intentions médicales.
Ta seule tâche est de répondre avec UN SEUL MOT parmi cette liste exacte :
CONSULT_PLANNING, CREATE_APPOINTMENT, MODIFY_APPOINTMENT, DELETE_APPOINTMENT, QUERY_PATIENT, MIXED

Règles :
- CONSULT_PLANNING  : consulter planning, voir disponibilités, agenda
- CREATE_APPOINTMENT: créer, prendre, réserver un rendez-vous
- MODIFY_APPOINTMENT: modifier, déplacer, changer un rendez-vous existant
- DELETE_APPOINTMENT: annuler, supprimer un rendez-vous
- QUERY_PATIENT     : question sur un dossier patient, antécédents, résumé
- MIXED             : plusieurs intentions mélangées

Réponds UNIQUEMENT avec le mot-clé, rien d'autre."""


class LLMBackend(ABC):
    """
    Interface abstraite pour les backends LLM.
    Correspond à LLMBackend <<Interface>> du diagramme.
    """

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """Génère une réponse synchrone."""
        ...

    @abstractmethod
    async def generate_stream(self, prompt: str) -> AsyncGenerator[str, None]:
        """Génère une réponse en streaming."""
        ...


class OllamaLLMBackend(LLMBackend):
    """
    Implémentation concrète utilisant le serveur Ollama du projet.
    Réutilise VLLM_BASE_URL et VLLM_MODEL depuis la config existante.
    """

    def __init__(self):
        base = getattr(settings, "VLLM_BASE_URL", "http://localhost:11434").rstrip("/")
        # Ollama native API (/api/generate) ne veut pas /v1 dans l'URL
        self.base_url = base[:-3] if base.endswith("/v1") else base
        self.model = getattr(settings, "VLLM_MODEL_NAME", "qwen2.5:1.5b-instruct")
        self.timeout = getattr(settings, "VLLM_TIMEOUT", 30)

    def generate(self, prompt: str) -> str:
        """Appel synchrone à Ollama /api/generate."""
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": 0.0, "num_predict": 32},
                    },
                )
                resp.raise_for_status()
                return resp.json().get("response", "").strip()
        except Exception as exc:
            logger.error("[OllamaLLMBackend] generate error: %s", exc)
            return ""

    async def generate_stream(self, prompt: str) -> AsyncGenerator[str, None]:
        """Appel streaming à Ollama."""
        import json
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/api/generate",
                    json={"model": self.model, "prompt": prompt, "stream": True},
                ) as resp:
                    async for line in resp.aiter_lines():
                        if line:
                            try:
                                data = json.loads(line)
                                token = data.get("response", "")
                                if token:
                                    yield token
                                if data.get("done"):
                                    break
                            except json.JSONDecodeError:
                                continue
        except Exception as exc:
            logger.error("[OllamaLLMBackend] stream error: %s", exc)
