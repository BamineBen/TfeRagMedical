import logging
import re

import numpy as np

from app.core import vector_store
from app.core.bm25_engine import bm25_engine, reciprocal_rank_fusion
from app.core.embeddings import get_embedding_service
from app.core.rag.prompts import is_english

try:
    from app.core.reranker import rerank as _rerank
    _RERANKER_AVAILABLE = True
except Exception:
    _RERANKER_AVAILABLE = False
    _rerank = None

logger = logging.getLogger(__name__)

_TEMPORAL_WEIGHT = 0.15

_META_QUERY_RE = re.compile(
    r'\b(combien|plusieurs|une\s+seule?|nombre\s+de|fois|'
    r'à\s+quelle\s+fr[eé]quence|depuis\s+quand|'
    r'la\s+derni[eè]re\s+fois|combien\s+de\s+fois|'
    r'une\s+seule\s+fois|deux\s+fois|trois\s+fois|'
    r'how\s+many|how\s+often|how\s+much)\b',
    re.IGNORECASE | re.UNICODE,
)

_ACCENT_MAP: dict[int, str] = str.maketrans('éèêëàâùûîïôöç', 'eeeeaauuiiooc')

_MEDICAL_ALIASES: dict[tuple[str, str], str] = {
    ('ligament', 'croise'): 'lca',
    ('accident', 'vasculaire'): 'avc',
    ('thrombose', 'veineus'): 'tvp',
    ('infarctus', 'myocarde'): 'idm',
    ('insuffisance', 'renale'): 'irc',
    ('insuffisance', 'cardiaque'): 'icc',
    ('hypertension', 'arterielle'): 'hta',
}

_EN_TO_MEDICAL: dict[str, list[str]] = {
    'acl': ['lca'], 'tear': ['rupture'], 'cruciate': ['croise', 'lca'],
    'ligament': ['ligament'], 'fracture': ['fracture'],
    'orthopedic': ['orthopedique', 'chirurgie'], 'surgery': ['chirurgie', 'operation'],
    'stroke': ['avc'], 'atrial': ['auriculaire'], 'fibrillation': ['fibrillation'],
    'cardiac': ['cardiaque'], 'heart': ['cardiaque', 'coeur'], 'infarct': ['infarctus', 'idm'],
    'diabetes': ['diabete'], 'diabetic': ['diabete'],
    'hypertension': ['hypertension', 'hta'], 'hypertensive': ['hypertension', 'hta'],
    'obesity': ['obesite', 'obese'], 'obese': ['obese'],
    'renal': ['renale', 'renaux'], 'kidney': ['renale', 'rein'],
    'asthma': ['asthme'], 'pulmonary': ['pulmonaire'], 'embolism': ['embolie'],
    'anticoagulant': ['anticoagulant'], 'antibiotic': ['antibiotique'],
    'chemotherapy': ['chimiotherapie'],
}

_COH_STOPWORDS: frozenset[str] = frozenset({
    'quels', 'quel', 'quelle', 'quelles', 'patients', 'patient',
    'avec', 'pour', 'dans', 'tous', 'liste', 'ayant', 'sont',
    'historique', 'comparaison', 'comparer', 'recherche',
    'which', 'have', 'had', 'that', 'with', 'from', 'into', 'been',
    'were', 'what', 'when', 'where', 'also', 'their', 'show', 'list',
    'give', 'tell', 'find', 'used', 'using', 'result', 'results',
})

_SOAP_SUBQUERIES = [
    "identité état civil date naissance prénom nom adresse",
    "antécédents médicaux personnels familiaux chirurgicaux",
    "allergies intolérances contre-indications",
    "traitements médicaments posologie dosage prescription ordonnance",
    "biologie analyses résultats glycémie créatinine hémoglobine HbA1c troponine NFS ionogramme",
    "examens complémentaires cabinet glycémie capillaire bandelette urinaire biologie rapide",
    "imagerie scanner IRM radiographie échographie spirométrie",
    "ECG électrocardiogramme rythme sinusal repolarisation ondes QRS",
    "constantes vitales tension artérielle poids taille SpO2 fréquence cardiaque température",
    "consultations hospitalisations compte-rendu évolution clinique",
    "vaccinations immunisations",
]


