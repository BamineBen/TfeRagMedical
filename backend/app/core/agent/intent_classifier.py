intent_classifier.py — Détection d'intention par regex.

IntentDetector analyse le texte libre du médecin et retourne :
- L'action voulue (ActionType)
- Les entités extraites (patient, médecin, date)

Exemple :
    "Créer RDV Dr Martin demain 14h pour DUPONT Jean"
    → ActionType.CREATE_APPOINTMENT
    → entities = {"doctor": "Dr Martin", "patient": "DUPONT Jean", "date": "demain 14h"}

   Utilisation du regex raison :  Fiabilité et rapidité. Le médecin peut écrire "rdv dupont demain" ou "créer rendez-vous pour dupont" 
   , les regex capturent les deux. Le LLM pourrait halluciner au niveau de l'intention.

import re
from datetime import datetime, timedelta
from typing import Dict, Optional

from app.core.agent.types import ActionType


class IntentDetector:
    """
    Détecte l'intention d'une requête médicale.
    
    Utilise des regex (expressions régulières) pour chercher des mots-clés.
    \b = limite de mot (word boundary). Ex: \bcréer\b match "créer" mais pas "recrée".
    """

    #  Patterns par ActionType : (test pattern : actuel)
    _CREATE = re.compile(
        r'\b(cr[ée]er?|réserver?|planifier?|prendre|fixer|ajouter|programmer?)\b',
        re.IGNORECASE | re.UNICODE
    )
    _DELETE = re.compile(
        r'\b(annuler?|supprimer?|effacer?|enlever?|retirer?)\b',
        re.IGNORECASE | re.UNICODE
    )
    _MODIFY = re.compile(
        r'\b(modifier?|changer?|déplacer?|reporter?|reprogrammer?|mettre à jour)\b',
        re.IGNORECASE | re.UNICODE
    )
    _RDV = re.compile(
        r'\b(rdv|rendez.vous|consultation|appointment)\b',
        re.IGNORECASE | re.UNICODE
    )
    _PLANNING = re.compile(
        r'\b(planning|agenda|disponibilit[eé]s?|cr[eé]neaux?|horaires?|calendrier)\b',
        re.IGNORECASE | re.UNICODE
    )
    _INTERACTION = re.compile(
        r'\b(interaction|incompatible|contre.indication|allergi|m[eé]dicaments?)\b',
        re.IGNORECASE | re.UNICODE
    )

    #  Patterns d'extraction d'entités : (test regex : actuel)
    _DOCTOR = re.compile(
        r'\b(dr\.?|docteur)\s+([A-ZÉÈÀÙÂÊÎÔÛa-zéèàùâêîôû][a-zéèàùâêîôû\-]+)',
        re.IGNORECASE
    )
    _PATIENT = re.compile(
        r'\b(patient|pour|dossier)\s+([A-ZÉÈÀÙ][A-ZÉÈÀÙ\s\-]+?)(?:\s+avec|\s+demain|\s+à|\s*$)',
        re.IGNORECASE
    )
    _TIME = re.compile(
        r'\b(\d{1,2}[h:]\d{0,2}|\d{1,2}\s*heures?)\b',
        re.IGNORECASE
    )
    _DATE_REL = re.compile(
        r'\b(demain|après.demain|lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\b',
        re.IGNORECASE
    )

    def detectAction(self, request: str) -> ActionType:
        """
        Retourne l'ActionType correspondant à la requête.
        
        Algorithme : cherche les mots-clés dans cet ordre de priorité :
        1. Interactions médicamenteuses
        2. Suppression de RDV
        3. Modification de RDV
        4. Création de RDV
        5. Consultation planning
        6. Fallback : requête patient RAG
        """
        q = request.lower()

        if self._INTERACTION.search(q):
            return ActionType.CHECK_INTERACTIONS

        has_rdv  = bool(self._RDV.search(q))
        has_del  = bool(self._DELETE.search(q))
        has_mod  = bool(self._MODIFY.search(q))
        has_cre  = bool(self._CREATE.search(q))
        has_plan = bool(self._PLANNING.search(q))

        if has_del and has_rdv:
            return ActionType.DELETE_APPOINTMENT
        if has_mod and has_rdv:
            return ActionType.MODIFY_APPOINTMENT
        if has_cre and has_rdv:
            return ActionType.CREATE_APPOINTMENT
        if has_plan or (has_rdv and not has_cre and not has_del):
            return ActionType.CONSULT_PLANNING

        return ActionType.QUERY_PATIENT

    def extractPatientId(self, request: str) -> Optional[str]:
        """
        Extrait le nom du patient.
        Ex: "patient DUPONT Jean" → "DUPONT Jean"
        Ex: "pour MARTIN Sophie" → "MARTIN Sophie"
        """
        m = self._PATIENT.search(request)
        if m:
            return m.group(2).strip()
        return None

    def extractDoctorId(self, request: str) -> Optional[str]:
        """
        Extrait le nom du médecin.
        Ex: "Dr Martin" → "Dr Martin"
        Ex: "docteur Dupont" → "Dr Dupont"
        """
        m = self._DOCTOR.search(request)
        if m:
            return f"Dr {m.group(2).capitalize()}"
        return None

    def extract_entities(self, request: str) -> Dict[str, Optional[str]]:
        """
        Extrait toutes les entités d'une requête en une seule passe.
        Retourne un dict : {"doctor": ..., "patient": ..., "date": ..., "time": ...}
        """
        date_str = None
        m_date = self._DATE_REL.search(request)
        if m_date:
            date_str = m_date.group(0)

        time_str = None
        m_time = self._TIME.search(request)
        if m_time:
            time_str = m_time.group(0)

        return {
            "doctor":  self.extractDoctorId(request),
            "patient": self.extractPatientId(request),
            "date":    date_str,
            "time":    time_str,
        }

    def resolve_datetime(self, date_str: Optional[str], time_str: Optional[str]) -> Optional[datetime]:
        """
        Convertit une date relative + heure en datetime.
        Ex: "demain", "14h" → datetime(aujourd'hui+1, 14, 0)
        """
        now = datetime.now()
        base = now

        if date_str:
            ds = date_str.lower()
            if "demain" in ds:
                base = now + timedelta(days=1)
            elif "après-demain" in ds or "apres-demain" in ds:
                base = now + timedelta(days=2)
            else:
                jours = {"lundi":0,"mardi":1,"mercredi":2,"jeudi":3,"vendredi":4,"samedi":5,"dimanche":6}
                for jour, n in jours.items():
                    if jour in ds:
                        diff = (n - now.weekday()) % 7 or 7
                        base = now + timedelta(days=diff)
                        break

        if time_str:
            m = re.search(r'(\d{1,2})[h:](\d{0,2})', time_str, re.IGNORECASE)
            if m:
                h = int(m.group(1))
                mi = int(m.group(2)) if m.group(2) else 0
                return base.replace(hour=h, minute=mi, second=0, microsecond=0)

        return base.replace(hour=9, minute=0, second=0, microsecond=0)