"""
prompts.py — Logique bilingue, templates de prompts et analyse d'intention pour le RAG.

Architecture (SOLID / DRY) :
─────────────────────────────
1. CONSTANTES LEXICALES  : regex de détection (greeting, SOAP, cohorte, médical, off-topic)
2. UTILITAIRES           : is_english(), classify_query(), is_soap_query(), is_cohort_query()
3. BLOCS RÉUTILISABLES   : _FORMAT_RULES_*, _build_header(), _build_footer()
4. GÉNÉRATION DE PROMPT  : generate_system_prompt() — point d'entrée unique
5. TRADUCTION            : _apply_translation_if_needed()

Principe DRY appliqué :
- Les règles de formatage sont centralisées dans des constantes (_FORMAT_RULES_*)
- Chaque type de prompt (note, soap, question, cohorte) compose son prompt
  à partir de blocs réutilisables → aucune duplication de règles.
- Si on veut changer le format de sortie, on modifie UN seul endroit.

Principe SRP (Single Responsibility) :
- classify_query()          → détermine le TYPE de requête (greeting / medical / general)
- is_soap_query()           → détecte si c'est une synthèse SOAP
- is_cohort_query()         → détecte si c'est une recherche multi-patient
- generate_system_prompt()  → assemble le prompt final selon le cas
- _apply_translation_if_needed() → traduit en anglais si besoin
"""
import re

# ═══════════════════════════════════════════════════════════════════════
# 1. CONSTANTES LEXICALES — Regex de détection d'intention
# ═══════════════════════════════════════════════════════════════════════
# Chaque regex identifie un TYPE de requête utilisateur.
# Utilisées par classify_query(), is_soap_query(), is_cohort_query().

_SOAP_TRIGGERS = re.compile(
    r'(synth[eè]se|r[eé]sum[eé]|bilan global|analyse compl[eè]te|'
    r'vue d.ensemble|pr[eé]sente.moi|profil complet|fiche|dossier complet|'
    r'tout sur|tout ce que tu sais|rapport complet|'
    r'bilan complet|[eé]tat de sant[eé]|point complet|pr[eé]sentation|'
    r'summarize|summarise|summariz|full\s+(summary|report|profile|file)|'
    r'complete\s+(summary|record|file|report)|overview|patient\s+(file|record|profile))',
    re.IGNORECASE | re.UNICODE,
)

_SECTION_TRIGGERS = re.compile(
    r'\b(consultation|antécédent|traitement|médicament|biologie|analyse|imagerie|'
    r'vaccin|hospitalisation|constante|allergie|examen|identité|ordonnance|'
    r'posologie|prescription|bilan\s+(bio|lipidique|rénal|hépatique)|'
    r'groupe\s+sanguin|médecin\s+traitant|date\s+de\s+naissance|'
    r'ECG|radio|scanner|IRM|échographie|spirométrie)\b',
    re.IGNORECASE | re.UNICODE,
)

_COHORT_TRIGGERS = re.compile(
    r'\b(patients?\s+(ayant|avec|qui\s+ont|ont\s+eu|ont|atteints?\s+de|souffrant\s+de|présentant|'
    r'traités?\s+pour|diagnostiqu[eé]s?\s+(de|avec))|'
    r'tous?\s+les?\s+patients?|quels?\s+patients?|combien\s+de\s+patients?|'
    r'liste\s+des?\s+patients?|historique\s+des?\s+patients?|'
    r'comparer?\s+les?\s+patients?|comparaison\s+de?\s+patients?|'
    r'cohorte|recherche\s+comparative|vue\s+d.ensemble\s+des?\s+patients?|'
    r'all\s+patients?|which\s+patients?|patients?\s+with|'
    # ── Adjectifs médicaux sans le mot "patients" ──────────────────────
    # Permettent : "liste des hypertendus", "quels diabétiques ont…"
    r'les?\s+(hypertendus?|diabétiques?|insuffisants?\s+cardiaques?|asthmatiques?|'
    r'bpco|épileptiques?|parkinsoniens?|cancéreux|obèses?)|'
    # ── Formulations "parmi" / "ceux qui" ──────────────────────────────
    r'parmi\s+(les?\s+)?patients?|parmi\s+(vos?|nos?)\s+patients?|'
    r'tous?\s+ceux\s+(qui|avec|ayant)|lesquels?\s+(ont|sont|présentent)|'
    r'ceux\s+qui\s+(ont|sont|présentent|souffrent)|'
    # ── Comparaisons et tableaux ────────────────────────────────────────
    r'tableau\s+comparatif|tableau\s+des?\s+patients?|'
    r'compare\s+patients?|patient\s+comparison|'
    # ── Requêtes épidémiologiques ───────────────────────────────────────
    r'(combien|quelle\s+proportion|quel\s+pourcentage)\s+(de\s+)?patients?|'
    r'prévalence|incidence|fréquence\s+de\s+(la\s+)?pathologie)\b',
    re.IGNORECASE | re.UNICODE,
)

