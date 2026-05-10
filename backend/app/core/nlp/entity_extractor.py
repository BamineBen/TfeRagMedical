import re
import logging
from typing import List, Dict, Tuple

logger = logging.getLogger(__name__)

STOP_WORDS_FR = {
    "le", "la", "les", "un", "une", "des", "du", "de", "au", "aux",
    "ce", "cet", "cette", "ces", "mon", "ton", "son", "ma", "ta", "sa",
    "mes", "tes", "ses", "notre", "votre", "leur", "nos", "vos", "leurs",
    "je", "tu", "il", "elle", "on", "nous", "vous", "ils", "elles",
    "me", "te", "se", "moi", "toi", "lui", "soi", "eux",
    "qui", "que", "quoi", "dont", "où", "lequel", "laquelle", "lesquels",
    "quel", "quelle", "quels", "quelles",
    "de", "en", "à", "dans", "sur", "par", "pour", "avec", "sans",
    "sous", "vers", "chez", "entre", "mais", "donc", "car", "ni", "or",
    "et", "ou", "si", "que", "quand", "comme", "lorsque", "puisque",
    "est", "sont", "était", "être", "avoir", "fait", "faire", "peut",
    "peux", "veut", "veux", "doit", "dit", "dis", "dire", "faut",
    "aller", "venir", "voir", "savoir", "pouvoir", "vouloir", "devoir",
    "pas", "plus", "moins", "très", "bien", "aussi", "encore", "même",
    "tout", "tous", "toute", "toutes", "autre", "autres", "peu", "beaucoup",
    "trop", "assez", "déjà", "toujours", "jamais", "souvent", "parfois",
    "ici", "là", "puis", "ensuite", "après", "avant", "depuis", "pendant",
    "comment", "combien", "pourquoi",
    "résume", "résumé", "résumer", "resume", "donne", "donner", "dossier",
    "trouve", "trouver", "cherche", "chercher", "liste", "lister",
    "affiche", "afficher", "montre", "montrer", "explique", "expliquer",
    "dis", "parle", "parler", "raconte", "raconter", "décris", "décrire",
    "patient", "patiente", "patients", "médical", "medical", "médicaux",
    "monsieur", "madame", "mademoiselle", "docteur",
    "récapitulatif", "récap", "recap", "ayant",
}

_EN_FUNCTION_WORDS = frozenset({
    "a", "an", "the",
    "is", "are", "was", "were", "be", "been",
    "do", "does", "did", "has", "have", "had",
    "can", "could", "would", "should", "will",
    "not", "but", "and", "or", "nor",
    "in", "on", "at", "to", "by", "up", "of", "for", "as",
    "it", "he", "she", "we", "you", "my", "his", "her", "its",
    "our", "their", "this", "that", "these", "those",
    "who", "how", "when", "where", "why", "what", "which",
    "get", "give", "show",
})

MEDICAL_ABBREVIATIONS = {
    "ta": ["tension", "artérielle", "mmHg"],
    "fc": ["fréquence", "cardiaque", "bpm"],
    "rh": ["rhésus", "groupe sanguin"],
    "imc": ["indice", "masse", "corporelle", "poids", "taille"],
    "hta": ["hypertension", "artérielle"],
    "ldl": ["cholestérol", "lipidique"],
    "hdl": ["cholestérol", "lipidique"],
    "hba1c": ["glycémie", "glucose", "diabète"],
    "nfs": ["hémoglobine", "leucocytes", "plaquettes", "numération"],
    "crp": ["inflammation", "protéine"],
    "dfg": ["rénal", "créatinine", "filtration"],
    "ecg": ["électrocardiogramme", "cardiaque", "rythme"],
    "irm": ["imagerie", "résonance", "magnétique"],
    "bpco": ["bronchopneumopathie", "pulmonaire"],
    "lca": ["ligament", "croisé", "antérieur"],
    "lcp": ["ligament", "croisé", "postérieur"],
    "lli": ["ligament", "latéral", "interne"],
    "lle": ["ligament", "latéral", "externe"],
}

PATHOLOGY_SEARCH_TERMS: Dict[str, List[str]] = {
    "diabète": ["diabète", "diabétique", "DT2", "insuline", "metformine", "antidiabétique"],
}