def _make_chunk(raw: dict, score: float = 1.0) -> dict:
    return {
        "text":        raw["text"],
        "parent_text": raw.get("parent_text", raw["text"]),
        "category":    raw.get("category", "AUTRE"),
        "score":       score,
        "source":      raw["source"],
        "date_score":  raw.get("date_score", 0.0),
        "page_number": raw.get("page_number", 1),
        "note_id":     raw.get("note_id"),
    }


def _best_per_patient(chunks: list[dict], max_k: int) -> list[dict]:
    seen: dict[str, dict] = {}
    for c in chunks:
        src = c["source"]
        if src not in seen:
            seen[src] = c
    return sorted(seen.values(), key=lambda x: x["score"], reverse=True)[:max_k]


def _fetch_identity_for_patients(patient_sources: list, chunks_mapping: list) -> list:
    identity_hits = []
    for src in patient_sources:
        id_chunk = next(
            (c for c in chunks_mapping
             if c["source"] == src
             and c.get("category") == "IDENTITE"
             and c.get("active", True)),
            None,
        )
        if id_chunk:
            identity_hits.append(_make_chunk(id_chunk, score=2.0))
    return identity_hits


def _multi_query_retrieve(emb_service, patient_chunks: list, k_per_query: int = 2) -> list:
    if not patient_chunks:
        return []

    texts = [c["text"] for c in patient_chunks]
    chunk_embs = emb_service.encode(texts)

    norms = np.linalg.norm(chunk_embs, axis=1, keepdims=True) + 1e-8
    chunk_embs_norm = chunk_embs / norms

    seen_idx: set = set()
    result: list = []

    for sq in _SOAP_SUBQUERIES:
        sq_emb = emb_service.encode([sq])[0]
        sq_norm = np.linalg.norm(sq_emb) + 1e-8
        sq_emb_norm = sq_emb / sq_norm

        scores = chunk_embs_norm @ sq_emb_norm

        top_indices = np.argsort(scores)[::-1][:k_per_query]
        for idx in top_indices:
            if float(scores[idx]) > 0.10 and int(idx) not in seen_idx:
                seen_idx.add(int(idx))
                c = patient_chunks[int(idx)]
                result.append({**_make_chunk(c, score=float(scores[idx]))})

    logger.info(f"[rag] Multi-query SOAP: {len(result)} chunks")
    return result


