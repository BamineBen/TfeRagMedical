"""
llm.py — Client LLM (Gemini + OpenAI-compatible pour Ollama/Mistral).

PROVIDERS SUPPORTÉS :
  gemini  → Google Gemini 2.5 Flash
  openai  → Compatible OpenAI (Ollama local, Mistral, etc.)

LAZY INITIALIZATION : connexion établie au premier appel (_ensure_configured).
"""
import os
import logging
from typing import Generator

from app.config import settings

logger = logging.getLogger(__name__)

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").lower()

# Filtres Gemini désactivés — termes médicaux déclenchent les filtres par défaut
_GEMINI_SAFETY = {
    "HARM_CATEGORY_HARASSMENT":        "BLOCK_NONE",
    "HARM_CATEGORY_HATE_SPEECH":       "BLOCK_NONE",
    "HARM_CATEGORY_SEXUALLY_EXPLICIT": "BLOCK_NONE",
    "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_NONE",
}

_configured    = False
_gemini_model  = None
_openai_client = None


def _ensure_configured() -> None:
    """Initialise le client LLM (lazy singleton)."""
    global _configured, _gemini_model, _openai_client
    if _configured:
        return

    logger.info("[LLM] Provider : %s", LLM_PROVIDER.upper())

    if LLM_PROVIDER == "gemini":
        import google.generativeai as genai
        key = settings.GEMINI_API_KEY or os.getenv("GOOGLE_API_KEY", "")
        if not key:
            raise ValueError("GEMINI_API_KEY manquante dans .env")
        genai.configure(api_key=key)
        _gemini_model = genai.GenerativeModel("gemini-2.5-flash", safety_settings=_GEMINI_SAFETY)

    else:
        # openai-compatible : Ollama, Mistral, etc.
        from openai import OpenAI
        key = os.getenv("OPENAI_API_KEY", "ollama")
        base_url = os.getenv("OPENAI_BASE_URL", settings.VLLM_BASE_URL)
        _openai_client = OpenAI(api_key=key, base_url=base_url)

    _configured = True


def _model_name() -> str:
    """Retourne le nom du modèle selon le provider actif."""
    if LLM_PROVIDER == "gemini":
        return settings.GEMINI_MODEL_NAME
    return settings.VLLM_MODEL_NAME


def _extract_gemini_text(response) -> str:
    """
    Extrait le texte d'une réponse Gemini en gérant les cas d'erreur.
    Les filtres de sécurité peuvent bloquer la réponse même avec BLOCK_NONE.
    """
    try:
        return response.text
    except ValueError:
        # finish_reason != STOP (filtre de sécurité, etc.)
        if response.candidates:
            parts = response.candidates[0].content.parts if response.candidates[0].content else []
            return "".join(p.text for p in parts if hasattr(p, "text")) or \
                   "(Réponse bloquée par le filtre de sécurité. Reformulez votre question.)"
        return "(Réponse indisponible.)"


def generate_answer(prompt: str) -> str:
    """
    Génère une réponse complète (non-streaming).

    Retourne la réponse en texte ou un message d'erreur si le LLM est indisponible.
    """
    _ensure_configured()
    try:
        if LLM_PROVIDER == "gemini":
            return _extract_gemini_text(_gemini_model.generate_content(prompt))
        response = _openai_client.chat.completions.create(
            model=_model_name(),
            messages=[{"role": "user", "content": prompt}],
            stream=False,
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error("[LLM] Erreur generate_answer : %s", e)
        return f"Erreur LLM ({LLM_PROVIDER}) : {e}"


def generate_answer_stream(prompt: str) -> Generator[str, None, None]:
    """
    Génère une réponse en streaming (token par token).

    Générateur Python : chaque `yield` envoie un fragment de texte.
    Utilisé par les endpoints SSE pour afficher la réponse progressivement.
    """
    _ensure_configured()
    try:
        if LLM_PROVIDER == "gemini":
            response = _gemini_model.generate_content(prompt, stream=True)
            try:
                for chunk in response:
                    try:
                        text = chunk.text
                    except (ValueError, AttributeError):
                        # Extraire depuis candidates si .text échoue
                        parts = (chunk.candidates[0].content.parts
                                 if chunk.candidates and chunk.candidates[0].content else [])
                        text = "".join(p.text for p in parts if hasattr(p, "text"))
                    if text:
                        yield text
            except Exception as e:
                msg = str(e)
                yield ("\n\n*(Réponse interrompue par les filtres de sécurité.)*"
                       if "finish_reason" in msg else f"\n\n*(Erreur du flux LLM : {msg})*")
        else:
            response = _openai_client.chat.completions.create(
                model=_model_name(),
                messages=[{"role": "user", "content": prompt}],
                stream=True,
            )
            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
    except Exception as e:
        logger.error("[LLM] Erreur generate_answer_stream : %s", e)
        yield f"Erreur LLM ({LLM_PROVIDER}) : {e}"