PATHOLOGY_KEYWORDS = {
    "ligament": ["ligament", "ligamentaire", "entorse", "rupture", "LCA", "LCP", "croisé"],
    "fracture": ["fracture", "fracturé", "ostéosynthèse", "consolidation"],
    "diabète": ["diabète", "diabétique", "glycémie", "HbA1c", "insuline", "glucose",
                "type 2", "type 1", "DT2", "metformine", "hypoglycémie", "antidiabétique"],
    "hypertension": ["hypertension", "HTA", "tension", "antihypertenseur"],
    "asthme": ["asthme", "asthmatique", "bronchospasme", "ventoline"],
    "allergie": ["allergie", "allergique", "allergène", "anaphylaxie",
                 "acarien", "acariens", "pollen", "pénicilline", "aspirine",
                 "lactose", "gluten", "noix", "latex", "chat", "chien", "codéine",
                 "ibuprofène", "amoxicilline", "sulfamide"],
    "cancer": ["cancer", "tumeur", "néoplasie", "oncologie", "métastase", "chimiothérapie"],
    "cardiaque": ["cardiaque", "cardiopathie", "insuffisance cardiaque", "infarctus", "coronaire"],
    "pulmonaire": ["pulmonaire", "pneumonie", "BPCO", "embolie", "pneumothorax"],
    "rénal": ["rénal", "rein", "insuffisance rénale", "dialyse", "créatinine"],
    "hépatique": ["hépatique", "foie", "cirrhose", "hépatite"],
    "arthrose": ["arthrose", "arthrite", "articulaire", "dégénératif"],
    "chirurgie": ["chirurgie", "opération", "intervention", "chirurgical", "opéré"],
    "grossesse": ["grossesse", "enceinte", "obstétrique", "accouchement"],
    "dépression": ["dépression", "anxiété", "psychiatrique", "antidépresseur"],
    "infection": ["infection", "infectieux", "sepsis", "antibiotique"],
    "obésité": ["obésité", "obèse", "surpoids", "IMC"],
}


