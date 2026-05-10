"""
llm_client.py — Routeur multi-backend LLM (Local / Mistral / Gemini)
═════════════════════════════════════════════════════════════════════

RÔLE DANS L'ARCHITECTURE
─────────────────────────
Ce module implémente le PATTERN STRATEGY (SOLID — OCP + DIP).

PATTERN STRATEGY expliqué :
───────────────────────────
Au lieu d'avoir un seul gros bloc if/elif pour chaque LLM, on définit une
INTERFACE (LLMBackend) que chaque backend doit respecter. Le code appelant
(chat.py) n'a pas besoin de savoir quel LLM il utilise — il appelle toujours
la même méthode generate() / generate_stream().

Structure :
  LLMBackend (ABC)         ← Interface commune (contrat)
  ├── OllamaLocalBackend   ← Implémentation LOCAL (Ollama sur VPS)
  ├── MistralCloudBackend  ← Implémentation MISTRAL (API Mistral)
  └── GeminiCloudBackend   ← Implémentation GEMINI (API Google)

  LLMRouter                ← Choisit le bon backend selon le mode
  get_llm_client()         ← Point d'entrée public (appelé par chat.py)

CONFORMITÉ RGPD PAR MODE
──────────────────────────
• LOCAL   : données restent sur le VPS Contabo (France) — RGPD strict
            Modèle : qwen2.5:1.5b-instruct via Ollama
• MISTRAL : API française (Mistral La Plateforme), DPA signé
            Modèle : mistral-small-latest
• GEMINI  : API Google, hébergé hors UE
            Réservé aux DONNÉES ANONYMISÉES / démonstration seulement

INTERFACE COMMUNE (OCP = Open/Closed Principle)
────────────────────────────────────────────────
Tous les backends implémentent :
  - generate()        → réponse complète (non-streaming)
  - generate_stream() → tokens en streaming (pour SSE)
  - check_health()    → vérification que le service est accessible

→ Pour ajouter un nouveau LLM (ex: Claude, GPT-4), il suffit de créer
  une nouvelle classe héritant de LLMBackend. AUCUN code existant n'est modifié.
"""

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import AsyncGenerator, Dict, List

import httpx
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from app.config import settings

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# TYPES PARTAGÉS — Dataclasses et Enum
# ═══════════════════════════════════════════════════════════════════════

class LLMMode(str, Enum):
    """
    Modes LLM disponibles dans l'application.
    Doit rester synchronisé avec LLM_MODES dans RagTerminal.jsx (frontend).
    """
    LOCAL = "local"       # Ollama sur VPS, RGPD strict
    MISTRAL = "mistral"   # API Mistral (France), DPA signé
    GEMINI = "gemini"     # API Google, hors UE, démo seulement


@dataclass
class LLMResponse:
    """
    Réponse structurée retournée par tous les backends LLM.

    POURQUOI UN DATACLASS ?
    ───────────────────────
    Toutes les propriétés garanties peu importe le backend utilisé.
    → Le code appelant n'a jamais à gérer des formats différents.
    """
    content: str                   # Texte généré par le LLM
    finish_reason: str             # Raison de fin ('stop', 'length', 'error')
    usage: Dict[str, int]          # {prompt_tokens, completion_tokens, total_tokens}
    model: str                     # Nom du modèle utilisé
    tool_calls: List[Dict] | None = None  # Appels d'outils (tool calling)


@dataclass
class LLMMessage:
    """
    Message dans une conversation avec le LLM.

    Suit le format standardisé OpenAI/Anthropic :
    - role = "user" (médecin) ou "assistant" (LLM) ou "system" (prompt système)
    - content = texte du message
    """
    role: str                             # 'user', 'assistant', 'system', 'tool'
    content: str                          # Texte du message
    tool_calls: List[Dict] | None = None  # Si le LLM appelle un outil
    tool_call_id: str | None = None       # ID de réponse d'outil


# ═══════════════════════════════════════════════════════════════════════
# INTERFACE ABSTRAITE — Principe OCP (Open/Closed Principle)
# ═══════════════════════════════════════════════════════════════════════

