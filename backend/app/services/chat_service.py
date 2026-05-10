"""
chat_service.py — Services partagés pour le pipeline de chat
═════════════════════════════════════════════════════════════

RÔLE DANS L'ARCHITECTURE
─────────────────────────
Ce module contient les FONCTIONS UTILITAIRES partagées entre les endpoints de chat.
Il applique le principe SRP : chaque fonction a une seule responsabilité claire.

FONCTIONS DISPONIBLES
──────────────────────
• _stream_llm()              → stream les tokens du LLM (Local/Mistral/Gemini)
• _simple_sse()              → génère un stream SSE simple pour greetings/off-topic
• _extract_source_filter()   → détecte le patient mentionné dans le message
• _validate_cohort_table()   → valide/corrige le tableau cohorte généré par le LLM
• _save_conversation()       → persiste la conversation en base de données
• _llm_extract_schedule_intent() → extrait l'intention du planning médecin

PRINCIPE DRY APPLIQUÉ
─────────────────────
Ces fonctions sont appelées par chat.py → les règles partagées ne sont
définies qu'une seule fois ici (ex: _SSE_HEADERS, _SCHEDULE_RE).

DIFFÉRENCE AVEC chat.py
────────────────────────
- chat.py      : routing HTTP, assemblage des réponses (QUOI faire)
- chat_service.py : implémentation des opérations (COMMENT le faire)
"""
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator

from app.core.llm_client import LLMMessage, get_llm_client
from app.core.rag.context_builder import _build_cohort_table_local
from app.utils.naming import patient_label_lower as _label_from_source

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════
# CONSTANTES PARTAGÉES
# ═══════════════════════════════════════════════════════════════════════

# Détecte si le message concerne le planning médecin (Google Sheets).
# Exemples : "horaires de dupont", "Dr. Martin disponible lundi ?"
_SCHEDULE_RE = re.compile(
    r'\b(horaires?|agenda|planning|disponibles?|dispo|absences?|absent'
    r'|congés?|travaille|consulte|libre|reçoit|schedule|available)\b'
    r'|\b(?:Dr\.?\s+|Docteur\s+)[A-Za-zÀ-ÿ]+',
    re.IGNORECASE,
)

# En-têtes HTTP nécessaires pour que le streaming SSE fonctionne correctement.
# - Cache-Control: no-cache → le proxy/navigateur ne doit PAS mettre en cache le stream
# - Connection: keep-alive  → la connexion HTTP reste ouverte pendant tout le stream
# - X-Accel-Buffering: no   → désactive le buffering Nginx (sinon les tokens s'accumulent
#                              et arrivent d'un coup au lieu d'être envoyés 1 par 1)
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

_EXTRACTION_PROMPT = """\
Tu es un assistant qui extrait des informations d'une question sur le planning médical.
Réponds UNIQUEMENT avec un objet JSON valide, sans texte autour.

Question : "{message}"

Médecins connus : {doctors}

Extrais :
- "doctor" : nom de famille du médecin mentionné (null si aucun ou si on demande "qui")
- "day" : jour de la semaine en français minuscule (lundi/mardi/...) ou null si non précisé
- "type" : "specific_day" | "full_schedule" | "absence" | "who_available"

Exemples :
  "horaires de dupont" → {{"doctor":"dupont","day":null,"type":"full_schedule"}}
  "dupont dispo lundi ?" → {{"doctor":"dupont","day":"lundi","type":"specific_day"}}
  "jours d'absence de martin" → {{"doctor":"martin","day":null,"type":"absence"}}
  "who works on monday ?" → {{"doctor":null,"day":"lundi","type":"who_available"}}
"""


# ── LLM streaming ──────────────────────────────────────────────────

async def _stream_llm(
    prompt: str,
    mode: str | None = None,
    max_tokens: int = 600,
    llm_mode: str | None = None,
) -> AsyncGenerator[str, None]:
    """
    Stream LLM via le router multi-backend.

    Args:
      prompt: prompt utilisateur
      mode: paramètre legacy (style RAG : 'expert', etc.) — non utilisé ici
      max_tokens: limite de tokens en sortie
      llm_mode: 'local' | 'mistral' | 'gemini' — None = défaut config
    """
    backend = get_llm_client(llm_mode)
    async for token in backend.generate_stream(
        messages=[LLMMessage(role="user", content=prompt)],
        max_tokens=max_tokens,
    ):
        yield token


# ── SSE helpers ─────────────────────────────────────────────────────

def _simple_sse(text: str):
    """SSE generator pour une réponse texte simple (greeting, off-topic)."""
    async def gen():
        yield f"data: {json.dumps({'sources': [], 'done': False})}\n\n"
        for i in range(0, len(text), 80):
            yield f"data: {json.dumps({'content': text[i:i + 80], 'done': False})}\n\n"
        yield f"data: {json.dumps({'content': '', 'done': True})}\n\n"
    return gen()