class EntityExtractor:
    """Utilitaire pour l'extraction d'entités (patients, pathologies, termes de recherche)."""

    def __init__(self):
        self.UNDERSCORE_NAME_PATTERN = re.compile(
            r"([A-ZÀ-Üa-zà-ü]{2,})_([A-ZÀ-Üa-zà-ü]{2,})", re.IGNORECASE
        )
        self.PATIENT_KEYWORD_PATTERN = re.compile(
            r"(?:patient|patiente|monsieur|madame|mme|mr|m\.)\s+([A-ZÀ-Üa-zà-ü]{2,})(?:\s+([A-ZÀ-Üa-zà-ü]{2,}))?",
            re.IGNORECASE
        )
        self.PREPOSITION_NAME_PATTERN = re.compile(
            r"(?:^|\s)(?:d'|(?:de|du|pour|chez|sur|of|for|about|from)\s)(?:monsieur|madame|mme|mr|m\.\s*)?([A-ZÀ-Üa-zà-ü]{2,})(?:\s+([A-ZÀ-Üa-zà-ü]{2,}))?",
            re.IGNORECASE
        )
        self.UPPERCASE_NAME_PATTERN = re.compile(
            r"([A-ZÀ-Ü]{2,})\s+([A-ZÀ-Ü][a-zà-ü]+)"
        )
        self.FIRSTNAME_LASTNAME_PATTERN = re.compile(
            r"([A-ZÀ-Ü][a-zà-ü]+)\s+([A-ZÀ-Ü][a-zà-ü]{2,})"
        )
        self.DOSSIER_NAME_PATTERN = re.compile(
            r"(?:dossier|résumé?|profil|fiche|info(?:rmations?)?|synthèse)\s+(?:de\s+|du\s+|complet\s+)?(?:le\s+|la\s+)?([a-zà-ü]{2,})\s+([a-zà-ü]{2,})",
            re.IGNORECASE
        )

    @staticmethod
    def _strip_accents(text: str) -> str:
        import unicodedata
        return unicodedata.normalize('NFD', text).encode('ascii', 'ignore').decode('ascii').lower()

    @staticmethod
    def get_name_title_filters(patient_name: str) -> List[str]:
        parts = patient_name.split()
        upper_parts = [
            p for p in parts
            if (p.isalpha() and p == p.upper() and len(p) >= 2)
            or re.match(r'^P\d{5}$', p, re.IGNORECASE)
        ]
        return upper_parts if upper_parts else parts

    def extract_entities(self, query: str, conversation_history: List[Dict] = None) -> Tuple[str | None, List[str]]:
        patient_name = None

        m = re.search(r'\b(P\d{5})\b', query, re.IGNORECASE)
        if m: patient_name = m.group(1).upper()

        if not patient_name:
            m = self.UNDERSCORE_NAME_PATTERN.search(query)
            if m: patient_name = f"{m.group(1)} {m.group(2)}"

        if not patient_name:
            m = self.PATIENT_KEYWORD_PATTERN.search(query)
            if m:
                p1, p2 = m.group(1), m.group(2)
                patient_name = f"{p1} {p2}" if p2 else p1

        if not patient_name:
            m = self.PREPOSITION_NAME_PATTERN.search(query)
            if m:
                p1, p2 = m.group(1), m.group(2)
                if (p1[0].isupper() and p1.lower() not in STOP_WORDS_FR and p1.lower() not in _EN_FUNCTION_WORDS):
                    patient_name = f"{p1} {p2}" if p2 else p1

        if not patient_name:
            m = self.UPPERCASE_NAME_PATTERN.search(query)
            if m: patient_name = f"{m.group(1)} {m.group(2)}"

        if not patient_name:
            m = self.FIRSTNAME_LASTNAME_PATTERN.search(query)
            if m:
                p1, p2 = m.group(1), m.group(2)
                if (p1.lower() not in STOP_WORDS_FR and p2.lower() not in STOP_WORDS_FR
                        and p1.lower() not in _EN_FUNCTION_WORDS and p2.lower() not in _EN_FUNCTION_WORDS):
                    patient_name = f"{p2} {p1}"

        if not patient_name:
            m = self.DOSSIER_NAME_PATTERN.search(query)
            if m:
                p1, p2 = m.group(1), m.group(2)
                if p1.lower() not in STOP_WORDS_FR and p2.lower() not in STOP_WORDS_FR:
                    patient_name = f"{p1} {p2}"

        _current_is_cross = self.detect_pathology_search(query) is not None
        if not patient_name and not _current_is_cross and conversation_history:
            for msg in reversed(conversation_history[-6:]):
                if msg.get("role") == "user":
                    prev_patient, _ = self.extract_entities(msg.get("content", ""))
                    _is_pathology_name = (
                        prev_patient and
                        prev_patient.lower().split()[0] in {
                            "diabète", "diabete", "diabétique", "allergie", "hypertension",
                            "asthme", "cancer", "fracture", "obésité", "infection",
                            "diab", "allerg", "hypertens", "asthm"
                        }
                    )
                    if prev_patient and not _is_pathology_name:
                        patient_name = prev_patient
                        break

        terms = []
        exclude = set()
        if patient_name:
            for part in patient_name.lower().split():
                exclude.add(part)

        medical_phrases = [
            (r'groupe\s+sanguin', ["groupe sanguin", "Groupe sanguin", "rhésus"]),
            (r'tension\s+art[ée]rielle', ["tension", "artérielle", "mmHg", "TA"]),
            (r'fr[ée]quence\s+cardiaque', ["fréquence", "cardiaque", "bpm", "FC"]),
            (r'poids\s+et\s+taille', ["poids", "taille", "IMC"]),
            (r'ant[ée]c[ée]dents?\s+m[ée]dicaux', ["antécédents", "médicaux"]),
            (r'ant[ée]c[ée]dents?\s+familiaux', ["antécédents", "familiaux"]),
            (r'ant[ée]c[ée]dents?', ["antécédents"]),
            (r'traitement\s+en\s+cours', ["traitement", "prescription", "médicament"]),
            (r'bilan\s+(sanguin|biologique|complet)', ["biologie", "bilan", "résultats"]),
            (r'allergies?', ["allergie", "allergies"]),
            (r'vaccinations?|vaccins?', ["vaccination", "vaccin"]),
            (r'hospitalisation', ["hospitalisation", "hospitalisé", "entrée", "sortie"]),
            (r'imagerie|radiologie|scanner|irm|radio', ["imagerie", "radio", "scanner", "IRM", "échographie"]),
            (r'consultation', ["consultation", "motif", "diagnostic"]),
            (r'glyc[ée]mie|diab[eè]te', ["glycémie", "HbA1c", "glucose", "diabète"]),
            (r'cholest[ée]rol|lipid', ["cholestérol", "LDL", "HDL", "triglycérides"]),
            (r'anamn[èe]se|historique', ["anamnèse", "historique", "antécédents", "histoire"]),
            (r'blessure|traumatisme|accident', ["blessure", "traumatisme", "accident", "fracture"]),
            (r'ligament', ["ligament", "ligamentaire", "entorse", "rupture", "genou"]),
            (r'chirurgie|op[ée]ration', ["chirurgie", "opération", "intervention"]),
            (r'ordonnance|prescription', ["ordonnance", "prescription", "médicament", "traitement"]),
            (r'(?:\bâge\b|date\s+de\s+naissance|né[e]?\s+le)', ["naissance", "IDENTIFICATION"]),
            (r'médecin\s+traitant|docteur\s+traitant', ["médecin traitant", "docteur", "généraliste"]),
            (r'objectifs?\s+thérapeut', ["objectifs", "thérapeutiques"]),
        ]

        query_lower = query.lower()
        for phrase_pattern, search_terms in medical_phrases:
            if re.search(phrase_pattern, query_lower):
                terms.extend(search_terms)

        for abbrev, expansions in MEDICAL_ABBREVIATIONS.items():
            if re.search(rf'\b{abbrev}\b', query_lower):
                terms.extend(expansions)

        for word in query.split():
            w_clean = re.sub(r'[^a-zA-Zà-üÀ-Ü0-9+\-]', '', word)
            if (len(w_clean) >= 3
                    and w_clean.lower() not in exclude
                    and w_clean.lower() not in STOP_WORDS_FR
                    and w_clean.lower() not in _EN_FUNCTION_WORDS):
                terms.append(w_clean)

        seen = set()
        unique_terms = []
        for t in terms:
            if t.lower() not in seen:
                seen.add(t.lower())
                unique_terms.append(t)

        return patient_name, unique_terms

    def detect_pathology_search(self, query: str) -> List[str | None]:
        q_lower = query.lower()
        q_normalized = self._strip_accents(query)

        cross_patterns = [
            r'(?:patients?|personnes?|malades?)\s+(?:ayant|avec|qui\s+(?:ont|avaient|pr[ée]sentent)|atteints?\s+de|souffrant\s+de)',
            r'(?:tou(?:t|s|te|tes)?\s+les?\s+|quels?\s+|combien\s+de\s+)(?:patients?|personnes?|dossiers?)',
            r'(?:r[ée]capitulatif|liste|r[ée]cap)\s+(?:des?\s+)?(?:patients?|personnes?)',
            r'qui\s+(?:a|ont|avai(?:t|ent))\s+(?:eu|un|une|des|le|la)',
            r'(?:which|what|all|list|find|show)\s+(?:patients?|people|persons?)',
            r'(?:patients?|who)\s+(?:has|have|had|are|were|with|taking|allergic\s+to)',
            r'\b(?:diab[eé]tiques?|allergiques?|hypertendus?|asthmatiques?|ob[eè]ses?|canc[eé]reux|dialys[eé]s?)\b',
            r'\b(?:diabetic|allergic|hypertensive|asthmatic|obese|pregnant)\b',
        ]

        if not any(re.search(p, q_lower) for p in cross_patterns):
            return None

        EN_PATHOLOGY_MAP = {
            "allerg": "allergie", "diabetic": "diabète", "diabetes": "diabète",
            "hypertens": "hypertension", "asthma": "asthme", "cancer": "cancer",
            "fracture": "fracture", "obes": "obésité",
        }

        search_terms = []
        for en_key, fr_path in EN_PATHOLOGY_MAP.items():
            if en_key in q_normalized:
                primary = PATHOLOGY_SEARCH_TERMS.get(fr_path)
                keywords = PATHOLOGY_KEYWORDS.get(fr_path, [])
                search_terms.extend(primary if primary else keywords)
                break

        if not search_terms:
            for pathology, keywords in PATHOLOGY_KEYWORDS.items():
                path_normalized = self._strip_accents(pathology)
                match = (
                    path_normalized in q_normalized
                    or any(kw.lower() in q_lower for kw in keywords)
                    or any(self._strip_accents(kw) in q_normalized for kw in keywords)
                )
                if match:
                    primary = PATHOLOGY_SEARCH_TERMS.get(pathology)
                    search_terms.extend(primary if primary else keywords)
                    break

        if not search_terms:
            for w in query.split():
                w_clean = re.sub(r'[^a-zA-Zà-üÀ-Ü]', '', w)
                if len(w_clean) >= 4 and w_clean.lower() not in STOP_WORDS_FR:
                    search_terms.append(w_clean)

        return list(set(search_terms)) if search_terms else None

    @staticmethod
    def extract_patient_name_from_title(title: str) -> str:
        name = re.sub(r'\.(pdf|txt|docx?)$', '', title, flags=re.IGNORECASE)
        m = re.search(r'(P\d{5})_(.+)', name)
        if m:
            pid, rest = m.group(1), m.group(2).replace("_", " ").strip()
            return f"{rest} ({pid})"
        for prefix in ["Dossier_Medical_", "Dossier_", "P00"]:
            name = re.sub(rf'^{prefix}', '', name)
        return re.sub(r'^\d+_', '', name).replace("_", " ").strip()