_GREETINGS = re.compile(
    r'^(bonjour|bonsoir|salut|hello|hi|hey|coucou|yo|'
    r'merci|au revoir|à bient[oô]t|bonne journ[eé]e|'
    r'comment [çc]a va|comment vas.tu|quoi de neuf|'
    r'ça va|ca va)\s*[?!.]*$',
    re.IGNORECASE | re.UNICODE,
)

_CONVERSATIONAL = re.compile(
    r'^(tu\s+vas\s+bien|t.as\s+bien|tu\s+t.en\s+sors|'
    r'tu\s+comprends|tu\s+m.entends|tu\s+m.as\s+compris|tu\s+as\s+compris|'
    r'tu\s+es\s+(qui|quoi|l[àa]|capable)|qui\s+es.tu|qu.est.ce\s+que\s+tu\s+es|t.es\s+quoi|'
    r'tu\s+(t.appelles|te\s+pr[eé]sentes)|comment\s+tu\s+t.appelles|'
    r"c.est\s+quoi\s+ton\s+(r[oô]le|but|usage|nom)|"
    r'tu\s+peux\s+(faire\s+)?quoi|que\s+peux.tu\s+faire|'
    r'est.ce\s+que\s+tu\s+(comprends|peux|sais|connais)|'
    r'how\s+are\s+you|who\s+are\s+you|what\s+(are|can)\s+you|do\s+you\s+understand)\s*[?!.]*$',
    re.IGNORECASE | re.UNICODE,
)

_MEDICAL_KW = re.compile(
    r'(patient|dossier|diagnostic|traitement|m[eé]dicament|ordonnance|'
    r'pathologie|sympt[oô]me|allergi|ant[eé]c[eé]dent|chirurgi|'
    r'biologi|examen|consultation|hospitali|vaccin|'
    r'identit[eé]|identifi|'
    # ── V10 : interventions, opérations, actes médicaux ──
    r'intervention|op[eé]rat|op[eé]r[eé]e?s?|acte|geste|soin|'
    r'rdv|rendez.vous|visite|complication|[eé]volution|'
    r'prise.en.charge|r[eé]veil|anesth[eé]si|'
    r'biopsie|ponction|endoscop|coloscop|gastroscop|'
    r'kin[eé]|r[eé][eé]ducation|infirmi|pansement|'
    # ── verbes médicaux courants en question ──
    r'a.t.il\s+(eu|été|reçu|pris|subi)|a.t.elle\s+(eu|été|reçu|prise|subi)|'
    r'reçu|prend|prise|prescrit|hospitalis|op[eé]r[eé]|subi|'
    # ── existants ──
    r'diab[eè]te|hypertension|cancer|infection|fracture|insuffisance|'
    r'h[eé]moglobine|cr[eé]atinine|glyc[eé]mie|cholest[eé]rol|tension|'
    r'mg|cp|comprim[eé]|posologi|dose|prescription|'
    r'imagerie|scanner|irm|radio|[eé]cho|bilan|analyse|'
    r'ecg|ekg|[eé]lectrocardiogramme|spirom[eé]trie|'
    r'soap|synth[eè]se|r[eé]sum[eé]|fiche|profil|vue d.ensemble|'
    r'qui est|pr[eé]sente|quels?\s+patients?|combien|liste|'
    r'infarctus|avc|arythmie|fibrillation|asthme|bpco|'
    r'parkinson|alzheimer|d[eé]mence|fibromyalgie|thyro[iï]de|'
    r'constante|poids|taille|imc|spo2|saturation|'
    r'note|atomique|derni[eè]re?\s+consultation|suivi|dur[eé]e|s[eé]jour|'
    r'contre.indication|interaction|effet\s+ind[eé]sirable|'
    r'plaquette|leucocyte|globule|troponine|bnp|crp|psa|tsh|tpo|'
    r'corticoth[eé]rapie|antibioth[eé]rapie|chimioth[eé]rapie|'
    r'motif|rappel|vaccination|groupe\s+sanguin|m[eé]decin\s+traitant|'
    r'record|treatment|medication|drug|allerg|diagnos|history|'
    r'admission|vaccine|blood|glucose|cholesterol|renal|cardiac|lipid|thyroid|'
    r'summary|summarize|summarise|summariz|file\s+for|follow.up|dosage|imaging|ultrasound|spirometry|'
    r'electrocardiogram|hospital|stay|stays|reason|length|result|'
    r'contraindication|interaction|side\s+effect|'
    r'anticoagulant|antibiotic|chemotherapy|surgery|surgical|procedure|'
    r'which\s+patients?|list\s+of|show\s+me|give\s+me|what\s+(are|is|were|was)|who\s+is|'
    r'obesity|obese|diabetes|hypertensive|asthma|'
    r'weight|height|bmi|saturation|troponin|creatinine|hemoglobin|'
    r'last\s+consultation|last\s+visit|current\s+treatment|medical\s+record|patient\s+file|clinical)',
    re.IGNORECASE | re.UNICODE,
)

