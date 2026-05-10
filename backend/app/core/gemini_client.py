"""
gemini_client.py — Client Google Gemini via REST direct (sans SDK officiel).

RÔLE
─────
Appelle l'API Gemini (generateContent + streamGenerateContent) directement
en HTTP avec httpx, sans dépendance au SDK google-generativeai volumineux.

MODÈLE PAR DÉFAUT : gemini-2.5-flash
  → Fenêtre contexte : 1M tokens
  → Sortie max       : 65K tokens
  → thinkingBudget=0  : désactive le mode "thinking" pour réduire la latence

GESTION DES ERREURS
────────────────────
  429 → quota atteint → message lisible retourné (pas d'exception)
  404 → modèle inconnu → fallback automatique sur gemini-2.5-flash
  Retry automatique (tenacity) : 3 tentatives avec backoff exponentiel

MÉTHODES PUBLIQUES
───────────────────
  generate()        → LLMResponse (non-streaming)
  generate_stream() → AsyncGenerator[str] (streaming SSE)

get_gemini_client() → instance singleton
"""
import json
import logging
from typing import AsyncGenerator, Dict, List
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.llm_client import LLMMessage, LLMResponse
from app.config import settings

logger = logging.getLogger(__name__)


class GeminiClient:
    """Client Google Gemini via API REST (sans SDK officiel)."""

    def __init__(self, api_key: str = None, model: str = "gemini-2.5-flash"):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = model
        self.base_url = "https://generativelanguage.googleapis.com/v1beta/models"

    def _convert_messages(self, messages: List[LLMMessage]) -> List[Dict]:
        """Converts OpenAI-style messages to Gemini format"""
        gemini_contents = []
        for msg in messages:
            role = "user" if msg.role == "user" else "model"
            gemini_contents.append({
                "role": role,
                "parts": [{"text": msg.content}]
            })
        return gemini_contents

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def generate(
        self,
        messages: List[LLMMessage],
        system_prompt: str = None,
        max_tokens: int = 1000
    ) -> LLMResponse:
        """Generates content using Gemini."""
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not found")

        url = f"{self.base_url}/{self.model}:generateContent?key={self.api_key}"

        gen_config: dict = {"maxOutputTokens": max_tokens, "temperature": 0.1}
        # thinkingBudget:0 désactive le mode "thinking" — supporté uniquement sur Flash
        if "flash" in self.model.lower():
            gen_config["thinkingConfig"] = {"thinkingBudget": 0}

        payload = {
            "contents": self._convert_messages(messages),
            "generationConfig": gen_config,
        }

        if system_prompt:
             payload["systemInstruction"] = {
                "parts": [{"text": system_prompt}]
            }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, timeout=120.0)
                response.raise_for_status()
                data = response.json()

                # Extract text
                content = ""
                try:
                    content = data["candidates"][0]["content"]["parts"][0]["text"]
                except (KeyError, IndexError):
                    logger.warning(f"Unusual Gemini response structure: {data}")
                    if "candidates" in data and data["candidates"][0].get("finishReason") == "SAFETY":
                         content = "[Blocage de sécurité par Gemini]"

                usage = {
                    "prompt_tokens": data.get("usageMetadata", {}).get("promptTokenCount", 0),
                    "completion_tokens": data.get("usageMetadata", {}).get("candidatesTokenCount", 0)
                }

                return LLMResponse(
                    content=content,
                    finish_reason="stop",
                    usage=usage,
                    model=self.model
                )

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    return LLMResponse(
                        content="Le quota de l'API Gemini a été atteint. Veuillez réessayer dans quelques minutes ou utiliser le Mode Expert (local).",
                        finish_reason="quota",
                        usage={"prompt_tokens": 0, "completion_tokens": 0},
                        model=self.model
                    )
                logger.error(f"Gemini API Error: {e.response.text}")
                raise
            except Exception as e:
                logger.error(f"Gemini Client Error: {type(e).__name__}: {e}")
                raise

    async def generate_stream(
        self,
        messages: List[LLMMessage],
        system_prompt: str = None,
        max_tokens: int = 1000
    ) -> AsyncGenerator[str, None]:
        """Streams content using Gemini."""
        if not self.api_key:
            yield "[Erreur: Clé API Gemini manquante]"
            return

        url = f"{self.base_url}/{self.model}:streamGenerateContent?alt=sse&key={self.api_key}"

        gen_config: dict = {"maxOutputTokens": max_tokens, "temperature": 0.1}
        if "flash" in self.model.lower():
            gen_config["thinkingConfig"] = {"thinkingBudget": 0}

        payload = {
            "contents": self._convert_messages(messages),
            "generationConfig": gen_config,
        }

        if system_prompt:
             payload["systemInstruction"] = {
                "parts": [{"text": system_prompt}]
            }

        async with httpx.AsyncClient() as client:
            try:
                async with client.stream("POST", url, json=payload, timeout=120.0) as response:
                    response.raise_for_status()

                    async for line in response.aiter_lines():
                        if line.startswith("data:"):
                            data_str = line[5:].strip()
                            if not data_str: continue

                            try:
                                data = json.loads(data_str)
                                part = data["candidates"][0]["content"]["parts"][0]
                                if "text" in part:
                                    yield part["text"]
                            except (KeyError, IndexError, json.JSONDecodeError):
                                continue

            except httpx.HTTPStatusError as e:
                try:
                    await e.response.aread()
                    error_body = e.response.text
                except Exception:
                    error_body = f"HTTP {e.response.status_code}"
                logger.error(f"Gemini Stream Error: {error_body}")

                if e.response.status_code == 429:
                    yield "Le quota de l'API Gemini a été atteint. Veuillez réessayer dans quelques minutes ou utiliser le Mode Expert (local)."
                elif e.response.status_code == 404:
                    logger.warning(f"Modèle {self.model} introuvable (404) — fallback gemini-2.5-flash")
                    if self.model != "gemini-2.5-flash":
                        fallback = GeminiClient(api_key=self.api_key, model="gemini-2.5-flash")
                        async for chunk in fallback.generate_stream(
                            messages=messages, system_prompt=system_prompt, max_tokens=max_tokens
                        ):
                            yield chunk
                    else:
                        yield "[Erreur: modèle Gemini indisponible]"
                else:
                    yield f"[Erreur API Gemini: {e.response.status_code}]"
            except Exception as e:
                exc_type = type(e).__name__
                logger.error(f"Gemini Stream Fatal: {exc_type}: {e}")
                yield "[Erreur de connexion Gemini — veuillez réessayer ou utiliser le Mode Expert]"

_gemini_client = None

def get_gemini_client():
    global _gemini_client
    if not _gemini_client:
        _gemini_client = GeminiClient()
    return _gemini_client