class LLMBackend(ABC):
    """
    Interface commune à tous les backends LLM.

    PRINCIPE LISKOV (LSP) :
    ───────────────────────
    Tout backend peut remplacer LLMBackend sans casser le code appelant.
    → chat.py appelle backend.generate() sans savoir si c'est Ollama ou Gemini.

    MÉTHODES OBLIGATOIRES (abstractmethod) :
    ─────────────────────────────────────────
    - _build_client()    : crée le client HTTP pour ce backend
    - generate()         : génère une réponse complète
    - generate_stream()  : génère en streaming (tokens 1 par 1)
    - check_health()     : vérifie que le service est accessible
    """

    name: str = "abstract"
    model_name: str = ""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        # Nombre maximum de tokens de sortie — chaque backend surcharge cette valeur
        # dans son propre __init__ pour utiliser le paramètre de config approprié.
        # Base par défaut = VLLM_MAX_TOKENS (surtout utilisé par OllamaLocalBackend).
        self._max_tokens_default: int = settings.VLLM_MAX_TOKENS

    @abstractmethod
    def _build_client(self) -> httpx.AsyncClient: ...

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = self._build_client()
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    @abstractmethod
    async def generate(
        self,
        messages: List[LLMMessage],
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        tools: List[Dict] | None = None,
        stop: List[str] | None = None,
        num_ctx: int | None = None,
    ) -> LLMResponse: ...

    @abstractmethod
    def generate_stream(
        self,
        messages: List[LLMMessage],
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        num_ctx: int | None = None,
        stop: List[str] | None = None,
    ) -> AsyncGenerator[str, None]: ...

    @abstractmethod
    async def check_health(self) -> bool: ...

    async def list_models(self) -> List[str]:  # défaut vide
        return [self.model_name] if self.model_name else []

    # ── Helpers communs ─────────────────────────────────────────────

    @staticmethod
    def _build_messages(
        messages: List[LLMMessage],
        system_prompt: str | None = None,
    ) -> List[Dict]:
        api_messages: List[Dict] = []
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})
        for msg in messages:
            entry: Dict = {"role": msg.role, "content": msg.content}
            if msg.tool_calls:
                entry["tool_calls"] = msg.tool_calls
            if msg.tool_call_id:
                entry["tool_call_id"] = msg.tool_call_id
            api_messages.append(entry)
        return api_messages

    def _effective_params(
        self,
        max_tokens: int | None,
        temperature: float | None,
        num_ctx: int | None,
    ) -> tuple[int, float, int | None]:
        # Utilise le défaut propre à chaque backend (self._max_tokens_default)
        # plutôt que VLLM_MAX_TOKENS pour tous — évite que Gemini/Mistral soient
        # limités à 1024 tokens alors qu'ils peuvent générer beaucoup plus.
        eff_max = max_tokens or self._max_tokens_default
        eff_temp = temperature if temperature is not None else settings.VLLM_TEMPERATURE
        eff_ctx = num_ctx or getattr(settings, "VLLM_NUM_CTX", None)
        return eff_max, eff_temp, eff_ctx


# ── 1. Backend LOCAL — Ollama natif ─────────────────────────────────