_PATIENT_NAME_RE = re.compile(
    r'\b[A-ZÀÁÂÄÈÉÊËÎÏÔÖÙÚÛÜ]{4,}\b'
    r'|\b[A-Z][a-zéèêëàâùûîïôöç]+\s+[A-Z]{3,}\b',
    re.UNICODE,
)

# ═══════════════════════════════════════════════════════════════════════
# 2. RÉPONSES PRÉ-DÉFINIES (greeting, off-topic)
# ═══════════════════════════════════════════════════════════════════════
# Quand la requête n'est pas médicale, on renvoie directement ces textes
# sans interroger le LLM → économie de tokens et temps de réponse.

OFF_TOPIC_RESPONSE = (
    "Je suis exclusivement configuré pour analyser des **dossiers médicaux patients**.\n\n"
    "Posez-moi une question médicale, par exemple :\n"
    "- « Quel est le traitement en cours de ce patient ? »\n"
    "- « Résume les antécédents de M. DUPONT »\n"
    "- « Quels patients sont diabétiques ? »"
)

_OFF_TOPIC_RESPONSE_EN = (
    "I am exclusively configured to analyse **patient medical records**.\n\n"
    "Please ask a medical question, for example:\n"
    "- \"What is the current treatment for this patient?\"\n"
    "- \"Summarise the history of Mr. DUPONT\"\n"
    "- \"Which patients have diabetes?\""
)

GREETING_RESPONSE = (
    "Bonjour ! 👋 Je suis votre **assistant médical RAG**, conçu pour analyser les dossiers patients.\n\n"
    "Je peux vous aider avec :\n"
    "- 💊 Traitements et médicaments en cours\n"
    "- 🧪 Résultats biologiques et bilans\n"
    "- 📊 Synthèses SOAP complètes\n"
    "- 👥 Recherches multi-patients (cohortes)\n"
    "- 🗓️ Plannings des médecins (agenda)\n\n"
    "**Exemples de questions :**\n"
    "- *« Quels sont les traitements actuels de Sophie LECOMTE ? »*\n"
    "- *« Fais une synthèse SOAP du dossier de Nguyen Thanh Van »*\n"
    "- *« Liste tous les patients diabétiques »*\n"
    "- *« Horaires du Dr Dupont ? »*"
)

_GREETING_RESPONSE_EN = (
    "Hello! 👋 I am your **medical RAG assistant**, designed to analyse patient records.\n\n"
    "I can help you with:\n"
    "- 💊 Current treatments and medications\n"
    "- 🧪 Lab results and blood tests\n"
    "- 📊 Complete SOAP summaries\n"
    "- 👥 Multi-patient searches (cohorts)\n"
    "- 🗓️ Doctor schedules (agenda)\n\n"
    "**Example questions:**\n"
    "- *\"What are the current treatments for Sophie LECOMTE?\"*\n"
    "- *\"Generate a SOAP summary for Nguyen Thanh Van\"*\n"
    "- *\"List all diabetic patients\"*\n"
    "- *\"What are Dr Dupont's office hours?\"*"
)

# ═══════════════════════════════════════════════════════════════════════
# 3. DÉTECTION DE LANGUE
# ═══════════════════════════════════════════════════════════════════════

_EN_WORDS = frozenset({
    'what', 'which', 'who', 'when', 'where', 'how', 'why',
    'is', 'are', 'was', 'were', 'the', 'of', 'for', 'in',
    'do', 'does', 'has', 'have', 'had', 'can', 'could',
    'give', 'show', 'list', 'tell', 'find', 'get', 'me',
    'please', 'summarize', 'summarise', 'describe',
    'my', 'his', 'her', 'its', 'their', 'our',
    'last', 'first', 'current', 'recent', 'latest', 'missing',
    'and', 'not', 'this', 'that', 'from', 'about', 'any', 'all',
    'results', 'records', 'entries', 'stays', 'reasons', 'lengths',
    'abnormal', 'complete', 'missing', 'documented', 'recommended',
    'hello', 'hi', 'hey', 'thanks', 'thank', 'ok', 'okay', 'yes', 'no',
})


