import re
from app.utils.naming import patient_label as _patient_label

def _extract_section(text: str, *headers: str) -> str:
    """Extrait le contenu d'une section ## Header d'une note SOAP."""
    for h in headers:
        pat = re.compile(
            r'##\s*' + h + r'[^\n]*\n(.*?)(?=\n##\s|\Z)',
            re.IGNORECASE | re.DOTALL
        )
        m = pat.search(text)
        if m:
            content = m.group(1).strip()
            content = re.sub(r'\n-\s+', '; ', content).strip('; ')
            return content[:200] if content else "Non documenté"
    return "Non documenté"

def _build_cohort_table_local(hits: list, n_pts: int) -> str:
    """
    Construit le tableau comparatif directement depuis les chunks.
    """
    rows: list[str] = []
    seen_sources: set = set()

    for hit in hits:
        src = hit.get("source", "")
        if src in seen_sources:
            continue
        seen_sources.add(src)

        text = hit.get("parent_text") or hit.get("text", "")
        label = _patient_label(src)

        age_m = re.search(r'[ÂA]ge\s*[:\-]\s*(\d+)\s*ans?', text, re.IGNORECASE)
        sex_m = re.search(r'[Ss]exe\s*[:\-]\s*(Masculin|F[eé]minin|M|F)\b', text, re.IGNORECASE)
        age_str = age_m.group(1) + " ans" if age_m else "NR"
        sex_str = sex_m.group(1).capitalize() if sex_m else "NR"
        age_genre = f"{age_str}, {sex_str}"

        motif = _extract_section(text, "Motif", "Motif de consultation", "Pathologie")
        if motif == "Non documenté":
            first_line = next(
                (l.strip() for l in text.splitlines()
                 if len(l.strip()) > 20 and not l.startswith('[') and not l.startswith('#')),
                "Non documenté"
            )
            motif = first_line[:150]

        traitement = _extract_section(
            text, "Traitement conservateur", "Traitement chirurgical",
            "Traitement décidé", "Traitement proposé", "Traitement",
            "Plan thérapeutique", "Plan", "Prescription", "Prise en charge",
        )

        evolution = _extract_section(
            text, "Évolution", "Evolution", "Suivi", "Assessment", "Résultat", "Résultats", "Outcome",
        )

        date_raw = hit.get("indexed_at", "")
        if not date_raw:
            dm = re.search(r'\[(\d{4}-\d{2}-\d{2})\]', text)
            date_raw = dm.group(1) if dm else "Non documenté"
        else:
            date_raw = str(date_raw)[:10]

        rows.append(f"| {label} | {age_genre} | {motif} | {traitement} | {evolution} | {date_raw} |")

    if not rows:
        return "Aucun patient ne présente ce critère dans les extraits analysés."

    header = (
        "| Patient | Âge / Genre | Pathologie / Motif | Traitement utilisé | Évolution / Résultat | Date |\n"
        "|---------|-------------|-------------------|-------------------|---------------------|------|"
    )
    total_line = f"\n**Total : {len(rows)} patient(s) identifié(s) sur {n_pts} dossier(s) analysé(s)**"
    return header + "\n" + "\n".join(rows) + "\n" + total_line

def build_context(hits: list, max_context_chars: int, is_cohort: bool, local_mode: bool) -> tuple:
    """
    Construit le bloc de contexte avec citations [N].
    Retourne:
      - context_block (str)
      - citation_map (list)
      - known_labels (list) pour le mode cohorte local
    """
    context_parts = []
    citation_map = []
    total_len = 0
    seen_parent_hashes = set()
    shown_n = 0
    known_labels = []
    seen_srcs_prompt = set()

    for hit in hits:
        parent_text = hit.get("parent_text") or hit["text"]
        parent_hash = hash(parent_text)
        # Déduplication : on évite d'envoyer 2× le même bloc parent au LLM.
        # EXCEPTION : si le chunk enfant (hit["text"]) est unique, on l'inclut
        # quand même avec un hash distinct — cela couvre les cas de comptage
        # (ex: plusieurs consultations dans la même section parent).
        child_hash = hash(hit["text"])
        dedup_key = parent_hash if parent_hash not in seen_parent_hashes else child_hash
        if dedup_key in seen_parent_hashes:
            continue
        if total_len >= max_context_chars:
            break
        seen_parent_hashes.add(dedup_key)
        shown_n += 1
        
        label = _patient_label(hit["source"])
        
        if is_cohort and local_mode:
            if hit["source"] not in seen_srcs_prompt:
                seen_srcs_prompt.add(hit["source"])
                known_labels.append(label)

        category = hit.get("category", "AUTRE")
        cat_tag = f" [{category}]" if category and category != "AUTRE" else ""
        src = hit["source"]
        
        _is_note_chunk = bool(
            hit.get("note_id") or
            src.upper().startswith("NOTE_") or
            (src.endswith(".txt") and "NOTE_" in src.upper())
        )
        src_type = "[NOTE]" if _is_note_chunk else "[PDF]"

        if is_cohort and local_mode:
            tagged = f"[PATIENT: {label}]\n{parent_text}"
        else:
            tagged = f"[Extrait {shown_n}]{cat_tag} {src_type} [Patient: {label}]\n{parent_text}"

        if total_len + len(tagged) <= max_context_chars:
             # in cohort+local, we separate blocks with '---' later
             if is_cohort and local_mode:
                 context_parts.append(tagged)
                 total_len += len(tagged) + 7
             else:
                 context_parts.append(tagged)
                 total_len += len(tagged)
             
             citation_map.append({
                 "id": shown_n,
                 "source": hit["source"],
                 "source_type": src_type.strip("[]"),
                 "patient": label,
                 "preview": hit["text"][:400],
                 "score": round(hit["score"], 3),
                 "score_pct": f"{min(99, round(hit['score'] * 100))}%",
                 "date_score": round(hit.get("date_score") or 0.0, 3),
                 "page_number": hit.get("page_number", 1),
                 "category": category,
             })
        else:
            remaining = max_context_chars - total_len
            if remaining > 100:
                context_parts.append(tagged[:remaining])
            break

    if is_cohort and local_mode:
         context_block = "\n\n---\n\n".join(context_parts) or "(aucun extrait pertinent trouvé)"
    else:
         context_block = "\n---\n".join(context_parts) or "(aucun extrait pertinent trouvé)"
         
    return context_block, citation_map, known_labels