class OllamaLocalBackend(LLMBackend):
    """
    Mode LOCAL — Ollama installé sur le serveur Contabo.

    RGPD : aucune donnée ne quitte le VPS. Idéal pour vraies données patient.
    Modèle par défaut : qwen2.5:3b-instruct (~2.2 GB RAM, ~15-25 tok/s ARM).
    """

    name = "local"

    def __init__(self) -> None:
        super().__init__()
        self.base_url = settings.LOCAL_LLM_BASE_URL.rstrip("/")
        self.model_name = settings.LOCAL_LLM_MODEL_NAME
        self.timeout = settings.VLLM_TIMEOUT
        # LOCAL : utilise VLLM_MAX_TOKENS (hérité de la base — déjà correct)

    @property
    def _native_base_url(self) -> str:
        return self.base_url.replace("/v1", "")

    def _build_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._native_base_url,
            headers={"Content-Type": "application/json"},
            timeout=httpx.Timeout(float(self.timeout), connect=10.0),
        )

    def _build_payload(
        self,
        messages: List[Dict],
        max_tokens: int,
        temperature: float,
        num_ctx: int | None,
        stream: bool,
        tools: List[Dict] | None = None,
        stop: List[str] | None = None,
    ) -> Dict:
        options: Dict = {
            "num_predict": max_tokens,
            "temperature": temperature,
        }
        if num_ctx:
            options["num_ctx"] = num_ctx
        if stop:
            options["stop"] = stop
        payload: Dict = {
            "model": self.model_name,
            "messages": messages,
            "stream": stream,
            "think": False,  # désactive le mode raisonnement (qwen3)
            "options": options,
        }
        if tools:
            payload["tools"] = tools
        return payload

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_not_exception_type(httpx.TimeoutException),
    )
    async def generate(
        self,
        messages: List[LLMMessage],
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        tools: List[Dict] | None = None,
        stop: List[str] | None = None,
        num_ctx: int | None = None,
    ) -> LLMResponse:
        start = time.time()
        eff_max, eff_temp, eff_ctx = self._effective_params(max_tokens, temperature, num_ctx)
        api_messages = self._build_messages(messages, system_prompt)
        payload = self._build_payload(
            api_messages, eff_max, eff_temp, eff_ctx, stream=False, tools=tools, stop=stop,
        )
        try:
            logger.info(f"[LOCAL] → {self.client.base_url}/api/chat | model={self.model_name}")
            response = await self.client.post("/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
            msg = data.get("message", {})
            usage = {
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0),
            }
            elapsed_ms = data.get("total_duration", 0) // 1_000_000
            logger.info(f"[LOCAL] response in {elapsed_ms}ms | tokens={usage}")
            return LLMResponse(
                content=msg.get("content", ""),
                finish_reason="stop" if data.get("done") else "length",
                usage=usage,
                model=data.get("model", self.model_name),
                tool_calls=msg.get("tool_calls") or None,
            )
        except httpx.ConnectError as e:
            logger.warning(f"[LOCAL] connection failed: {e}")
            return LLMResponse(
                content="[Mode Hors-Ligne] Le service Ollama local n'est pas accessible.",
                finish_reason="stop",
                usage={"prompt_tokens": 0, "completion_tokens": 0},
                model="offline-fallback",
            )
        except httpx.HTTPStatusError as e:
            logger.error(f"[LOCAL] API error {e.response.status_code}: {e.response.text}")
            if e.response.status_code == 404:
                return LLMResponse(
                    content=f"[Système] Le modèle '{self.model_name}' n'est pas installé sur Ollama. "
                            f"Lancez : `docker exec rag_ollama ollama pull {self.model_name}`",
                    finish_reason="stop",
                    usage={"prompt_tokens": 0, "completion_tokens": 0},
                    model="system-initializing",
                )
            raise

    async def generate_stream(
        self,
        messages: List[LLMMessage],
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        num_ctx: int | None = None,
        stop: List[str] | None = None,
    ) -> AsyncGenerator[str, None]:
        eff_max, eff_temp, eff_ctx = self._effective_params(max_tokens, temperature, num_ctx)
        api_messages = self._build_messages(messages, system_prompt)
        payload = self._build_payload(
            api_messages, eff_max, eff_temp, eff_ctx, stream=True, stop=stop,
        )
        timeout = httpx.Timeout(float(self.timeout), connect=10.0)
        logger.info(f"[LOCAL] stream → /api/chat | model={self.model_name}")
        async with self.client.stream("POST", "/api/chat", json=payload, timeout=timeout) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                content = data.get("message", {}).get("content", "")
                if content:
                    yield content
                if data.get("done"):
                    break

    async def check_health(self) -> bool:
        try:
            response = await self.client.get("/api/tags")
            return response.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> List[str]:
        try:
            response = await self.client.get("/api/tags")
            response.raise_for_status()
            data = response.json()
            return [m["name"] for m in data.get("models", [])]
        except Exception as e:
            logger.error(f"[LOCAL] list_models error: {e}")
            return []


#  2. Backend MISTRAL — Mistral La Plateforme 