# ═══════════════════════════════════════════════════════════════════════
# 4. FONCTIONS UTILITAIRES — Classification de requêtes
# ═══════════════════════════════════════════════════════════════════════
# Chaque fonction a UNE seule responsabilité (SRP).

def is_english(text: str) -> bool:
    """Détecte si la requête est en anglais en comptant les mots anglais connus."""
    clean = re.sub(r'\s*\(Dossier\s*:.*\)\s*$', '', text, flags=re.IGNORECASE).strip()
    words = set(clean.lower().split())
    threshold = 1 if len(words) <= 3 else 2
    return len(words & _EN_WORDS) >= threshold


def get_greeting_response(query: str) -> str:
    """Retourne la réponse de greeting dans la bonne langue."""
    return _GREETING_RESPONSE_EN if is_english(query) else GREETING_RESPONSE


def get_offtopic_response(query: str) -> str:
    """Retourne la réponse off-topic dans la bonne langue."""
    return _OFF_TOPIC_RESPONSE_EN if is_english(query) else OFF_TOPIC_RESPONSE


def classify_query(query: str) -> str:
    """
    Classifie la requête en 3 catégories :
    - "greeting"  : bonjour, salut, comment ça va, etc.
    - "medical"   : contient des mots-clés médicaux ou un nom de patient
    - "general"   : tout le reste (potentiellement off-topic)

    Flux : greeting → conversational → medical keywords → patient name → general
    """
    q = query.strip()
    core = re.sub(r'\s*\(Dossier\s*:.*\)\s*$', '', q, flags=re.IGNORECASE).strip()

    if len(core) < 3:
        return "greeting"
    if _GREETINGS.match(core):
        return "greeting"
    if _CONVERSATIONAL.match(core):
        return "greeting"
    if _MEDICAL_KW.search(core):
        return "medical"
    if _PATIENT_NAME_RE.search(core):
        return "medical"

    return "general"


def is_soap_query(query: str) -> bool:
    """Détecte si l'utilisateur demande une synthèse SOAP (et pas juste une section)."""
    return bool(_SOAP_TRIGGERS.search(query)) and not bool(_SECTION_TRIGGERS.search(query))


def is_cohort_query(query: str, source_filter) -> bool:  # source_filter: str | list | None
    """Détecte une recherche multi-patient (cohorte) — uniquement si aucun patient sélectionné."""
    return not bool(source_filter) and bool(_COHORT_TRIGGERS.search(query))


# ═══════════════════════════════════════════════════════════════════════
# 5. BLOCS DE FORMATAGE RÉUTILISABLES (DRY)
# ═══════════════════════════════════════════════════════════════════════
# Ces constantes contiennent les instructions de formatage envoyées au LLM.
# Centralisées ici → modifiées en UN seul endroit si besoin.
#
# IMPORTANT : ne jamais utiliser le mot "Label" comme placeholder dans les
# exemples — les petits LLM (qwen2.5:1.5b) le copient littéralement.
# Toujours utiliser des noms de champs CONCRETS (Nom, Date, Traitement...).

# ── Instructions de format structuré (mode API : Groq, Mistral, Gemini) ──
_FORMAT_STRUCTURED_API = (
    "FORMAT DE RÉPONSE OBLIGATOIRE :\n"
    "• Commence par un titre en gras, ex: **IDENTITÉ DE JEAN DUPONT**\n"
    "• Chaque information sur sa propre ligne : **Nom du champ** : valeur (cf.[N])\n"
    "• Regroupe par section avec titres en gras : **IDENTITÉ**, **ANTÉCÉDENTS**, "
    "**TRAITEMENTS**, **BIOLOGIE**, **IMAGERIE**, **CONSTANTES**, etc.\n"
    "• INTERDIT d'écrire des phrases continues comme 'Le patient est né le...' "
    "ou 'Sophie LECOMTE est une femme de 32 ans...'\n"
    "• Sépare les sections par une ligne vide\n\n"
    "Exemple de format attendu :\n"
    "**IDENTITÉ DE MARIE DUBOIS**\n"
    "**Nom complet** : Marie DUBOIS (cf.[1])\n"
    "**Date de naissance** : 15/03/1970 (68 ans) (cf.[1])\n"
    "**Sexe** : Féminin (cf.[1])\n"
    "**Adresse** : Rue de Namur 12, 5000 Namur (cf.[1])\n\n"
    "**TRAITEMENTS EN COURS**\n"
    "**Metformine** : 500mg — 2 cp/jour (cf.[3])\n"
    "**Amlodipine** : 5mg — 1 cp/jour (cf.[4])\n"
)