# ── Schedule intent extraction ──────────────────────────────────────

async def _llm_extract_schedule_intent(
    message: str,
    doctors: list[str],
    mode: str,
    llm_mode: str | None = None,
) -> dict:
    """
    Extrait l'intention planning via le LLM.

    Robuste aux 2 problèmes courants :
    - Gemini entoure le JSON de backticks markdown (```json ... ```)
    - max_tokens trop bas tronque la réponse → augmenté à 200
    """
    prompt = _EXTRACTION_PROMPT.format(message=message, doctors=", ".join(doctors))
    try:
        backend = get_llm_client(llm_mode)
        resp = await backend.generate(
            messages=[LLMMessage(role="user", content=prompt)],
            max_tokens=200,   # ← était 80, trop bas pour gemini-2.5-flash thinking
        )
        raw = resp.content.strip()

        # Supprimer les balises markdown si présentes (```json ... ```)
        raw = re.sub(r'^```[a-z]*\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        raw = raw.strip()

        # Extraire le premier objet JSON de la réponse
        m = re.search(r'\{.*?\}', raw, re.DOTALL)
        if not m:
            return {}
        return json.loads(m.group(0))
    except Exception as e:
        logger.warning(f"[tool] LLM extraction failed: {e}")
        return {}


# ── Cohort table validation ─────────────────────────────────────────

def _validate_cohort_table(response: str, known_labels: list[str], hits: list) -> str:
    """Valide et corrige la table de cohorte générée par le LLM.

    Stratégie :
    1. Parse les lignes LLM
    2. Tente de matcher chaque ligne à un known_label
    3. Si une ligne est manquante → fallback Python pour ce patient
    4. Si le LLM n'a produit AUCUNE ligne valide → 100% fallback Python
    """
    lines = response.splitlines()
    table_lines = [l.strip() for l in lines if l.strip().startswith("|") or l.strip().startswith("**Total")]

    header_rows = [l for l in table_lines if l.startswith("| Patient")]
    sep_rows    = [l for l in table_lines if l.startswith("|---")]
    data_rows   = [
        l for l in table_lines
        if l.startswith("|") and not l.startswith("|---") and not l.startswith("| Patient")
        and not l.startswith("**Total")
    ]
    total_rows = [l for l in table_lines if l.startswith("**Total")]

    def _norm(n: str) -> str:
        import unicodedata
        n = re.sub(r'\s+', ' ', n.strip().lower())
        return ''.join(
            c for c in unicodedata.normalize('NFD', n)
            if unicodedata.category(c) != 'Mn'
        )

    known_norm = {_norm(lbl): lbl for lbl in known_labels}

    # ── Fallback Python rows (toujours construits, utilisés si LLM incomplet) ──
    python_rows: dict[str, str] = {}
    py_table = _build_cohort_table_local(hits, len(known_labels))
    for row in py_table.splitlines():
        if row.startswith("|") and not row.startswith("|---") and not row.startswith("| Patient"):
            parts = [p.strip() for p in row.split("|")]
            if len(parts) > 1:
                python_rows[_norm(parts[1])] = row

    # ── Matcher les lignes LLM aux labels connus ──
    validated: dict[str, str] = {}
    for row in data_rows:
        parts = [p.strip() for p in row.split("|")]
        if len(parts) < 2:
            continue
        cell = _norm(parts[1])
        if not cell:          # cellule vide ou séparateur
            continue
        for kn, orig in known_norm.items():
            # Correspondance souple : inclusion dans les deux sens OU mots en commun
            kn_words  = set(kn.split())
            cell_words = set(cell.split())
            if (kn in cell or cell in kn
                    or len(kn_words & cell_words) >= max(1, len(kn_words) - 1)):
                validated[_norm(orig)] = row
                break

    # ── Si le LLM n'a produit AUCUNE ligne valide → 100% fallback Python ──
    if not validated and python_rows:
        logger.warning("[cohort] LLM table empty — using 100% Python fallback")
        final_rows = [python_rows.get(_norm(lbl), f"| {lbl} | Non documenté | Non documenté | Non documenté | Non documenté | — |") for lbl in known_labels]
    else:
        # Compléter ligne par ligne : LLM si disponible, sinon Python
        final_rows = []
        for lbl in known_labels:
            nk = _norm(lbl)
            if nk in validated:
                final_rows.append(validated[nk])
            elif nk in python_rows:
                logger.warning(f"[cohort] LLM row missing for '{lbl}' — Python fallback")
                final_rows.append(python_rows[nk])
            # Si ni LLM ni Python n'ont ce patient, on ne l'inclut pas
            # (il n'avait probablement pas le critère cherché)

    if not header_rows:
        header_rows = ["| Patient | Âge / Genre | Pathologie / Motif | Traitement utilisé | Évolution / Résultat | Date |"]
    if not sep_rows:
        sep_rows    = ["|---------|-------------|-------------------|-------------------|---------------------|------|"]

    n = len(final_rows)
    total = total_rows[0] if total_rows else f"**Total : {n} patient(s) identifié(s) sur {len(known_labels)} dossier(s) analysé(s)**"
    return "\n".join(header_rows + sep_rows + final_rows + [total])


# ── Source filter extraction ────────────────────────────────────────

def _extract_source_filter(message: str, chunks_mapping: list) -> list[str] | None:
    """
    Détecte le patient mentionné dans le message et retourne ses fichiers source.

    PROBLÈME RÉSOLU
    ───────────────
    Un patient peut avoir PLUSIEURS PDFs indexés (ex: 2 hospitalisations → 2 PDFs).
    Il faut retourner TOUS ses fichiers, pas seulement le premier trouvé.

    ALGORITHME (5 étapes par ordre de priorité)
    ────────────────────────────────────────────
    0. Cohorte en priorité : si la requête déclenche _COHORT_TRIGGERS → None immédiat
       (un message "liste des diabétiques" ne doit pas filtrer sur un patient)
    1. Pattern explicite  : "(Dossier: Sophie LECOMTE)" → injecté par le frontend
    2. Match exact        : "lecomte" apparaît tel quel dans le message
    3. Match multi-parties: "LECOMTE" + "Sophie" tous les deux dans le message
    4. Match flou         : les mots du label sont tous dans le message

    Retourne :
        list[str] : liste des fichiers du patient trouvé (ex: ['1234_LECOMTE.pdf'])
        None      : aucun patient identifié → mode cohorte
    """
    # 0. Priorité cohorte : si le message est une requête multi-patient,
    #    on ne filtre PAS sur un patient même si un nom apparaît dans la phrase.
    #    Ex: "Véronique GERMAIN est-elle la seule hypertendue ?" → cohorte
    from app.core.rag.prompts import _COHORT_TRIGGERS
    if _COHORT_TRIGGERS.search(message):
        return None
    def _all_sources_for_label(target_label: str) -> list[str]:
        """Retourne tous les fichiers dont le label correspond au patient."""
        seen: set[str] = set()
        result: list[str] = []
        for c in chunks_mapping:
            src = c["source"]
            if src not in seen and _label_from_source(src) == target_label:
                seen.add(src)
                result.append(src)
        return result

    # 1. Pattern explicite (Dossier: ...)
    m = re.search(r'\(Dossier\s*:\s*([^)]+)\)', message, re.IGNORECASE)
    if m:
        label = m.group(1).strip().lower()
        srcs = _all_sources_for_label(label)
        if srcs:
            return srcs

    # 2. Collect unique labels
    known_labels: list[str] = []
    seen_labels: set[str] = set()
    for c in chunks_mapping:
        lbl = _label_from_source(c["source"])
        if lbl not in seen_labels:
            seen_labels.add(lbl)
            known_labels.append(lbl)

    msg_lower = message.lower()

    # Exact match
    for label in known_labels:
        if label in msg_lower:
            return _all_sources_for_label(label)

    # Multi-part match (handles "HENRY Isabelle" → label "isabelle henry")
    for label in known_labels:
        parts = label.split()
        if len(parts) >= 2 and all(p in msg_lower for p in parts):
            return _all_sources_for_label(label)

    # Fuzzy word match
    msg_words = set(re.findall(r'\b[a-zàâéèêëîïôùûüç]{3,}\b', msg_lower))
    for label in known_labels:
        label_parts = set(label.split())
        if len(label_parts) >= 2 and label_parts.issubset(msg_words):
            return _all_sources_for_label(label)

    return None


# ── Conversation persistence ────────────────────────────────────────

async def _save_conversation(
    session_id: str | None,
    user_message: str,
    ai_response: str,
    user_id: int | None,
):
    """Sauvegarde la conversation en DB (fire-and-forget)."""
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.conversation import Conversation, ConversationStatus, ConversationChannel
    from app.models.message import Message, MessageRole
    try:
        async with AsyncSessionLocal() as db:
            conv = None
            if session_id:
                result = await db.execute(
                    select(Conversation).where(Conversation.session_id == session_id)
                )
                conv = result.scalar_one_or_none()

            if not conv:
                conv = Conversation(
                    session_id=session_id or str(uuid.uuid4()),
                    channel=ConversationChannel.WEB,
                    user_id=user_id,
                    status=ConversationStatus.ACTIVE,
                )
                db.add(conv)
                await db.flush()

            now = datetime.now(timezone.utc)
            db.add(Message(conversation_id=conv.id, role=MessageRole.USER, content=user_message, created_at=now))
            db.add(Message(conversation_id=conv.id, role=MessageRole.ASSISTANT, content=ai_response, created_at=now))
            conv.last_message_at = now
            await db.commit()
    except Exception as e:
        logger.warning(f"[save_conversation] {e}")
