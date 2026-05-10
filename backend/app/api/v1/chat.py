"""
chat.py — Endpoints FastAPI pour le chat médical (streaming SSE)
════════════════════════════════════════════════════════════════

RÔLE DANS L'ARCHITECTURE
─────────────────────────
Ce fichier définit les ROUTES HTTP de l'API de chat.
Il reçoit les questions du frontend (RagTerminal.jsx) et retourne
les réponses du LLM en streaming (SSE = Server-Sent Events).

DEUX ENDPOINTS DISPONIBLES
───────────────────────────
• POST /api/v1/chat/send   → réponse non-streaming (JSON classique, fallback)
• POST /api/v1/chat/stream → réponse streaming SSE (utilisé par le frontend)

LE PROTOCOLE SSE (Server-Sent Events)
───────────────────────────────────────
SSE est un protocole HTTP qui permet au serveur d'envoyer des données
au client en continu, sans que le client n'ait à faire plusieurs requêtes.
Chaque message SSE a le format : "data: {json}\n\n"

Séquence d'événements SSE envoyés au frontend :
  1. {sources: [...], done: false}      → sources RAG trouvées
  2. {type: 'citations', data: [...]}   → carte de citations [1], [2]...
  3. {content: 'token...', done: false} → tokens LLM (envoyés 1 par 1)
  4. {content: '', done: true}          → fin du stream

PRINCIPE SRP DANS CE FICHIER
─────────────────────────────
- Ce fichier gère UNIQUEMENT le routing HTTP et l'assemblage des réponses.
- La logique métier (RAG, prompts, streaming LLM) est dans d'autres modules.
- Chaque helper (_resolve_llm_mode, _format_sources, etc.) a une seule responsabilité.
"""
import asyncio
import json
import logging
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import DBSession, OptionalUser
from app.config import settings
from app.core.rag_state import rag_state
from app.models.document import Document
from app.models.patient import Patient
from app.core import rag_engine
from app.core.tool_executor import get_tool_executor
from app.core.llm_client import LLMMessage, LLMMode, get_llm_client
from app.core.query_cache import query_cache
from app.core.rag.prompts import (
    classify_query,
    get_greeting_response, get_offtopic_response,
    _SOAP_TRIGGERS, _SECTION_TRIGGERS, _COHORT_TRIGGERS,
)
from app.utils.naming import patient_label as _format_patient_name