# ── Instructions de format structuré (mode LOCAL : qwen2.5:1.5b) ──
# Plus simple et direct car le modèle local a moins de capacités.
_FORMAT_STRUCTURED_LOCAL = (
    "FORMAT: chaque info sur 1 ligne → **Champ** : valeur [N]\n"
    "Exemple:\n"
    "**Nom complet** : Marie DUBOIS [1]\n"
    "**Date de naissance** : 15/03/1970 [1]\n"
    "**Traitement** : Metformine 500mg 2cp/jour [3]\n"
    "INTERDIT: phrases du type 'Le patient est né le...'\n"
)

# ── Règles médicales communes (DRY — utilisées dans tous les prompts) ──
_MEDICAL_RULES = (
    "• Médicament → **Nom du médicament** : molécule + dosage + posologie + date (cf.[N])\n"
    "• Biologie → **Nom du paramètre** : valeur unité (norme) date — ⚠️ si hors norme (cf.[N])\n"
    "• Diagnostic → **Diagnostic** : intitulé — date (cf.[N])\n"
    "• Imagerie/ECG → **Type d'examen** : date + conclusion (cf.[N])\n"
    "• Constante → **Nom de la constante** : valeur + date — ⚠️ si anormale (cf.[N])\n"
    "• ⚠️ devant toute valeur anormale\n"
)


def _build_header(patient_label: str, n_ext: int, context_block: str, query: str,
                  source_type: str = "dossier") -> str:
    """
    Construit l'en-tête commun de tous les prompts single-patient (API mode).

    Paramètres :
        patient_label  : nom affiché du patient (ex: "Sophie LECOMTE")
        n_ext          : nombre d'extraits dans le contexte
        context_block  : le texte des chunks RAG concaténés
        query          : la question posée par le médecin
        source_type    : "dossier", "note(s)" → affiché dans l'en-tête
    """
    return (
        f"Tu es un assistant médical expert. Un médecin pose une question sur le {source_type} de son patient.\n"
        f"Source : {n_ext} extrait(s) du {source_type} de **{patient_label}**.\n\n"
        f"=== DOSSIER — {patient_label} ({n_ext} extraits) ===\n{context_block}\n\n"
        f"=== QUESTION ===\n{query}\n\n"
    )


def _build_absent_rule(n_ext: int) -> str:
    """Construit la règle pour les données absentes — centralisée (DRY)."""
    return f"• Donnée absente → écrire : **Champ** : Non documenté dans les {n_ext} extraits\n"


def _build_note_priority(has_notes: bool) -> str:
    """Construit la règle de priorité [NOTE] > [PDF] si des notes existent."""
    if not has_notes:
        return ""
    return (
        "\n• Extraits [NOTE] = données saisies récemment par le médecin → "
        "priorité sur [PDF] en cas de contradiction. "
        "Signaler : '⚠️ Mise à jour [NOTE] : ...'."
    )


# ═══════════════════════════════════════════════════════════════════════
# 6. GÉNÉRATION DU PROMPT — Point d'entrée unique
# ═══════════════════════════════════════════════════════════════════════
# Cette fonction est appelée depuis rag_engine.py → _prepare_rag_context().
# Elle détermine le bon template selon 4 axes :
#   1. Patient unique vs Cohorte (multi-patient)
#   2. Note atomique vs PDF
#   3. Question simple vs Synthèse SOAP
#   4. Mode local (qwen2.5) vs Mode API (Groq/Mistral/Gemini)

def generate_system_prompt(
    query: str,
    context_block: str,
    n_ext: int,
    n_pts: int,
    patient_label: str,
    has_notes: bool,
    is_note_patient: bool,
    use_soap: bool,
    is_cohort: bool,
    local_mode: bool,
    known_labels: list[str] = None
) -> str:
    """
    Génère le prompt LLM complet en fonction du contexte.

    Arbre de décision :
    ├── is_cohort=True  → _build_cohort_prompt()    (tableau comparatif)
    └── is_cohort=False → single-patient
        ├── is_note_patient=True → _build_note_prompt()    (notes atomiques)
        ├── use_soap=True        → _build_soap_prompt()    (synthèse SOAP)
        └── else                 → _build_question_prompt() (question directe)

    Chaque sous-fonction gère local_mode en interne.
    """
    note_priority = _build_note_priority(has_notes)
    absent_rule = _build_absent_rule(n_ext)

    if is_cohort:
        prompt = _build_cohort_prompt(
            query, context_block, n_ext, n_pts, local_mode, known_labels
        )
    elif is_note_patient:
        prompt = _build_note_prompt(
            query, context_block, n_ext, patient_label, local_mode,
            note_priority, absent_rule
        )
    elif use_soap:
        prompt = _build_soap_prompt(
            query, context_block, n_ext, patient_label, has_notes,
            local_mode, note_priority, absent_rule
        )
    else:
        prompt = _build_question_prompt(
            query, context_block, n_ext, patient_label, local_mode,
            note_priority, absent_rule
        )

    return _apply_translation_if_needed(prompt, query)