class MistralCloudBackend(LLMBackend):
    """
    Mode MISTRAL — API Mistral La Plateforme (France, OpenAI-compatible).

    RGPD : DPA signable gratuitement, hébergement 100% France, ISO 27001/SOC 2.
    Conforme pour vraies données patient (loi belge + RGPD Art. 28).
    Coût : ~0,20 € / million tokens input pour mistral-small-latest.
    """

    name = "mistral"

    def __init__(self) -> None:
        super().__init__()
        self.base_url = settings.MISTRAL_BASE_URL.rstrip("/")
        self.model_name = settings.MISTRAL_MODEL_NAME
        self.api_key = settings.MISTRAL_API_KEY
        self.timeout = settings.MISTRAL_TIMEOUT
        self._max_tokens_default = settings.MISTRAL_MAX_TOKENS

    def _build_client(self) -> httpx.AsyncClient:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=httpx.Timeout(float(self.timeout), connect=10.0),
        )

    def _build_payload(
        self,
        messages: List[Dict],
        max_tokens: int,
        temperature: float,
        stream: bool,
        tools: List[Dict] | None = None,
        stop: List[str] | None = None,
    ) -> Dict:
        payload: Dict = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if stop:
            payload["stop"] = stop
        return payload

    def _check_configured(self) -> LLMResponse | None:
        if not self.api_key:
            return LLMResponse(
                content="[Mode Mistral non configuré] La clé MISTRAL_API_KEY est manquante. "
                        "Crée un compte sur https://console.mistral.ai et ajoute la clé dans .env",
                finish_reason="stop",
                usage={"prompt_tokens": 0, "completion_tokens": 0},
                model="mistral-not-configured",
            )
        return None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_not_exception_type(httpx.TimeoutException),
    )
    async def generate(
        self,
        messages: List[LLMMessage],
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        tools: List[Dict] | None = None,
        stop: List[str] | None = None,
        num_ctx: int | None = None,  # ignoré (Mistral gère son contexte)
    ) -> LLMResponse:
        guard = self._check_configured()
        if guard:
            return guard
        start = time.time()
        eff_max, eff_temp, _ = self._effective_params(max_tokens, temperature, num_ctx)
        api_messages = self._build_messages(messages, system_prompt)
        payload = self._build_payload(api_messages, eff_max, eff_temp, stream=False, tools=tools, stop=stop)
        try:
            logger.info(f"[MISTRAL] → {self.base_url}/chat/completions | model={self.model_name}")
            response = await self.client.post("/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()
            choice = data["choices"][0]
            message = choice["message"]
            elapsed_ms = int((time.time() - start) * 1000)
            usage = data.get("usage", {})
            logger.info(f"[MISTRAL] response in {elapsed_ms}ms | tokens={usage}")
            return LLMResponse(
                content=message.get("content", ""),
                finish_reason=choice.get("finish_reason", "stop"),
                usage={
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                },
                model=data.get("model", self.model_name),
                tool_calls=message.get("tool_calls") or None,
            )
        except httpx.HTTPStatusError as e:
            logger.error(f"[MISTRAL] API error {e.response.status_code}: {e.response.text}")
            return LLMResponse(
                content=f"[Mistral] Erreur API ({e.response.status_code}). Vérifiez votre clé et votre quota.",
                finish_reason="stop",
                usage={"prompt_tokens": 0, "completion_tokens": 0},
                model="mistral-error",
            )

    async def generate_stream(
        self,
        messages: List[LLMMessage],
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        num_ctx: int | None = None,
        stop: List[str] | None = None,
    ) -> AsyncGenerator[str, None]:
        guard = self._check_configured()
        if guard:
            yield guard.content
            return
        eff_max, eff_temp, _ = self._effective_params(max_tokens, temperature, num_ctx)
        api_messages = self._build_messages(messages, system_prompt)
        payload = self._build_payload(api_messages, eff_max, eff_temp, stream=True, stop=stop)
        timeout = httpx.Timeout(float(self.timeout), connect=10.0)
        logger.info(f"[MISTRAL] stream → /chat/completions | model={self.model_name}")
        async with self.client.stream("POST", "/chat/completions", json=payload, timeout=timeout) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                    delta = data["choices"][0].get("delta", {})
                    if "content" in delta and delta["content"]:
                        yield delta["content"]
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

    async def check_health(self) -> bool:
        if not self.api_key:
            return False
        try:
            response = await self.client.get("/models")
            return response.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> List[str]:
        if not self.api_key:
            return []
        try:
            response = await self.client.get("/models")
            response.raise_for_status()
            data = response.json()
            return [m["id"] for m in data.get("data", [])]
        except Exception as e:
            logger.error(f"[MISTRAL] list_models error: {e}")
            return []


# ── 3. Backend GEMINI — Google AI (OpenAI-compatible) ───────────────


class GeminiCloudBackend(LLMBackend):
    """
    Mode GEMINI — Google Gemini API (OpenAI-compatible endpoint).

    ⚠️ NON conforme RGPD pour vraies données patient (USA, pas de DPA gratuit).
    Réservé à la démo / aux données anonymisées / fictives.
    Très rapide (~100-200 tok/s) et qualité élevée.
    """

    name = "gemini"

    def __init__(self) -> None:
        super().__init__()
        self.base_url = settings.GEMINI_BASE_URL.rstrip("/")
        self.model_name = settings.GEMINI_MODEL_NAME
        self.api_key = settings.GEMINI_API_KEY
        self.timeout = settings.GEMINI_TIMEOUT
        self._max_tokens_default = settings.GEMINI_MAX_TOKENS

    def _build_client(self) -> httpx.AsyncClient:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=httpx.Timeout(float(self.timeout), connect=10.0),
        )

    def _build_payload(
        self,
        messages: List[Dict],
        max_tokens: int,
        temperature: float,
        stream: bool,
        stop: List[str] | None = None,
    ) -> Dict:
        payload: Dict = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream,
        }
        if stop:
            payload["stop"] = stop
        return payload

    def _check_configured(self) -> LLMResponse | None:
        if not self.api_key:
            return LLMResponse(
                content="[Mode Gemini non configuré] La clé GEMINI_API_KEY est manquante. "
                        "Récupère une clé sur https://aistudio.google.com/apikey",
                finish_reason="stop",
                usage={"prompt_tokens": 0, "completion_tokens": 0},
                model="gemini-not-configured",
            )
        return None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_not_exception_type(httpx.TimeoutException),
    )
    async def generate(
        self,
        messages: List[LLMMessage],
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        tools: List[Dict] | None = None,
        stop: List[str] | None = None,
        num_ctx: int | None = None,
    ) -> LLMResponse:
        guard = self._check_configured()
        if guard:
            return guard
        start = time.time()
        eff_max, eff_temp, _ = self._effective_params(max_tokens, temperature, num_ctx)
        api_messages = self._build_messages(messages, system_prompt)
        payload = self._build_payload(api_messages, eff_max, eff_temp, stream=False, stop=stop)
        try:
            logger.info(f"[GEMINI] → {self.base_url}/chat/completions | model={self.model_name}")
            response = await self.client.post("/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()
            choice = data["choices"][0]
            message = choice["message"]
            usage = data.get("usage", {})
            elapsed_ms = int((time.time() - start) * 1000)
            logger.info(f"[GEMINI] response in {elapsed_ms}ms | tokens={usage}")
            return LLMResponse(
                content=message.get("content", ""),
                finish_reason=choice.get("finish_reason", "stop"),
                usage={
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                },
                model=data.get("model", self.model_name),
            )
        except httpx.HTTPStatusError as e:
            logger.error(f"[GEMINI] API error {e.response.status_code}: {e.response.text}")
            return LLMResponse(
                content=f"[Gemini] Erreur API ({e.response.status_code}). Vérifiez votre clé.",
                finish_reason="stop",
                usage={"prompt_tokens": 0, "completion_tokens": 0},
                model="gemini-error",
            )

    async def generate_stream(
        self,
        messages: List[LLMMessage],
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        num_ctx: int | None = None,
        stop: List[str] | None = None,
    ) -> AsyncGenerator[str, None]:
        guard = self._check_configured()
        if guard:
            yield guard.content
            return
        eff_max, eff_temp, _ = self._effective_params(max_tokens, temperature, num_ctx)
        api_messages = self._build_messages(messages, system_prompt)
        payload = self._build_payload(api_messages, eff_max, eff_temp, stream=True, stop=stop)
        timeout = httpx.Timeout(float(self.timeout), connect=10.0)
        logger.info(f"[GEMINI] stream → /chat/completions | model={self.model_name}")
        async with self.client.stream("POST", "/chat/completions", json=payload, timeout=timeout) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                    delta = data["choices"][0].get("delta", {})
                    if "content" in delta and delta["content"]:
                        yield delta["content"]
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

    async def check_health(self) -> bool:
        if not self.api_key:
            return False
        try:
            response = await self.client.get("/models")
            return response.status_code == 200
        except Exception:
            return False


#  Router 


class LLMRouter:
    """
    Router multi-backend. Singleton.

    Garde une instance de chaque backend (lazy init) et expose une API
    par défaut compatible avec l'ancien `LLMClient` pour ne pas casser
    le code appelant existant.
    """

    def __init__(self) -> None:
        self._backends: dict[LLMMode, LLMBackend] = {}

    def get_backend(self, mode: LLMMode | str | None = None) -> LLMBackend:
        """Retourne le backend correspondant au mode demandé."""
        resolved = self._resolve_mode(mode)
        if resolved not in self._backends:
            self._backends[resolved] = self._build_backend(resolved)
        return self._backends[resolved]

    @staticmethod
    def _resolve_mode(mode: LLMMode | str | None) -> LLMMode:
        if mode is None:
            mode = settings.DEFAULT_LLM_MODE
        if isinstance(mode, LLMMode):
            return mode
        try:
            return LLMMode(mode.lower())
        except (ValueError, AttributeError):
            logger.warning(f"Mode LLM inconnu '{mode}', fallback sur LOCAL")
            return LLMMode.LOCAL

    @staticmethod
    def _build_backend(mode: LLMMode) -> LLMBackend:
        if mode == LLMMode.LOCAL:
            return OllamaLocalBackend()
        if mode == LLMMode.MISTRAL:
            return MistralCloudBackend()
        if mode == LLMMode.GEMINI:
            return GeminiCloudBackend()
        raise ValueError(f"Mode LLM non supporté : {mode}")

    async def close_all(self) -> None:
        for backend in self._backends.values():
            await backend.close()
        self._backends.clear()

    #  Compat ancien LLMClient 

    async def generate(self, *args, **kwargs) -> LLMResponse:
        return await self.get_backend().generate(*args, **kwargs)

    def generate_stream(self, *args, **kwargs):
        return self.get_backend().generate_stream(*args, **kwargs)

    async def check_health(self) -> bool:
        return await self.get_backend().check_health()

    async def list_models(self) -> List[str]:
        return await self.get_backend().list_models()

    @property
    def model_name(self) -> str:
        return self.get_backend().model_name


#  Singleton + helpers publics 


_llm_router: LLMRouter | None = None


def get_llm_router() -> LLMRouter:
    """Retourne l'instance singleton du router."""
    global _llm_router
    if _llm_router is None:
        _llm_router = LLMRouter()
    return _llm_router


def get_llm_client(mode: LLMMode | str | None = None) -> LLMBackend:
    """
    Retourne un backend LLM.

    - `get_llm_client()`             → backend du mode par défaut (settings.DEFAULT_LLM_MODE)
    - `get_llm_client("mistral")`    → backend Mistral
    - `get_llm_client(LLMMode.LOCAL)` → backend Ollama local

    Conserve la signature historique pour rester compatible avec l'ancien
    code (chat.py, dashboard.py, main.py, etc.).
    """
    return get_llm_router().get_backend(mode)


def get_available_modes() -> List[Dict[str, str | bool]]:
    """
    Retourne la liste des 3 modes avec leur statut de configuration.
    Utilisé par le frontend pour afficher le toggle.
    """
    return [
        {
            "id": LLMMode.LOCAL.value,
            "label": "Local",
            "model": settings.LOCAL_LLM_MODEL_NAME,
            "configured": True,  # toujours dispo (Ollama Contabo)
            "rgpd": "strict",
            "description": "Données restent sur le VPS — vraies données patient autorisées.",
        },
        {
            "id": LLMMode.MISTRAL.value,
            "label": "Mistral (UE)",
            "model": settings.MISTRAL_MODEL_NAME,
            "configured": bool(settings.MISTRAL_API_KEY),
            "rgpd": "dpa",
            "description": "Mistral La Plateforme (France) — DPA RGPD signé. Vraies données patient autorisées.",
        },
        {
            "id": LLMMode.GEMINI.value,
            "label": "Gemini (Démo)",
            "model": settings.GEMINI_MODEL_NAME,
            "configured": bool(settings.GEMINI_API_KEY),
            "rgpd": "anonymized",
            "description": "Google Gemini (USA) — Réservé aux données anonymisées / démo.",
        },
    ]


#  Fonction utilitaire (héritée) 


async def generate_response(
    prompt: str,
    context: str | None = None,
    history: List[Dict] | None = None,
    system_prompt: str | None = None,
    mode: LLMMode | str | None = None,
) -> str:
    """Génère une réponse simple (utilitaire haut niveau)."""
    backend = get_llm_client(mode)
    messages: List[LLMMessage] = []
    if history:
        messages.extend(LLMMessage(role=m["role"], content=m["content"]) for m in history)
    user_content = f"Contexte:\n{context}\n\nQuestion: {prompt}" if context else prompt
    messages.append(LLMMessage(role="user", content=user_content))
    response = await backend.generate(messages=messages, system_prompt=system_prompt)
    return response.content
