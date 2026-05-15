"""
intent_classifier.py — IntentDetector (anciennement IntentClassifier)
Section 5 : Classification de l'intention utilisateur

Détermine si l'utilisateur veut consulter un planning, créer/modifier/supprimer
un RDV, vérifier des interactions médicamenteuses, interroger un dossier,
ou une intention mixte.

Correspond à «IntentDetector» du diagramme de classes UML (page 1) :
  + detectAction(request: String): ActionType
  + extractPatientId(request: String): String
  + extractDoctorId(request: String): String

NOTE PÉDAGOGIQUE :
  Approche rule-based (regex français) — plus rapide qu'un LLM,
  adaptée à un usage en temps réel dans un cabinet médical.
  Pour un projet de 3e année, les regex suffisent pour les patterns courants.
"""
import logging
import re
from datetime import datetime, timedelta
from typing import Optional, Tuple

from app.core.agent.types import ActionType, IntentType

logger = logging.getLogger(__name__)


class IntentDetector:
    """
    Détecteur d'intention utilisateur.

    Correspond à «IntentDetector» du diagramme UML (package Agent).

    Méthodes publiques (conformes au diagramme) :
      detectAction(request)   → ActionType  (anciennement classify())
      extractPatientId(request) → str       (anciennement detect_patient())
      extractDoctorId(request)  → str       (anciennement detect_doctor())

    Approche : regex français rule-based.
    Avantages : déterministe, rapide, sans appel LLM.
    Limites : ne couvre pas toutes les formulations possibles.
    """

    # ── Mots-clés d'intention (formes conjuguées ET infinitif -er) ────
    # Exemples : "annuler", "annule", "annulé", "annulez" sont tous couverts

    # CREATE : verbes d'ajout
    _CREATE_KEYWORDS = (
        r"\b(cr[eé]er?|r[eé]server?|prendre?|fix[eé]r?|planifier?|ajouter?|bloquer?|programmer?)\b"
    )
    # MODIFY : verbes de changement
    _MODIFY_KEYWORDS = (
        r"\b(modifi[eé]r?|d[eé]cale[rz]?|change[rz]?|reporte[rz]?|repousse[rz]?|d[eé]place[rz]?|d[eé]caler?)\b"
    )
    # DELETE : verbes de suppression
    _DELETE_KEYWORDS = (
        r"\b(supprime[rz]?|annule[rz]?|efface[rz]?|enl[eè]ve[rz]?|retire[rz]?|annul[eé])\b"
    )
    # Nom désignant un rendez-vous
    # Accepte "rendez-vous", "rendez -vous" (espace avant tiret), "rendez vous"
    _APPOINTMENT_NOUN = r"\b(rdv|rendez\s*-?\s*vous|consultation|cr[eé]neau|visite)\b"
    # PLANNING : mots relatifs au calendrier et aux disponibilités
    _PLANNING_KEYWORDS = (
        r"\b(planning|agenda|disponibilit[eé]s?|disponible[s]?|"
        r"cr[eé]neaux?\s+(?:libres?|disponibles?)|cr[eé]neaux?\s+de|"
        r"calendrier|horaires?|emploi\s+du\s+temps|"
        r"quand\s+est[-\s]il\s+disponible|qui\s+est\s+disponible|"
        r"absences?|absent|qui\s+travaille|libre[s]?\s+(?:demain|aujourd|lundi|mardi|mercredi|jeudi|vendredi))\b"
        r"|quels?\s+sont\s+les\s+cr[eé]neaux"
    )
    # QUERY_PATIENT : mots relatifs à un dossier médical
    _QUERY_PATIENT_KEYWORDS = (
        r"\b(dossier|r[eé]sum[eé]|ant[eé]c[eé]dents?|traitements?|biologie|"
        r"consultation[s]?\s+de|diagnostic|pathologie|quel[s]?|quelle[s]?|"
        r"combien|donne-?moi|affiche|montre)\b"
    )
    # CHECK_INTERACTIONS : mots relatifs aux interactions médicamenteuses (nouveau)
    _INTERACTION_KEYWORDS = (
        r"\b(interaction[s]?|contre-?indication[s]?|incompatible[s]?|"
        r"compatible[s]?|association[s]?\s+m[eé]dicamenteuse[s]?|"
        r"v[eé]rifi[eé]r?\s+(?:les?\s+)?m[eé]dicament[s]?|"
        r"ordonnance|prescription|valide[rz]?|v[eé]rifie[rz]?|"
        r"allergi[eé]s?|m[eé]dicament[s]?\s+incompatibles?)\b"
    )

    # Extraction entités
    _DOCTOR_PATTERN = re.compile(
        r"\b(dr|docteur|pr|professeur)\.?\s+([A-ZÉÈÀ][a-zéèàâêîôû-]+)",
        re.IGNORECASE,
    )
    _PATIENT_PATTERN = re.compile(
        r"\b([A-ZÉÈÀ]{2,}(?:\s+[A-ZÉÈÀ][a-zéèàâêîôû-]+)?)\b"
    )
    _DATE_PATTERN = re.compile(
        r"\b(\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|"
        r"\d{1,2}\s+(?:janvier|f[eé]vrier|mars|avril|mai|juin|juillet|ao[uû]t|"
        r"septembre|octobre|novembre|d[eé]cembre)(?:\s+\d{4})?|"
        r"aujourd'hui|demain|apr[eè]s[-\s]demain|"
        r"lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\b",
        re.IGNORECASE,
    )

    _FRENCH_MONTHS: dict = {
        "janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4,
        "mai": 5, "juin": 6, "juillet": 7, "aout": 8, "août": 8,
        "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12, "décembre": 12,
    }
    _TIME_PATTERN = re.compile(r"\b(\d{1,2})\s*h(?:\s*(\d{2}))?\b", re.IGNORECASE)

    # Détection de la période demandée (semaine / mois / jour par défaut)
    _WEEK_PATTERN  = re.compile(r"\b(cette\s+semaine|semaine\s+prochaine|la\s+semaine)\b", re.IGNORECASE)
    _MONTH_PATTERN = re.compile(r"\b(ce\s+mois|mois\s+prochain|le\s+mois)\b", re.IGNORECASE)

    # ── Méthodes publiques du diagramme UML ───────────────────────────

    def detectAction(self, request: str) -> ActionType:
        """
        Détecte l'action demandée dans une requête.

        Méthode principale du diagramme UML : IntentDetector.detectAction().

        Paramètres :
          request : texte de la requête du médecin en français

        Retourne :
          ActionType détecté (CREATE_APPOINTMENT, QUERY_PATIENT, etc.)

        Algorithme :
          1. Détecter les mots-clés par catégorie
          2. Combiner selon des règles de priorité
          3. Si ambiguïté → MIXED
        """
        q = request.lower()

        has_appt          = bool(re.search(self._APPOINTMENT_NOUN, q))
        has_planning      = bool(re.search(self._PLANNING_KEYWORDS, q))
        has_create        = bool(re.search(self._CREATE_KEYWORDS, q))
        has_modify        = bool(re.search(self._MODIFY_KEYWORDS, q))
        has_delete        = bool(re.search(self._DELETE_KEYWORDS, q))
        has_patient_query = bool(re.search(self._QUERY_PATIENT_KEYWORDS, q))
        has_interaction   = bool(re.search(self._INTERACTION_KEYWORDS, q))

        # CHECK_INTERACTIONS : priorité sur les autres si mot-clé d'interaction présent
        if has_interaction:
            return ActionType.CHECK_INTERACTIONS

        # MIXED : plusieurs intentions conflictuelles
        agenda_intents = sum([has_create, has_modify, has_delete])

        # Exception : "créer un RDV avec résumé du patient" → CREATE_APPOINTMENT
        # (le résumé RAG sera injecté automatiquement par l'agent)
        if has_patient_query and has_create and has_appt and not has_modify and not has_delete:
            pass  # Traiter comme CREATE_APPOINTMENT ci-dessous
        elif has_patient_query and (has_create or has_modify or has_delete) and has_appt:
            return ActionType.MIXED

        if agenda_intents >= 2:
            return ActionType.MIXED

        if has_delete and has_appt:
            return ActionType.DELETE_APPOINTMENT
        if has_modify and has_appt:
            return ActionType.MODIFY_APPOINTMENT
        if has_create and has_appt:
            return ActionType.CREATE_APPOINTMENT
        if has_planning:
            return ActionType.CONSULT_PLANNING
        if has_patient_query:
            return ActionType.QUERY_PATIENT

        # Fallback → interroger le dossier patient
        return ActionType.QUERY_PATIENT

    def extractPatientId(self, request: str) -> Optional[str]:
        """
        Extrait l'identifiant (nom) du patient depuis la requête.

        Méthode du diagramme UML : IntentDetector.extractPatientId().

        Paramètres :
          request : texte de la requête du médecin

        Retourne :
          Nom du patient détecté, ou None
        """
        return self.detect_patient(request)

    def extractDoctorId(self, request: str) -> Optional[str]:
        """
        Extrait l'identifiant (nom) du médecin depuis la requête.

        Méthode du diagramme UML : IntentDetector.extractDoctorId().

        Paramètres :
          request : texte de la requête

        Retourne :
          Nom du médecin (ex: "Dr Martin"), ou None
        """
        return self.detect_doctor(request)

    # Alias rétro-compatible (ancien nom utilisé dans medical_agent.py)
    def classify(self, query: str) -> ActionType:
        """Alias de detectAction() — conservé pour la compatibilité."""
        return self.detectAction(query)

    def extract_entities(self, query: str) -> dict:
        """
        Extrait toutes les entités (médecin, patient, date, heure, période) depuis la requête.

        Utilisé par MedicalAgent pour alimenter les paramètres des outils.

        Retourne :
          dict avec clés : doctor, patient, date, time, period
          period : "day" | "week" | "month"
        """
        return {
            "doctor":  self.extractDoctorId(query),
            "patient": self.extractPatientId(query),
            "date":    self.detect_date(query),
            "time":    self.detect_time(query),
            "period":  self.detect_period(query),
        }

    def detect_period(self, query: str) -> str:
        """
        Détecte la période demandée : 'week', 'month', ou 'day' (défaut).

        Utilisé pour la vue d'ensemble semaine/mois (CDC §5.2).
        """
        if re.search(self._MONTH_PATTERN, query):
            return "month"
        if re.search(self._WEEK_PATTERN, query):
            return "week"
        return "day"

    def detect_doctor(self, query: str) -> Optional[str]:
        m = self._DOCTOR_PATTERN.search(query)
        if m:
            return f"Dr {m.group(2).capitalize()}"
        return None

    # ── Patterns de détection du nom patient ──────────────────────────
    # Priorité 1 : "patient X" ou "patiente X"
    _PATIENT_KEYWORD_PATTERN = re.compile(
        r"\bpatients?\s+([A-Za-zÉÈÀéèàâêîôûùÂÊÎÔÛ][a-zA-ZéèàâêîôûùÉÈÀÂÊÎÔÛ-]+"
        r"(?:\s+[a-zA-ZéèàâêîôûùÉÈÀÂÊÎÔÛ][a-zéèàâêîôûù-]+)?)",
        re.IGNORECASE,
    )
    # Priorité 2 : "pour X avec Y" → X est le patient
    _PATIENT_POUR_AVEC_PATTERN = re.compile(
        r"\bpour\s+(?:le\s+patient\s+|la\s+patiente\s+)?(.+?)\s+avec\b",
        re.IGNORECASE,
    )
    # Priorité 3 : "pour X" avec majuscule initiale
    _PATIENT_POUR_PATTERN = re.compile(
        r"\bpour\s+([A-ZÉÈÀ][a-zA-ZéèàâêîôûùÉÈÀÂÊÎÔÛ-]+"
        r"(?:\s+[a-zA-ZéèàâêîôûùÉÈÀÂÊÎÔÛ][a-zéèàâêîôûù-]+)?)"
    )
    # Priorité 4 : mots capitalisés en fin de requête
    # Couvre "Dossier de Martine Durand", "résumé de Frédéric Aubert"
    _PATIENT_DE_PATTERN = re.compile(
        r"\bde\s+([A-Za-zÉÈÀéèàâêîôûù][a-zA-ZéèàâêîôûùÉÈÀÂÊÎÔÛ-]+"
        r"(?:\s+[A-Za-zÉÈÀéèàâêîôûù][a-zA-ZéèàâêîôûùÉÈÀÂÊÎÔÛ-]+)?)\s*$",
        re.IGNORECASE,
    )

    # Mots exclus de la détection patient (articles, titres, etc.)
    _EXCLUDE_PATIENT_WORDS = frozenset([
        "le", "la", "les", "un", "une", "dr", "pr", "docteur",
        "ce", "son", "sa", "ses", "mon", "son",
    ])

    def detect_patient(self, query: str) -> Optional[str]:
        """
        Détecte le nom du patient dans la requête (en français).

        Ordre de priorité — du plus explicite au moins explicite :
          1. "patient Martine Durand"        → "Martine Durand"
          2. "pour Sophie Martin avec Dr X"  → "Sophie Martin"
          3. "pour DUPONT Jean"              → "DUPONT Jean"
          4. "Dossier de Martine Durand"     → "Martine Durand"  (fin de phrase)
          5. "DUPONT Jean" (tout caps)       → "DUPONT Jean"

        Le .title() normalise la casse : "sophie martin" → "Sophie Martin"
        """
        # Priorité 1 : "patient X" ou "patiente X"
        m = self._PATIENT_KEYWORD_PATTERN.search(query)
        if m:
            return m.group(1).strip().title()

        # Priorité 2 : "pour X avec Y" → X est le patient (entre "pour" et "avec")
        m = self._PATIENT_POUR_AVEC_PATTERN.search(query)
        if m:
            candidate = m.group(1).strip()
            if candidate.lower().split()[0] not in self._EXCLUDE_PATIENT_WORDS:
                return candidate.title()

        # Priorité 3 : "pour X" avec majuscule initiale
        m = self._PATIENT_POUR_PATTERN.search(query)
        if m:
            candidate = m.group(1).strip()
            if candidate.lower().split()[0] not in self._EXCLUDE_PATIENT_WORDS:
                return candidate

        # Priorité 4 : "dossier de X" / "résumé de X" → X en fin de requête
        # Couvre "Dossier de Martine Durand", "résumé de Frédéric Aubert"
        m = self._PATIENT_DE_PATTERN.search(query)
        if m:
            candidate = m.group(1).strip()
            if candidate.lower().split()[0] not in self._EXCLUDE_PATIENT_WORDS:
                return candidate.title()

        # Priorité 5 : mot(s) tout en MAJUSCULES (ex : "DUPONT Jean")
        for m in self._PATIENT_PATTERN.finditer(query):
            name = m.group(1)
            if name.lower() not in ("dr", "pr", "rdv"):
                return name

        return None

    def detect_date(self, query: str) -> Optional[datetime]:
        m = self._DATE_PATTERN.search(query.lower())
        if not m:
            return None
        token = m.group(1).lower()
        now = datetime.utcnow().replace(hour=9, minute=0, second=0, microsecond=0)

        if token == "aujourd'hui":
            return now
        if token == "demain":
            return now + timedelta(days=1)
        if "apr" in token and "demain" in token:
            return now + timedelta(days=2)

        weekdays = {
            "lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3,
            "vendredi": 4, "samedi": 5, "dimanche": 6,
        }
        if token in weekdays:
            target = weekdays[token]
            delta = (target - now.weekday()) % 7 or 7
            return now + timedelta(days=delta)

        # format "18 avril 2026" (mois en lettres)
        french_m = re.match(
            r"(\d{1,2})\s+([a-zéèûô]+)(?:\s+(\d{4}))?", token
        )
        if french_m:
            month_name = french_m.group(2).lower()
            month = self._FRENCH_MONTHS.get(month_name)
            if month:
                day = int(french_m.group(1))
                year = int(french_m.group(3)) if french_m.group(3) else now.year
                try:
                    return datetime(year, month, day, 9, 0)
                except ValueError:
                    pass

        # format numérique DD/MM ou DD/MM/YYYY
        try:
            parts = re.split(r"[/-]", token)
            day = int(parts[0])
            month = int(parts[1])
            year = int(parts[2]) if len(parts) > 2 else now.year
            if year < 100:
                year += 2000
            return datetime(year, month, day, 9, 0)
        except (ValueError, IndexError):
            return None

    def detect_time(self, query: str) -> Optional[Tuple[int, int]]:
        m = self._TIME_PATTERN.search(query)
        if m:
            hour = int(m.group(1))
            minute = int(m.group(2)) if m.group(2) else 0
            return (hour, minute)
        return None


# ── Alias rétro-compatible ────────────────────────────────────────────
# L'ancien code utilise IntentClassifier. On crée un alias pour éviter
# de casser les imports existants tout en respectant le nouveau nom UML.
IntentClassifier = IntentDetector