# ═══════════════════════════════════════════════════════════════════════
# 7. BUILDERS DE PROMPTS — Un par cas d'usage
# ═══════════════════════════════════════════════════════════════════════

def _build_note_prompt(query, context_block, n_ext, patient_label,
                       local_mode, note_priority, absent_rule):
    """
    Prompt pour les patients basés sur des NOTES ATOMIQUES (pas de PDF importé).
    Le médecin a saisi des notes directement dans l'application.
    """
    if local_mode:
        return (
            f"Tu es un assistant médical. Voici les notes de {patient_label} :\n\n"
            f"{context_block}\n\n"
            f"QUESTION : {query}\n\n"
            f"RÈGLES ABSOLUES :\n"
            f"1. Réponds UNIQUEMENT à la question posée.\n"
            f"2. Format : **Champ** : valeur [N]\n"
            f"3. Si absent : 'Non documenté dans les notes.'\n"
            f"4. NE RECOPIE PAS l'identité sauf si la question porte dessus.\n\n"
            f"Réponse directe à '{query}' :"
        )

    return (
        f"Tu es un assistant médical expert. Un médecin consulte les notes qu'il a saisies pour son patient.\n"
        f"Source : {n_ext} note(s) [NOTE] pour **{patient_label}**.\n\n"
        f"=== NOTES — {patient_label} ({n_ext} note(s)) ===\n{context_block}\n\n"
        f"=== QUESTION ===\n{query}\n\n"
        f"{_FORMAT_STRUCTURED_API}"
        f"RÈGLES :\n"
        f"{_MEDICAL_RULES}"
        f"{absent_rule}"
        f"• Présente TOUT ce qui est disponible dans les {n_ext} note(s), organisé par catégorie\n"
        f"• ⚠️ devant toute valeur anormale • Cite (cf.[N]) après chaque info\n"
        f"• Termine par : 'ℹ️ Dossier basé uniquement sur {n_ext} note(s) atomique(s). Aucun PDF importé.'\n"
        f"{note_priority}"
        f"Réponds en français."
    )


def _build_soap_prompt(query, context_block, n_ext, patient_label,
                       has_notes, local_mode, note_priority, absent_rule):
    """
    Prompt pour les synthèses SOAP (Subjectif / Objectif / Assessment / Plan).
    Déclenché par des mots comme "synthèse", "résumé", "bilan complet", etc.
    """
    if local_mode:
        return (
            f"Tu es un assistant médical. Voici le dossier de {patient_label} ({n_ext} extraits) :\n\n"
            f"{context_block}\n\n"
            f"Génère une synthèse SOAP complète EN FRANÇAIS :\n"
            f"## S — Subjectif\n## O — Objectif\n## A — Assessment\n## P — Plan\n"
            f"{_FORMAT_STRUCTURED_LOCAL}"
            f"Si section absente : 'Non documenté'. Réponds uniquement en français."
        )

    return (
        f"Tu es un assistant médical expert. Un médecin demande une synthèse clinique complète.\n"
        f"Source : {n_ext} extrait(s) du dossier de **{patient_label}** "
        f"({'dont des notes récentes [NOTE]' if has_notes else 'PDF uniquement'}).\n\n"
        f"=== DOSSIER — {patient_label} ({n_ext} extraits) ===\n{context_block}\n\n"
        f"=== DEMANDE ===\n{query}\n\n"
        f"Génère la synthèse SOAP complète. {_FORMAT_STRUCTURED_API}\n"
        f"## S — Subjectif\n"
        f"Motif(s) • Symptômes rapportés • Antécédents médicaux/chirurgicaux/familiaux (cf.[N]) • "
        f"Allergies : liste exacte ou \"Aucune allergie documentée dans les {n_ext} extraits\" • Mode de vie\n\n"
        f"## O — Objectif\n"
        f"**Constantes** : TA / FC / poids / taille / IMC / SpO2 / T° — valeur + date (⚠️ si anormal) (cf.[N])\n"
        f"**Biologie** : glycémie, HbA1c, créatinine, NFS, ionogramme, troponine, BNP, CRP, PSA, TSH... "
        f"— cherche dans TOUS les extraits même sous 'Examens' — valeur + unité + norme + date (⚠️ si hors norme) (cf.[N])\n"
        f"**Examens** : ECG (rythme, fréquence, anomalies), imagerie (scanner/IRM/radio/écho — date + conclusion), "
        f"spirométrie, bandelette urinaire, glycémie capillaire (cf.[N])\n\n"
        f"## A — Assessment\n"
        f"Diagnostics actifs avec dates d'établissement (cf.[N]) • "
        f"Hospitalisations : motif + durée + évolution (cf.[N])\n\n"
        f"## P — Plan\n"
        f"Médicaments : molécule + dosage + posologie + date prescription (cf.[N]) • "
        f"Actes programmés • Suivi prévu • Recommandations\n\n"
        f"## ⚠️ Points d'attention\n"
        f"Valeurs hors norme • Interactions éventuelles • Changements récents\n\n"
        f"RÈGLES ABSOLUES :\n"
        f"• Cite (cf.[N]) après chaque information — N = numéro de l'extrait\n"
        f"• ⚠️ devant toute valeur anormale (HbA1c>8%, créat>120μmol/L, TA>140/90, etc.)\n"
        f"{absent_rule}"
        f"• Contradiction → garder le plus récent, signaler ⚠️{note_priority}\n"
        f"• Exhaustif : ne résume pas les valeurs numériques\n"
        f"Réponds en français."
    )


