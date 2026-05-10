import re

_ID_RE = re.compile(r'^(\d+|[A-Z]\d+|NOTE)$')


def _parse_parts(source: str):
    base = re.sub(r'\.\w+$', '', source)
    parts = base.split("_")

    start = 0
    for i, p in enumerate(parts):
        if _ID_RE.match(p):
            start = i + 1
        else:
            break
    parts = parts[start:]

    if not parts:
        return [], []

    nom_parts, prenom_parts = [], []
    found_prenom = False
    for p in parts:
        if not found_prenom and p.isupper():
            nom_parts.append(p)
        else:
            found_prenom = True
            prenom_parts.append(p)

    return nom_parts, prenom_parts


def patient_label(source: str) -> str:
    """Retourne le nom affiché : 'Jean Claude MARTIN', 'Isabelle HENRY'."""
    nom_parts, prenom_parts = _parse_parts(source)
    if nom_parts and prenom_parts:
        return f"{' '.join(prenom_parts)} {' '.join(nom_parts)}"
    if nom_parts:
        return ' '.join(nom_parts)
    return source


def patient_label_lower(source: str) -> str:
    """Retourne le nom normalisé pour comparaison : 'jean claude martin'."""
    nom_parts, prenom_parts = _parse_parts(source)
    if nom_parts and prenom_parts:
        prenom = ' '.join(p.lower() for p in prenom_parts)
        nom = ' '.join(n.lower() for n in nom_parts)
        return f"{prenom} {nom}"
    if nom_parts:
        return ' '.join(n.lower() for n in nom_parts)
    base = re.sub(r'\.\w+$', '', source)
    return base.lower()