def retrieve_chunks(
    query: str,
    index,
    chunks_mapping: list,
    k: int,
    min_score: float,
    source_filter,
    use_soap: bool,
    is_cohort: bool,
    local_mode: bool
) -> list:
    emb_service = get_embedding_service()
    query_embedding = emb_service.encode([query])

    if source_filter:
        _src_set = {source_filter} if isinstance(source_filter, str) else set(source_filter)
    else:
        _src_set = None

    # ── BRANCHE 1 : SINGLE-PATIENT ──
    if _src_set:
        patient_chunks = [
            _make_chunk(c)
            for c in chunks_mapping
            if c["source"] in _src_set and c.get("active", True)
        ]
        logger.info(f"[rag] Single-patient: {len(patient_chunks)} chunks pour {_src_set}")

        is_note_patient = any(
            s.upper().startswith("NOTE_") or
            (s.endswith(".txt") and "NOTE_" in s.upper())
            for s in _src_set
        )

        if use_soap and patient_chunks:
            hits = _multi_query_retrieve(emb_service, patient_chunks, k_per_query=3)
            if len(hits) > k * 2:
                hits = hits[:k * 2]

        elif is_note_patient and patient_chunks:
            hits = sorted(patient_chunks, key=lambda c: c.get("date_score", 0.0), reverse=True)

        elif _RERANKER_AVAILABLE and patient_chunks:
            if _META_QUERY_RE.search(query):
                hits = sorted(patient_chunks, key=lambda c: c.get("date_score", 0.0), reverse=True)[:k]
            else:
                hits = _rerank(query, patient_chunks, min(k, len(patient_chunks)))

        else:
            hits = patient_chunks[:k]

    # ── BRANCHE 2 : MULTI-PATIENT (COHORTE) ──
    else:
        search_k = min(200, len(chunks_mapping))

        distances, indices = vector_store.search(index, query_embedding, k=search_k)

        faiss_hits = [
            _make_chunk(chunks_mapping[idx], score=float(score))
            for idx, score in zip(indices[0], distances[0])
            if idx != -1
            and idx < len(chunks_mapping)
            and chunks_mapping[idx].get("active", True)
        ]

        if bm25_engine.is_ready():
            bm25_hits = bm25_engine.search(query, top_k=search_k)

            _meta_lookup = {
                (c["source"], c["text"][:80]): (
                    c.get("date_score", 0.0),
                    c.get("page_number", 1),
                    c.get("active", True),
                )
                for c in chunks_mapping
            }
            for h in bm25_hits:
                ds, pg, act = _meta_lookup.get((h["source"], h["text"][:80]), (0.0, 1, True))
                h["date_score"] = ds
                h.setdefault("page_number", pg)
                h["active"] = act

            fused = reciprocal_rank_fusion(faiss_hits, bm25_hits)
            logger.info(f"[rag] Hybride RRF : {len(fused)} candidats")
        else:
            fused = faiss_hits

        if is_cohort and is_english(query):
            _pre_kws = (
                set(re.findall(r'[a-z]{3,}', query.lower().translate(_ACCENT_MAP)))
                - _COH_STOPWORDS
            )
            _fr_aug = []
            for kw in _pre_kws:
                if kw in _EN_TO_MEDICAL:
                    _fr_aug.extend(_EN_TO_MEDICAL[kw])

            if _fr_aug:
                aug_emb = emb_service.encode([" ".join(_fr_aug)])
                aug_dist, aug_idx = vector_store.search(index, aug_emb, k=search_k)
                aug_hits = [
                    _make_chunk(chunks_mapping[idx], score=float(score))
                    for idx, score in zip(aug_idx[0], aug_dist[0])
                    if idx != -1
                    and idx < len(chunks_mapping)
                    and chunks_mapping[idx].get("active", True)
                ]
                if aug_hits:
                    fused = reciprocal_rank_fusion(fused, aug_hits)

        pre_filter = [
            c for c in fused if c["score"] >= min_score and c.get("active", True)
        ][:50]

        if is_cohort:
            _clean = query.lower().translate(_ACCENT_MAP)
            _kws = [w for w in re.findall(r'[a-z]{3,}', _clean) if w not in _COH_STOPWORDS]
            _kws_set = set(_kws)

            for (a, b), alias in _MEDICAL_ALIASES.items():
                if a in _kws_set and b in _kws_set:
                    _kws.append(alias)

            _translated = []
            for kw in list(_kws_set):
                if kw in _EN_TO_MEDICAL:
                    _translated.extend(_EN_TO_MEDICAL[kw])
            if _translated:
                _kws = list(_kws_set) + _translated

            if local_mode:
                if _kws:
                    _min_match = min(2, len(_kws))
                    _kw_pats = [re.compile(r'\b' + kw + r'\b') for kw in _kws]
                    kw_filtered = [
                        c for c in pre_filter
                        if sum(
                            1 for p in _kw_pats
                            if p.search(c['text'].lower().translate(_ACCENT_MAP))
                        ) >= _min_match
                    ]
                    pre_filter = kw_filtered if kw_filtered else pre_filter

                hits = _best_per_patient(pre_filter, max_k=8)
                logger.info(f"[rag] Cohorte local: {len(hits)} patients")
            else:
                hits = _best_per_patient(pre_filter, max_k=k)
                logger.info(f"[rag] Cohorte: {len(hits)} patients")

        elif _RERANKER_AVAILABLE and len(pre_filter) > k:
            hits = _rerank(query, pre_filter, k)
        else:
            hits = pre_filter[:k]

    # ── TEMPORAL RERANKING ──
    for h in hits:
        ds = h.get("date_score") or 0.0
        h["score"] = h["score"] * (1 + _TEMPORAL_WEIGHT * ds)

    hits = sorted(hits, key=lambda x: x["score"], reverse=True)

    # ── ENRICHISSEMENT IDENTITÉ pour cohorte (mode API) ──
    if is_cohort and hits and not local_mode:
        unique_srcs = list({h["source"] for h in hits})
        id_hits = _fetch_identity_for_patients(unique_srcs, chunks_mapping)

        existing_texts = {h["text"][:80] for h in hits}
        new_id = [ih for ih in id_hits if ih["text"][:80] not in existing_texts]

        if new_id:
            hits = sorted(hits + new_id, key=lambda x: x["score"], reverse=True)
            logger.info(f"[rag] Cohorte: +{len(new_id)} chunks IDENTITE")

    return hits