from app.services.chat_service import (
    _SCHEDULE_RE, _SSE_HEADERS, _simple_sse, _stream_llm,
    _extract_source_filter, _save_conversation,
    _llm_extract_schedule_intent, _validate_cohort_table,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# Modes LLM autorisés — dérivés directement de l'enum LLMMode pour rester
# automatiquement synchronisés si on ajoute un nouveau backend un jour.
_VALID_LLM_MODES = {m.value for m in LLMMode}


def _resolve_llm_mode(request_mode: str | None, current_user) -> str:
    """
    Détermine quel backend LLM utiliser pour cette requête.

    PRIORITÉ (du plus fort au plus faible) :
      1. Mode dans la requête HTTP (override session — ex: le médecin choisit "Gemini")
      2. Préférence sauvegardée sur l'utilisateur (en base de données)
      3. Mode par défaut de l'application (config .env → DEFAULT_LLM_MODE = "local")

    Exemple de flux :
      Médecin clique "Mistral" dans l'UI
      → request_mode = "mistral"
      → retourne "mistral" (priorité 1)
    """
    if request_mode and request_mode.lower() in _VALID_LLM_MODES:
        return request_mode.lower()
    if current_user and getattr(current_user, "preferred_llm_mode", None):
        return current_user.preferred_llm_mode
    return settings.DEFAULT_LLM_MODE


class ChatRequest(BaseModel):
    """
    Schéma de la requête de chat envoyée par le frontend.

    Pydantic valide automatiquement les types au moment de la réception HTTP.
    Si un champ obligatoire manque → FastAPI retourne une erreur 422 automatiquement.
    """
    message: str                     # Question du médecin
    patient_id: int | None = None    # ID DB du document patient (solution pro : évite le parsing NLP)
    conversation_id: int | None = None  # Pour continuer une conversation existante
    session_id: str | None = None    # ID de session (stockage conversation)
    channel: str = "web"             # Canal (web | sms | whatsapp)
    use_rag: bool = True             # True = recherche RAG, False = LLM seul
    model_mode: str | None = None    # Legacy : type de prompt RAG (expert, etc.)
    llm_mode: str | None = None      # Backend LLM actif : local | mistral | gemini
    phone_number: str | None = None  # Pour les canaux SMS/WhatsApp


def _get_state():
    """Lecture de l'état RAG — délègue au singleton rag_state."""
    return rag_state.get()


async def _sources_for_patient_id(patient_id: int, chunks: list, db) -> list[str] | None:
    """
    Retourne les fichiers source d'un patient depuis son ID.

    DOUBLE STRATÉGIE (backward-compatible)
    ────────────────────────────────────────
    A) Document.id  (ancienne API — 6 patients uploadés via UI)
       patient_id=8 → documents.id=8 → filename="P00013_NGUYEN_Thanh_Van.pdf"

    B) Patient.id   (nouvelle API post-migration — 171 patients FAISS)
       patient_id=42 → patients.id=42 → source_filename="P00013_NGUYEN_Thanh_Van.pdf"

    Priorité A → B (Document est résolu en premier ; si introuvable, on essaie Patient)

    Avantages :
      - 100% déterministe (pas de NLP fragile)
      - RGPD : l'ID est opaque dans les logs
      - Fonctionne pour noms composés, accents, etc.

    Returns:
        list[str] : noms de fichiers sources du patient
        None      : patient introuvable → mode cohorte (tous patients)
    """
    def _match_source(c_src: str, target: str) -> bool:
        """
        Correspondance souple entre un source FAISS et un nom de fichier cible.
        Gère le mismatch d'extension (.pdf ↔ .txt) et les préfixes timestamp.
        """
        import os
        t_stem = os.path.splitext(target)[0]   # "P00013_NGUYEN" (sans ext)
        c_stem = os.path.splitext(c_src)[0]
        return (
            c_src  == target            # exact
            or c_stem == t_stem         # même stem, ext différente (pdf↔txt)
            or c_src.endswith(f"_{target}")    # préfixe timestamp + exact
            or c_stem.endswith(f"_{t_stem}")   # préfixe timestamp + stem
        )

    # ── Chemin A : Document.id (legacy) ──────────────────────────────
    result = await db.execute(select(Document).where(Document.id == patient_id))
    doc = result.scalar_one_or_none()
    if doc:
        filename = doc.filename
        matches = list({c["source"] for c in chunks if _match_source(c["source"], filename)})
        logger.info(f"[chat] patient_id={patient_id} (doc) → {len(matches)} source(s): {matches}")
        return matches or None

    # ── Chemin B : Patient.id (post-migration) ───────────────────────
    try:
        r2 = await db.execute(select(Patient).where(Patient.id == patient_id))
        pat = r2.scalar_one_or_none()
        if pat:
            src = pat.source_filename
            matches = list({c["source"] for c in chunks if _match_source(c["source"], src)})
            logger.info(f"[chat] patient_id={patient_id} (patient) → {len(matches)} source(s): {matches}")
            return matches or None
    except Exception as exc:
        logger.debug(f"[chat] Patient lookup failed (table peut être absente): {exc}")

    logger.warning(f"[chat] patient_id={patient_id} → aucun document ni patient trouvé en DB")
    return None


# ── Non-streaming endpoint ──────────────────────────────────────────

@router.post("/send")
async def chat_message(request: ChatRequest, db: DBSession, current_user: OptionalUser):
    """Réponse non-streaming (fallback)."""
    intent = classify_query(request.message)

    if intent == "greeting":
        return _quick_response(get_greeting_response(request.message))

    if intent == "general" and not _SCHEDULE_RE.search(request.message):
        return _quick_response(get_offtopic_response(request.message))

    index, chunks = _get_state()
    if index is None or index.ntotal == 0:
        raise HTTPException(400, "Aucun document indexé.")

    # Résolution du filtre patient (même logique que /stream)
    source_filter = None
    if request.patient_id:
        source_filter = await _sources_for_patient_id(request.patient_id, chunks, db)
    elif "(Dossier" in request.message:
        source_filter = _extract_source_filter(request.message, chunks)

    prompt, hits, _ = rag_engine.build_rag_prompt(
        query=request.message, index=index, chunks_mapping=chunks,
        source_filter=source_filter,
    )

    llm_mode = _resolve_llm_mode(request.llm_mode, current_user)
    resp = await get_llm_client(llm_mode).generate(
        messages=[LLMMessage(role="user", content=prompt)],
    )

    sources = [
        {
            "document_title": h["source"],
            "chunk_content": h["text"][:200],
            "similarity_score": round(h["score"], 3),
            "page_number": None,
            "document_id": 0,
        }
        for h in hits[:5]
    ]
    return {
        "message_id": 0, "conversation_id": 0, "session_id": "",
        "response": resp.content, "sources": sources, "tools_used": [],
        "confidence_score": 0.8, "processing_time_ms": 0,
        "token_count_input": 0, "token_count_output": 0,
    }


# ── Streaming endpoint ─────────────────────────────────────────────

@router.post("/stream")
async def chat_stream(request: ChatRequest, db: DBSession, current_user: OptionalUser):
    """Streaming SSE — format compatible avec le frontend RagTerminal.jsx."""
    llm_mode = _resolve_llm_mode(request.llm_mode, current_user)
    logger.info(f"[chat] llm_mode={llm_mode} user={getattr(current_user, 'id', None)}")

    intent = classify_query(request.message)

    # ── Résolution du filtre patient (voir _sources_for_patient_id) ───────
    # NOTE ARCHITECTURALE : deux stratégies selon le contexte
    #
    # Stratégie A — patient_id (solution pro) :
    #   Le frontend envoie l'ID DB du document → lookup direct, 100% fiable.
    #   Utilisé quand le médecin a sélectionné un patient PDF dans l'UI.
    #
    # Stratégie B — extraction textuelle (fallback) :
    #   Parsing NLP de "(Dossier: ...)" dans le message.
    #   Utilisé pour : patients notes-only (pas d'ID DB), requêtes cohorte,
    #   appels API externes sans patient_id.
    #
    # Priorité : A > B (patient_id est toujours plus fiable)

    if intent == "greeting":
        return StreamingResponse(
            _simple_sse(get_greeting_response(request.message)),
            media_type="text/event-stream", headers=_SSE_HEADERS,
        )

    if intent == "general" and not _SCHEDULE_RE.search(request.message):
        return StreamingResponse(
            _simple_sse(get_offtopic_response(request.message)),
            media_type="text/event-stream", headers=_SSE_HEADERS,
        )

    # ── Planning médecin (tool) ─────────────────────────────────────
    if _SCHEDULE_RE.search(request.message):
        answer = await _handle_schedule(request.message, llm_mode)
        if answer:
            return StreamingResponse(
                _simple_sse(answer),
                media_type="text/event-stream", headers=_SSE_HEADERS,
            )

    # ── RAG pipeline ────────────────────────────────────────────────
    index, chunks = _get_state()
    if index is None or index.ntotal == 0:
        raise HTTPException(400, "Aucun document indexé.")

    # Stratégie A : patient_id fourni par le frontend (recommandé)
    if request.patient_id:
        source_filter = await _sources_for_patient_id(request.patient_id, chunks, db)
    else:
        # Stratégie B : fallback NLP — pour notes-only, cohorte, appels externes
        source_filter = _extract_source_filter(request.message, chunks)
        if source_filter:
            logger.info(f"[chat] source_filter (NLP) : {source_filter} ({len(source_filter)} fichier(s))")

    _sf_key = "|".join(sorted(source_filter)) if source_filter else ""
    cache_key = query_cache.make_key(request.message, f"{llm_mode}|{_sf_key}")
    cached = query_cache.get(cache_key)

    if cached:
        return StreamingResponse(
            _cached_sse(*cached),
            media_type="text/event-stream", headers=_SSE_HEADERS,
        )

    ctx_chars, local_max_tokens, top_k = _compute_context_params(
        request.message, source_filter, llm_mode, chunks,
    )

    # local_mode=True UNIQUEMENT pour le LLM local (qwen2.5 petit modèle).
    # Mistral et Gemini utilisent le prompt riche avec toutes les instructions SOAP,
    # les numéros de citation [1][2]..., les balises de contradiction ⚠️, etc.
    _use_local_prompt = (llm_mode == "local")

    prompt, hits, citation_map = rag_engine.build_rag_prompt(
        query=request.message, index=index, chunks_mapping=chunks,
        source_filter=source_filter, max_context_chars=ctx_chars,
        k=top_k, local_mode=_use_local_prompt,
    )

    sources_fmt = _format_sources(hits)

    # Détection cohort local
    cohort_known, real_prompt = _extract_cohort_meta(prompt)

    async def sse_gen():
        yield f"data: {json.dumps({'sources': sources_fmt, 'done': False, 'llm_mode': llm_mode})}\n\n"
        if citation_map:
            yield f"data: {json.dumps({'type': 'citations', 'data': citation_map})}\n\n"

        full = ""
        try:
            if cohort_known:
                async for token in _stream_llm(real_prompt, "expert", local_max_tokens, llm_mode=llm_mode):
                    full += token
                full = _validate_cohort_table(full, cohort_known, hits)
                yield f"data: {json.dumps({'content': full, 'done': False})}\n\n"
            else:
                async for token in _stream_llm(prompt, "expert", local_max_tokens, llm_mode=llm_mode):
                    full += token
                    yield f"data: {json.dumps({'content': token, 'done': False})}\n\n"
        except Exception as exc:
            logger.error(f"[sse_gen] LLM streaming error: {exc}")
            yield f"data: {json.dumps({'content': '⚠️ Erreur lors de la génération. Réessayez.', 'done': False})}\n\n"

        yield f"data: {json.dumps({'content': '', 'done': True})}\n\n"

        if full:
            query_cache.set(cache_key, (sources_fmt, full, citation_map))
            # asyncio.create_task() est non-bloquant : la sauvegarde se fait
            # après que la réponse est déjà envoyée au frontend.
            # Le callback log les erreurs silencieuses (connexion DB perdue, etc.)
            task = asyncio.create_task(_save_conversation(
                request.session_id, request.message, full,
                current_user.id if current_user else None,
            ))
            task.add_done_callback(
                lambda t: logger.error(f"[chat] _save_conversation failed: {t.exception()}")
                if not t.cancelled() and t.exception() else None
            )

    return StreamingResponse(
        sse_gen(), media_type="text/event-stream", headers=_SSE_HEADERS,
    )


# ── Helpers (DRY) ──────────────────────────────────────────────────

def _quick_response(text: str) -> dict:
    """Réponse rapide sans RAG."""
    return {
        "message_id": 0, "conversation_id": 0, "session_id": "",
        "response": text, "sources": [], "tools_used": [],
        "confidence_score": 1.0, "processing_time_ms": 0,
        "token_count_input": 0, "token_count_output": 0,
    }


def _format_sources(hits: list) -> list:
    """Formate les hits RAG pour le frontend."""
    return [
        {
            "document_title": _format_patient_name(h["source"]),
            "patient": _format_patient_name(h["source"]),
            "chunk_content": h["text"][:300],
            "similarity_score": round(h["score"], 3),
            "score_pct": f"{min(99, round(h['score'] * 100))}%",
            "rank": i + 1,
            "source": h["source"],
            "page_number": h.get("page_number", 1),
            "document_id": 0,
        }
        for i, h in enumerate(hits[:10])
    ]


# ── Paramètres de contexte par LLM et type de requête ────────────────
# POURQUOI CES VALEURS DIFFÉRENTES ?
# ─────────────────────────────────────
# Chaque LLM a une fenêtre de contexte différente :
#   - Local (qwen2.5:1.5b) : ~32K tokens max, mais LENT sur CPU → on limite volontairement
#   - Mistral (128K tokens) : peut gérer beaucoup plus de contexte
#   - Gemini (1M tokens!)   : fenêtre quasi-illimitée → contexte maximal
#
# Et chaque type de requête a des besoins différents :
#   - "identity"  : identité patient → beaucoup de données démographiques
#   - "soap"      : synthèse complète → TOUS les extraits du dossier
#   - "cohort"    : comparaison multi-patient → 1 chunk par patient × beaucoup de patients
#   - "default"   : question simple → moins de contexte suffit

# ctx_chars = nombre max de caractères dans le bloc contexte envoyé au LLM
_CTX_CAPS: dict[str, dict[str, int]] = {
    "local":   {"default": 800,   "identity": 2500,  "soap": 3500,  "cohort": 4000},
    "mistral": {"default": 20000, "identity": 60000, "soap": 80000, "cohort": 100000},
    "gemini":  {"default": 20000, "identity": 60000, "soap": 80000, "cohort": 100000},
}

# max_tokens = nombre max de tokens que le LLM peut générer en réponse
#
# LOCAL   (qwen2.5:7b — ~10 tok/s ARM)              : limité volontairement pour la vitesse
# MISTRAL (mistral-small-latest — 32K output max)    : parité complète avec Gemini
# GEMINI  (gemini-2.5-flash — 65K output max)        : parité complète avec Mistral
#
# Mistral et Gemini sont identiques : même qualité de réponse, même exhaustivité.
_TOK_CAPS: dict[str, dict[str, int]] = {
    "local":   {"default": 600,   "identity": 900,   "soap": 2000,  "cohort": 1500},
    "mistral": {"default": 4000,  "identity": 8000,  "soap": 16000, "cohort": 20000},
    "gemini":  {"default": 4000,  "identity": 8000,  "soap": 16000, "cohort": 20000},
}

# top_k = nombre de chunks RAG récupérés (plus de chunks = meilleur rappel)
_TOPK_CAPS: dict[str, dict[str, int]] = {
    "local":   {"default": 10, "identity": 15, "soap": 25, "cohort": 20},
    "mistral": {"default": 30, "identity": 50, "soap": 60, "cohort": 60},
    "gemini":  {"default": 30, "identity": 50, "soap": 70, "cohort": 80},
}


def _compute_context_params(
    message: str,
    source_filter,
    llm_mode: str = "local",
    chunks_mapping: list | None = None,
) -> tuple[int, int, int]:
    """
    Calcule les 3 paramètres RAG de façon DYNAMIQUE.

    Retourne : (ctx_chars, max_tokens, top_k)

    OPTIMISATION DYNAMIQUE DES max_tokens
    ──────────────────────────────────────
    Pour les modèles cloud (Gemini, Mistral), on adapte max_tokens à la
    taille RÉELLE du dossier patient au lieu d'un plafond fixe trop haut.

    Exemple :
      Robert DEPREZ a 26 chunks × ~200 tokens = ~5 200 tokens de données.
      Réponse attendue ≈ contexte × 0.5 = ~2 600 tokens.
      On fixe max_tokens = 3 000 au lieu de 16 000.

      → Gemini 2.5-flash alloue moins de "thinking budget" → 8s au lieu de 20s
      → Mistral génère exactement ce dont il a besoin, pas plus

    Pour les cohortes (pas de source_filter), on garde le plafond statique car
    le nombre de patients est imprévisible.
    """
    is_soap    = bool(_SOAP_TRIGGERS.search(message)) and not bool(_SECTION_TRIGGERS.search(message))
    is_cohort  = not bool(source_filter) and bool(_COHORT_TRIGGERS.search(message))
    is_identity = bool(re.search(
        r'identit[eé]|qui\s+est|pr[eé]nom|nom\s+complet|date\s+de\s+naissance|identity|full\s+name',
        message, re.IGNORECASE,
    ))

    mode  = llm_mode if llm_mode in _CTX_CAPS else "local"
    caps  = _CTX_CAPS[mode]
    tok   = _TOK_CAPS[mode]
    topk  = _TOPK_CAPS[mode]

    query_type = (
        "cohort"   if is_cohort   else
        "soap"     if is_soap     else
        "identity" if is_identity else
        "default"
    )

    ctx_chars  = caps[query_type]
    max_tokens = tok[query_type]
    top_k      = topk[query_type]

    # ── Ajustement dynamique de max_tokens (patient unique, modèle cloud) ──
    # Pour Gemini et Mistral, on estime la taille réelle du dossier et on
    # calibre max_tokens en conséquence. Inutile pour local (déjà limité)
    # et pour les cohortes (nb de patients inconnu).
    if mode in ("gemini", "mistral") and source_filter and chunks_mapping and not is_cohort:
        # Compter les chunks réels du patient
        sources = set(source_filter) if isinstance(source_filter, list) else {source_filter}
        import os
        patient_chunks = [
            c for c in chunks_mapping
            if os.path.splitext(c.get("source", ""))[0] in
               {os.path.splitext(s)[0] for s in sources}
        ]
        n_chunks = len(patient_chunks)
        if n_chunks > 0:
            # ~200 tokens par chunk en moyenne ; réponse ≈ 50 % des données
            estimated_response = max(800, int(n_chunks * 200 * 0.5))
            # Plafonner : ne pas dépasser le cap statique, ni descendre sous un minimum
            min_tok = {"soap": 2000, "identity": 1000, "default": 800}
            dynamic_max = max(min_tok.get(query_type, 800), estimated_response)
            max_tokens  = min(max_tokens, dynamic_max)   # on prend le plus petit
            logger.info(
                f"[ctx] dynamic max_tokens: {n_chunks} chunks → "
                f"estimated {estimated_response} → capped at {max_tokens}"
            )

    logger.info(f"[ctx] mode={mode} type={query_type} ctx={ctx_chars} max_tok={max_tokens} top_k={top_k}")
    return ctx_chars, max_tokens, top_k


def _extract_cohort_meta(prompt: str) -> tuple[list[str], str]:
    """Extrait les labels cohort du prompt si présents."""
    if prompt.startswith("__COHORT_LOCAL__|"):
        meta, _, real_prompt = prompt.partition("\n")
        parts = meta.split("|")
        known = [p for p in parts[1:] if p and p != "__END__"]
        return known, real_prompt
    return [], prompt


async def _cached_sse(sources, answer, cmap):
    """SSE generator pour une réponse en cache."""
    yield f"data: {json.dumps({'sources': sources, 'done': False})}\n\n"
    if cmap:
        yield f"data: {json.dumps({'type': 'citations', 'data': cmap})}\n\n"
    for i in range(0, len(answer), 50):
        yield f"data: {json.dumps({'content': answer[i:i + 50], 'done': False})}\n\n"
    yield f"data: {json.dumps({'content': '', 'done': True})}\n\n"


async def _handle_schedule(message: str, llm_mode: str | None = None) -> str | None:
    """Gère les requêtes de planning médecin. Retourne None si échec."""
    jours_order = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    absent_vals = {"absent", "fermé", "ferme", "congé", "conge"}
    try:
        tool = get_tool_executor().registry.get("check_doctor_schedule")
        planning = await tool._fetch_schedule()

        intent_data = await _llm_extract_schedule_intent(
            message, list(planning.keys()), "expert", llm_mode=llm_mode,
        )
        doctor = (intent_data.get("doctor") or "").lower().strip()
        day = (intent_data.get("day") or "").lower().strip()
        qtype = intent_data.get("type", "full_schedule")

        def _norm_key(k: str) -> str:
            """Normalise une clé de planning pour la comparaison (minuscule, sans accents)."""
            import unicodedata
            k = k.lower().strip()
            return ''.join(
                c for c in unicodedata.normalize('NFD', k)
                if unicodedata.category(c) != 'Mn'
            )

        doctor_norm = _norm_key(doctor)
        found = next(
            (k for k in planning
             if doctor_norm and (
                 doctor_norm in _norm_key(k)
                 or _norm_key(k) in doctor_norm
                 or _norm_key(k).startswith(doctor_norm)
             )),
            None,
        )

        if qtype == "who_available" and day:
            dispo = [
                f"**Dr. {k.capitalize()}** : {v[day]}"
                for k, v in planning.items()
                if day in v and v[day].lower() not in absent_vals
            ]
            return (
                f"**Médecins disponibles — {day.capitalize()}** *(Google Sheets)*\n\n"
                + ("\n".join(dispo) if dispo else f"Aucun médecin disponible {day}.")
            )

        if found:
            rows = planning[found]
            if qtype == "absence":
                absent_days = [j for j in jours_order if j in rows and rows[j].lower() in absent_vals]
                return (
                    f"**Jours d'absence — Dr. {found.capitalize()}** *(Google Sheets)*\n\n"
                    + ("\n".join(f"**{j.capitalize()}**" for j in absent_days) or "Aucun jour d'absence.")
                )
            if qtype == "specific_day" and day:
                horaire = rows.get(day, "Information non disponible")
                return f"**Dr. {found.capitalize()} — {day.capitalize()}** *(Google Sheets)*\n\n{horaire}"
            # full_schedule
            lines = [f"**{j.capitalize()}** : {rows[j]}" for j in jours_order if j in rows]
            return f"**Planning complet — Dr. {found.capitalize()}** *(Google Sheets)*\n\n" + "\n".join(lines)

        return (
            "**Médecins dans le planning** *(Google Sheets)*\n\n"
            + "\n".join(f"- Dr. {k.capitalize()}" for k in planning)
            + "\n\nPrécisez un nom pour voir son planning."
        )
    except Exception as e:
        logger.warning(f"[tool] schedule failed: {e}")
        return None