def _build_question_prompt(query, context_block, n_ext, patient_label,
                           local_mode, note_priority, absent_rule):
    """
    Prompt pour une question directe sur un patient (le cas le plus fréquent).
    Ex: "identité du patient", "traitements en cours", "dernière biologie", etc.
    """
    if local_mode:
        return (
            f"Tu es un assistant médical. Voici les extraits du dossier de {patient_label} :\n\n"
            f"{context_block}\n\n"
            f"QUESTION : {query}\n\n"
            f"RÈGLES ABSOLUES :\n"
            f"1. Réponds UNIQUEMENT à la question posée — n'affiche pas d'autres informations.\n"
            f"2. Utilise SEULEMENT les informations présentes dans les extraits ci-dessus.\n"
            f"3. Format : **Champ** : valeur [N] (N = numéro de l'extrait source)\n"
            f"4. Si l'information demandée est absente des extraits : écrire 'Non documenté dans les extraits.'\n"
            f"5. NE RECOPIE PAS l'identité du patient sauf si la question porte sur l'identité.\n\n"
            f"Réponse directe à '{query}' :"
        )

    return (
        _build_header(patient_label, n_ext, context_block, query)
        + f"{_FORMAT_STRUCTURED_API}"
        f"RÈGLES :\n"
        f"• Réponds DIRECTEMENT à la question (sans introduction)\n"
        f"• Donne TOUTES les informations pertinentes — sans en omettre\n"
        f"{_MEDICAL_RULES}"
        f"{absent_rule}"
        f"{note_priority}\n"
        f"Réponds en français."
    )


def _build_cohort_prompt(query, context_block, n_ext, n_pts,
                         local_mode, known_labels):
    """
    Prompt pour les recherches multi-patient (cohorte).
    Génère un tableau Markdown comparatif.
    Ex: "Quels patients sont diabétiques ?", "Liste des patients sous anticoagulants"
    """
    if local_mode:
        skeleton = "\n".join(f"| {lbl} | | | | | |" for lbl in (known_labels or []))
        prompt = (
            f"Tu es un assistant médical. Voici les dossiers de {len(known_labels or [])} patients.\n\n"
            f"{context_block}\n\n"
            f"=== QUESTION ===\n{query}\n\n"
            f"Complète le tableau Markdown ci-dessous en extrayant les données "
            f"de chaque bloc [PATIENT: ...] correspondant.\n"
            f"RÈGLE ABSOLUE : copie EXACTEMENT le nom de la colonne Patient — "
            f"ne modifie jamais les noms.\n\n"
            f"| Patient | Âge / Genre | Pathologie / Motif | Traitement utilisé | Évolution / Résultat | Date |\n"
            f"|---------|-------------|-------------------|-------------------|---------------------|------|\n"
            f"{skeleton}\n\n"
            f"Remplace chaque cellule vide par les données du bloc correspondant. "
            f"'Non documenté' si absent.\n"
            f"Dernière ligne : '**Total : {len(known_labels or [])} patient(s) identifié(s) sur {n_pts} dossier(s)**'\n"
            f"Réponds uniquement en français."
        )
        return f"__COHORT_LOCAL__|{'|'.join(known_labels or [])}|__END__\n{prompt}"

    return (
        f"Tu es un assistant médical expert. Un professionnel de santé fait une recherche comparative sur sa patientèle.\n"
        f"Base : {n_ext} extraits de {n_pts} dossier(s). [IDENTITE]=données démographiques, [NOTE]=note médicale récente, [PDF]=document importé.\n\n"
        f"=== EXTRAITS ({n_ext} — {n_pts} patients) ===\n{context_block}\n\n"
        f"=== QUESTION ===\n{query}\n\n"
        f"Génère un tableau comparatif Markdown :\n\n"
        f"| Patient | Âge / Genre | Pathologie / Motif | Traitement utilisé | Évolution / Résultat | Date |\n"
        f"|---------|-------------|-------------------|-------------------|---------------------|------|\n\n"
        f"RÈGLES STRICTES :\n"
        f"• 1 ligne par patient — n'inclure QUE les patients dont un extrait mentionne EXPLICITEMENT le critère\n"
        f"• 'Âge/Genre' : calculer l'âge depuis la date de naissance (extrait [IDENTITE]) ou 'NR' si absent\n"
        f"• 'Pathologie/Motif' : terme exact de l'extrait + date de diagnostic si dispo\n"
        f"• 'Traitement utilisé' : molécule + dosage + durée, ou 'Non documenté'\n"
        f"• 'Évolution/Résultat' : outcome, complications, amélioration observée, ou 'Non documenté'\n"
        f"• 'Date' : date du diagnostic ou de l'acte clinique principal\n"
        f"• Ne pas déduire ni inventer — uniquement ce qui est écrit dans les extraits\n"
        f"• Dernière ligne hors tableau : '**Total : X patient(s) identifié(s) sur {n_pts} dossier(s) analysé(s)**'\n"
        f"• Si aucun patient ne correspond : 'Aucun patient ne présente ce critère dans les {n_ext} extraits ({n_pts} dossiers).'\n"
        f"Réponds en français."
    )


# ═══════════════════════════════════════════════════════════════════════
# 8. TRADUCTION AUTOMATIQUE — Anglais si requête en anglais
# ═══════════════════════════════════════════════════════════════════════

def _apply_translation_if_needed(prompt: str, query: str) -> str:
    """
    Si la requête est en anglais, traduit les mots-clés français du prompt.
    Approche : remplacement ciblé des chaînes connues (pas de traduction LLM).
    """
    if is_english(query):
        prompt = (prompt
            .replace("Tu es un assistant médical expert.", "You are an expert medical AI assistant.")
            .replace("Tu es un assistant médical.", "You are a medical AI assistant.")
            .replace("Tu es un assistant médical", "You are a medical AI assistant")
            .replace("Médecin IA.", "Medical AI.")
            .replace("jamais inventer", "never invent")
            .replace("Un médecin consulte", "A physician is reviewing")
            .replace("Un médecin pose une question", "A physician is asking a question")
            .replace("Un médecin demande une synthèse", "A physician requests a full clinical summary")
            .replace("Un professionnel de santé fait une recherche", "A healthcare professional is searching")
            .replace("Réponds en français :", "Answer in English:")
            .replace("Réponds en français.", "Answer in English.")
            .replace("Réponds en français", "Answer in English")
            .replace("Réponds UNIQUEMENT en FRANÇAIS.", "Answer in English only.")
            .replace("Réponds en FRANÇAIS.", "Answer in English.")
            .replace("Réponds en FRANÇAIS", "Answer in English")
            .replace("N'invente rien.", "Do not invent anything.")
            .replace("**Identité**", "**Identity**")
            .replace("**Antécédents & Allergies**", "**Medical History & Allergies**")
            .replace("**Consultations & Hospitalisations**", "**Consultations & Hospitalizations**")
            .replace("**Traitements en cours**", "**Current Treatments**")
            .replace("**Constantes vitales récentes**", "**Recent Vital Signs**")
            .replace("**Biologie & Examens complémentaires**", "**Lab & Complementary Tests**")
            .replace("**Imagerie & ECG**", "**Imaging & ECG**")
            .replace("**Vaccinations**", "**Vaccinations**")
            .replace("**Diagnostics actifs**", "**Active Diagnoses**")
            .replace("**Points d'attention", "**Key Points")
            .replace("Non documenté dans les sources disponibles", "Not documented in available sources")
            .replace("Non documenté dans les", "Not documented in the")
            .replace("Aucune allergie documentée dans les sources analysées", "No allergy documented in analyzed sources")
            .replace("Aucun traitement documenté dans les sources analysées", "No treatment documented in analyzed sources")
            .replace("=== DEMANDE ===", "=== REQUEST ===")
            .replace("RÈGLE :", "RULE:")
            .replace("RÈGLES TABLEAU :", "TABLE RULES:")
            .replace("PRIORITÉ :", "PRIORITY:")
            .replace("STRUCTURE OBLIGATOIRE", "REQUIRED STRUCTURE")
            .replace("Aucun patient correspondant →", "No matching patient →")
            .replace("Patients correspondants →", "Matching patients →")
        )
        prompt += "\n\nCRITICAL: Your ENTIRE response must be in English. Do not write any French words."
    else:
        prompt += "\n\nIMPORTANT: Réponds INTÉGRALEMENT en FRANÇAIS. N'utilise aucun mot anglais."

    return prompt
