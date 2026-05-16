"""
medical_agent.py — MedicalAgent (Singleton)
Section 5 : Agent Médical Autonome Multi-Outils.

Classe MedicalAgent (Singleton) :
  Attributs :
    ragEngine          : RAGEngine (existant, via RAGQueryTool)
    calendarManager    : CalendarManager (nouveau)
    interactionChecker : InteractionChecker (nouveau)
    intentDetector     : IntentDetector (anciennement IntentClassifier)
    config             : AgentConfig (nouveau)
    + processRequest(request: String): AgentResponse
    + dispatch(action: ActionType, request: String): AgentResponse
    + run(query, session_id)     → AsyncGenerator SSE
    + plan(query, intent)        → List de steps
    + execute_step(tool, params) → ToolResult
    + confirm(session_id, ok)    → ToolResult
"""
import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import AsyncGenerator, Dict, List, Optional

from app.core.agent.calendar_manager import CalendarManager
from app.core.agent.interaction_checker import InteractionChecker
from app.core.agent.intent_classifier import IntentDetector
from app.core.agent.models import (
    AgentConfig, AgentResponse, Appointment, PatientInfo, Prescription, ToolResult
)
from app.core.agent.tools import (
    AgentTool, CalendarReadTool, CalendarWriteTool,
    InteractionCheckTool, RAGQueryTool,
)
from app.core.agent.types import ActionType, AgentEventType, Status

logger = logging.getLogger(__name__)

class MedicalAgent:
    """
    Agent médical autonome — Singleton.

    PATTERN SINGLETON :
      Une seule instance est créée pour toute l'application.
      Cela évite de recharger les modèles et connexions à chaque requête.

    RESPONSABILITÉS :
      1. Détecter l'intention du médecin (intentDetector)
      2. Planifier les étapes d'exécution (plan)
      3. Exécuter chaque outil dans l'ordre (execute_step)
      4. Gérer les confirmations avant écriture (confirm)
      5. Émettre les événements en streaming SSE (run)
      ragEngine          : accès aux dossiers patients via RAGQueryTool
      calendarManager    : gestion des rendez-vous (CRUD)
      interactionChecker : vérification des interactions médicamenteuses
      intentDetector     : classification de l'intention utilisateur
      config             : configuration de l'agent
    """

    _instance: Optional["MedicalAgent"] = None

    def __new__(cls, *args, **kwargs):
        """Garantit l'unicité de l'instance (pattern Singleton)."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialise l'agent une seule fois (garde porte du Singleton)."""
        if self._initialized:
            return
        # intentDetector : détecte l'action dans la requête du médecin
        self.intentDetector = IntentDetector()

        # calendarManager : couche métier pour les rendez-vous
        self.calendarManager = CalendarManager()

        # interactionChecker : vérifie les interactions médicamenteuses
        self.interactionChecker = InteractionChecker()

        # config : paramètres de l'agent
        self.config = AgentConfig(language="fr", timeout=120, privacy_mode=False)

        # ── Outils du pipeline SSE (détail d'implémentation) ──────────
        self.tools: Dict[str, AgentTool] = {
            "rag_query":        RAGQueryTool(),
            "calendar_read":    CalendarReadTool(),
            "calendar_write":   CalendarWriteTool(),
            "interaction_check": InteractionCheckTool(),
        }

        # Historique des événements par session_id
        self._history: Dict[str, List[dict]] = {}

        # Steps en attente de confirmation : session_id → step dict
        self._pending: Dict[str, dict] = {}

        self._initialized = True
        logger.info("[MedicalAgent] Singleton initialisé — %d tools | config: %s",
                    len(self.tools), self.config)

    # ══════════════════════════════════════════════════════════════════
    # MÉTHODES DU DIAGRAMME UML
    # ══════════════════════════════════════════════════════════════════

    def processRequest(self, request: str) -> AgentResponse:
        """
        Point d'entrée principal pour une requête non-streaming.

        Logique :
          1. Détecter l'action → intentDetector.detectAction()
          2. Router vers le bon handler → dispatch()
          3. Retourner un AgentResponse

        Paramètres :
          request : texte libre du médecin (ex: "Vérifier warfarine + aspirine")

        Retourne :
          AgentResponse avec message, success, sources, status
        """
        logger.info("[MedicalAgent] processRequest : %s", request[:80])
        action = self.intentDetector.detectAction(request)
        return self.dispatch(action, request)

    def dispatch(self, action: ActionType, request: str) -> AgentResponse:
        """
        Route la requête vers le bon handler selon l'ActionType.

        Paramètres :
          action  : type d'action détecté par intentDetector
          request : texte de la requête (pour extraction d'entités)

        Retourne :
          AgentResponse avec le résultat de l'action
        """
        entities = self.intentDetector.extract_entities(request)
        doctor   = entities.get("doctor") or "Dr Martin"
        patient  = entities.get("patient") or ""
        date_dt  = entities.get("date") or datetime.utcnow()
        time_s   = entities.get("time")

        # Construire le datetime de début
        start_dt = date_dt.replace(second=0, microsecond=0)
        if time_s:
            h, m = time_s
            start_dt = start_dt.replace(hour=h, minute=m)
        end_dt = start_dt + timedelta(minutes=30)

        try:
            # ── CHECK_INTERACTIONS : vérifier les interactions ──────────
            if action == ActionType.CHECK_INTERACTIONS:
                # Extraire les médicaments depuis la requête (liste après virgule)
                meds = self._extract_medications(request)
                prescription = Prescription(
                    patient_id=patient,
                    medications=meds,
                )
                patient_info = PatientInfo(patient_id=patient or "", name=patient or "", allergies=[])
                result = self.interactionChecker.validatePrescription(patient_info, prescription)
                msg = result.description
                if result.recommendations:
                    msg += "\n\nRecommandations :\n" + "\n".join(
                        f"• {r}" for r in result.recommendations
                    )
                return AgentResponse(
                    message=msg,
                    success=True,
                    sources=[],
                    status=Status.COMPLETED,
                )

            # ── CONSULT_PLANNING : afficher le planning ─────────────────
            elif action == ActionType.CONSULT_PLANNING:
                events = self.calendarManager.getDoctorSchedule(doctor, date_dt)
                slots  = self.calendarManager.findAvailableSlots(doctor, date_dt, duration=30)
                msg = (
                    f"Planning de {doctor} pour le {date_dt.strftime('%d/%m/%Y')} :\n"
                    f"• {len(events)} rendez-vous planifié(s)\n"
                    f"• {len(slots)} créneau(x) libre(s)\n"
                )
                if slots:
                    msg += "\nCréneaux disponibles : " + ", ".join(
                        s.start.strftime("%H:%M") for s in slots[:5]
                    )
                return AgentResponse(message=msg, success=True, status=Status.COMPLETED)

            # ── CREATE_APPOINTMENT ──────────────────────────────────────
            elif action == ActionType.CREATE_APPOINTMENT:
                appt = Appointment(
                    id=str(uuid.uuid4()),
                    patient_id=patient,
                    doctor_id=doctor,
                    start_time=start_dt,
                    end_time=end_dt,
                    title=f"Consultation {patient or 'patient'}",
                )
                appt_result = self.calendarManager.createAppointment(appt)
                return AgentResponse(
                    message=appt_result.message,
                    success=appt_result.success,
                    status=appt_result.status,
                )

            # ── QUERY_PATIENT / MIXED / fallback ────────────────────────
            else:
                return AgentResponse(
                    message=f"Requête «{action.value}» reçue. Utilisez /agent/stream pour le mode SSE complet.",
                    success=True,
                    status=Status.COMPLETED,
                )

        except Exception as exc:
            logger.exception("[MedicalAgent] dispatch error : %s", exc)
            return AgentResponse(
                message=f"Erreur interne : {exc}",
                success=False,
                status=Status.FAILED,
            )

    def plan(self, query: str, intent: ActionType) -> List[dict]:
        """
        Transforme une intention en liste de steps (dict).
        Chaque step : {order, tool_name, params, requires_confirmation, status, label}
        """
        entities  = self.intentDetector.extract_entities(query)
        patient   = entities.get("patient")
        doctor    = entities.get("doctor") or "Dr Martin"
        date      = entities.get("date") or datetime.utcnow()
        time_slot = entities.get("time")
        period    = entities.get("period", "day")

        # Construire le datetime de début
        start = date.replace(second=0, microsecond=0)
        if time_slot:
            h, m = time_slot
            start = start.replace(hour=h, minute=m)
        end_appt  = start + timedelta(minutes=30)

        # Plage calendrier selon la période (CDC §5.2 : semaine / mois / jour)
        if period == "month":
            range_end = start + timedelta(days=30)
        elif period == "week":
            range_end = start + timedelta(days=7)
        else:
            range_end = start.replace(hour=18, minute=0, second=0)

        steps: List[dict] = []

        if intent == ActionType.CONSULT_PLANNING:
            steps.append(_step(1, "calendar_read", {
                "doctor_name":      doctor,
                "start":            start.isoformat(),
                "end":              range_end.isoformat(),
                "duration_minutes": 30,
            }, label="Consultation du calendrier…"))

        elif intent == ActionType.CREATE_APPOINTMENT:
            order = 1

            # Étape 1 (si patient connu) : résumé RAG → injecté dans la description
            if patient:
                steps.append(_step(order, "rag_query", {
                    "patient_name": patient,
                    "query":        f"résumé médical complet {patient}",
                }, label="Lecture du dossier patient…"))
                order += 1

            # Vérifier disponibilités
            steps.append(_step(order, "calendar_read", {
                "doctor_name":      doctor,
                "start":            start.isoformat(),
                "end":              range_end.isoformat(),
                "duration_minutes": 30,
            }, label="Vérification des disponibilités…"))
            order += 1

            # Créer l'événement (NÉCESSITE CONFIRMATION — CDC §5.3)
            steps.append(_step(order, "calendar_write", {
                "action": "create",
                "event": {
                    "title":        f"Consultation {patient or 'patient'}",
                    "doctor_name":  doctor,
                    "patient_name": patient or "",
                    "start":        start.isoformat(),
                    "end":          end_appt.isoformat(),
                    "description":  query,
                },
            }, requires_confirmation=True, label="Création du rendez-vous…"))

        elif intent == ActionType.MODIFY_APPOINTMENT:
            day_start = date.replace(hour=8,  minute=0, second=0, microsecond=0)
            day_end   = date.replace(hour=18, minute=0, second=0, microsecond=0)
            steps.append(_step(1, "calendar_read", {
                "doctor_name":      doctor,
                "start":            day_start.isoformat(),
                "end":              day_end.isoformat(),
                "duration_minutes": 30,
            }, label="Recherche du rendez-vous…"))
            steps.append(_step(2, "calendar_write", {
                "action":    "update",
                "event_id":  "",
                "event": {
                    "title":        f"Consultation {patient or 'patient'} (modifiée)",
                    "doctor_name":  doctor,
                    "patient_name": patient or "",
                    "start":        start.isoformat(),
                    "end":          end_appt.isoformat(),
                    "description":  query,
                },
            }, requires_confirmation=True, label="Modification du rendez-vous…"))

        elif intent == ActionType.DELETE_APPOINTMENT:
            day_start = date.replace(hour=8,  minute=0, second=0, microsecond=0)
            day_end   = date.replace(hour=18, minute=0, second=0, microsecond=0)
            steps.append(_step(1, "calendar_read", {
                "doctor_name":      doctor,
                "start":            day_start.isoformat(),
                "end":              day_end.isoformat(),
                "duration_minutes": 30,
            }, label="Recherche du rendez-vous…"))
            steps.append(_step(2, "calendar_write", {
                "action":   "delete",
                "event_id": "",
            }, requires_confirmation=True, label="Suppression du rendez-vous…"))

        elif intent == ActionType.CHECK_INTERACTIONS:
            medications = self._extract_medications(query)
            steps.append(_step(1, "interaction_check", {
                "patient_id":  patient or "",
                "medications": medications,
            }, label="Vérification des interactions médicamenteuses…"))

        else:  # QUERY_PATIENT + MIXED + fallback
            steps.append(_step(1, "rag_query", {
                "patient_name": patient or "",
                "query":        query,
            }, label="Interrogation du dossier patient…"))

        return steps

    # ── Message de réponse lisible (CDC §5.4) ─────────────────────────
    @staticmethod
    def _build_answer_message(
        intent: ActionType, results: dict, entities: dict
    ) -> str:
        """
        Génère une phrase de résumé en français visible dans la carte ANSWER.
                """
        doctor  = entities.get("doctor") or "le médecin"
        patient = entities.get("patient") or "le patient"

        if intent == ActionType.CONSULT_PLANNING:
            cal     = results.get("calendar_read", {})
            n_rdv   = len(cal.get("events", []))
            n_libre = len(cal.get("free_slots", []))
            return (
                f"Planning de {doctor} : {n_rdv} rendez-vous planifié(s), "
                f"{n_libre} créneau(x) libre(s)."
            )

        if intent == ActionType.CREATE_APPOINTMENT:
            w = results.get("calendar_write", {})
            if w.get("created"):
                start_iso = w.get("start", "")
                date_str = start_iso[:10] if start_iso else ""
                return f"Rendez-vous créé : {w.get('title', '')} le {date_str}."
            return "Rendez-vous en attente de confirmation."

        if intent == ActionType.MODIFY_APPOINTMENT:
            w = results.get("calendar_write", {})
            return "Rendez-vous modifié." if w.get("updated") else "Modification en attente de confirmation."

        if intent == ActionType.DELETE_APPOINTMENT:
            w = results.get("calendar_write", {})
            return "Rendez-vous supprimé." if w.get("deleted") else "Suppression en attente de confirmation."

        if intent == ActionType.QUERY_PATIENT:
            r = results.get("rag_query", {})
            if r.get("patient_found") is False:
                return f"Patient {patient} introuvable dans la base médicale."
            return f"Résumé du dossier de {patient} généré avec succès."

        if intent == ActionType.CHECK_INTERACTIONS:
            i = results.get("interaction_check", {})
            sev = i.get("severity", "LOW")
            if i.get("has_interaction"):
                return f"⚠ Interaction détectée (sévérité {sev}) — consultez les recommandations."
            return "Aucune interaction médicamenteuse connue entre ces médicaments."

        return "Analyse terminée."

    # ── Méthode utilitaire : lien RDV sécurisé ────────────────────────
    @staticmethod
    def _generate_rdv_link(patient_name: str, doctor_name: str,
                           start_iso: str, user_id: Optional[int] = None) -> str:
        """
        Génère une URL sécurisée (JWT signé) pour consulter le dossier d'un RDV.

        Au lieu de mettre les données médicales dans Google Calendar (où Google y a
        accès), on génère un lien unique et signé. Le médecin clique → s'authentifie
        sur notre serveur → voit le résumé RAG. Google ne voit que l'URL, pas le contenu.

        Le token JWT contient :
          - patient  : nom du patient
          - doctor   : nom du médecin
          - date     : date du RDV (YYYY-MM-DD)
          - exp      : expiration 30 jours

        Paramètres :
          patient_name : nom du patient
          doctor_name  : nom du médecin
          start_iso    : datetime ISO de début du RDV
          user_id      : ID de l'utilisateur (pour restreindre l'accès)

        Retourne :
          URL complète, ex: https://medrag.duckdns.org/rdv?token=eyJ...
        """
        import os
        try:
            from jose import jwt as jose_jwt
            secret   = os.getenv("SECRET_KEY", "medrag-secret-key")
            base_url = os.getenv("APP_BASE_URL", "https://medrag.duckdns.org")
            payload  = {
                "type":    "rdv",
                "patient": patient_name,
                "doctor":  doctor_name,
                "date":    start_iso[:10] if start_iso else "",
                "uid":     user_id,
                "exp":     int((datetime.utcnow() + timedelta(days=30)).timestamp()),
            }
            token = jose_jwt.encode(payload, secret, algorithm="HS256")
            return f"{base_url}/rdv?token={token}"
        except Exception as e:
            logger.warning("[MedicalAgent] Génération du lien RDV échouée : %s", e)
            return "https://medrag.duckdns.org/rdv"

    # ── Méthode utilitaire : validation du résumé RAG ────────────────
    @staticmethod
    def _is_valid_medical_summary(answer: str, patient_name: str) -> bool:
        """
        Vérifie qu'une réponse RAG est un vrai résumé médical.

        On rejette les réponses qui :
          - Expriment une confusion ("Il semble y avoir une confusion...")
          - Disent que le patient n'est pas trouvé
          - Sont des messages d'erreur du LLM

        On accepte seulement les réponses qui semblent contenir
        des informations médicales réelles.

        Paramètres :
          answer       : texte retourné par le LLM via RAGQueryTool
          patient_name : nom du patient attendu

        Retourne :
          True si la réponse est exploitable comme description de RDV
        """
        if not answer or len(answer.strip()) < 30:
            return False

        answer_lower = answer.lower()

        # Mots-clés qui indiquent une confusion ou un message d'erreur du LLM
        confusion_signals = [
            "il semble y avoir une confusion",
            "je ne peux pas",
            "je n'ai pas",
            "je n'ai aucune",
            "je ne trouve pas",
            "aucune information",
            "données insuffisantes",
            "pourriez-vous vérifier",
            "pourriez-vous fournir",
            "merci de votre compréhension",
            "données médicales spécifiques",
            "informations pour le patient",
            "mais vous demandez",
            "confusion dans votre demande",
        ]
        for signal in confusion_signals:
            if signal in answer_lower:
                return False

        # Vérification optionnelle : le nom du patient doit apparaître
        # (si le nom est connu et d'au moins 3 lettres)
        if patient_name and len(patient_name) >= 3:
            # Vérifier que le nom du patient apparaît dans le TITRE du résumé
            # (la première ligne, ex: "RÉSUMÉ MÉDICAL – MARTINE DURAND")
            # plutôt que n'importe où dans le texte.
            # Cela évite les faux positifs quand "Sophie" apparaît comme
            # nom de médecin (Dr Sophie MARTIN) dans un autre patient's résumé.
            first_line = answer.split('\n')[0].lower() if answer else ""
            first_word = patient_name.split()[0].lower()

            if len(first_word) >= 4 and first_word not in first_line:
                return False

        return True

    # ── Méthode utilitaire : patients similaires ─────────────────────
    def _find_similar_patients(self, patient_name: str) -> List[str]:
        """
        Cherche les noms de patients similaires dans les fichiers médicaux.

        Parcourt le dossier medical_docs/ et retourne les noms de fichiers
        qui partagent le même nom de famille ou prénom que le patient cherché.

        Paramètres :
          patient_name : "DUPONT Jean", "Martine Durand", etc.

        Retourne :
          Liste de noms formatés (ex: ["DUPONT Thomas", "GARCIA Jeanne"])
        """
        import os, re as _re
        similar: List[str] = []
        if not patient_name:
            return similar

        # Chercher le dossier medical_docs (plusieurs emplacements possibles)
        possible_dirs = [
            "/app/data/medical_docs",
            "/opt/rag-medical/backend/data/medical_docs",
            "data/medical_docs",
            "medical_docs",
        ]
        docs_dir = next((d for d in possible_dirs if os.path.isdir(d)), None)
        if not docs_dir:
            return similar

        # Mots du nom cherché (ex: ["dupont","jean"])
        search_words = {w.lower() for w in patient_name.split() if len(w) >= 3}

        try:
            for filename in os.listdir(docs_dir):
                if not (filename.endswith(".pdf") or filename.endswith(".txt")):
                    continue
                # Format : P00115_DUPONT_Thomas.pdf → ["DUPONT","Thomas"]
                parts = filename.replace(".pdf","").replace(".txt","").split("_")[1:]
                file_words = {p.lower() for p in parts if len(p) >= 3}

                # Si au moins 1 mot en commun → patient similaire
                if search_words & file_words:
                    # Reformater en "NOM Prénom"
                    pretty = " ".join(parts)
                    similar.append(pretty)

            # Trier par pertinence (plus de mots en commun en premier)
            similar.sort(
                key=lambda n: len({w.lower() for w in n.split()} & search_words),
                reverse=True
            )
        except Exception:
            pass

        return similar[:5]

    # ── Méthode utilitaire : extraction des médicaments ───────────────
    def _extract_medications(self, query: str) -> List[str]:
        """
        Extrait les noms de médicaments depuis une requête médicale.

        Stratégie :
          1. Chercher les mots après des mots-clés d'introduction
             ("entre X et Y", "warfarine + aspirine", etc.)
          2. Exclure les mots de la liste de stop-words étendue

        Paramètres :
          query : texte de la requête

        Retourne :
          Liste de noms de médicaments trouvés (peut être vide)

        Exemples :
          "interactions entre warfarine et aspirine" → ["warfarine", "aspirine"]
          "prescrire warfarine 5mg" → ["warfarine"]
        """
        import re
        # Mots à exclure — non-médicaments courants dans les requêtes médicales
        stop_words = {
            # Verbes d'action
            "verifier", "vérifier", "vérification", "valider", "prescrire",
            "associer", "check", "contrôler", "analyser",
            # Noms communs médicaux (non-médicaments)
            "interactions", "interaction", "ordonnance", "prescription",
            "médicaments", "médicament", "allergie", "allergies",
            "incompatible", "compatible", "association",
            # Prépositions et articles
            "entre", "avec", "pour", "sans", "après", "avant",
            "dans", "lors", "sous", "faire",
            "et", "ou", "mais", "donc", "car",
            "le", "la", "les", "un", "une", "des",
            "du", "de", "cette", "ces", "mon", "son", "leur",
            # Mots contextuels
            "patient", "patients", "contre", "indication",
            "traitement", "dossier", "résumé", "médecin",
            "docteur", "consultation",
        }
        # Chercher les mots après des marqueurs ("entre X et Y", "X + Y", "X, Y")
        # 1. Pattern "entre X et Y"
        between_match = re.findall(
            r"entre\s+([a-zéèàâêîôûùä]+)\s+et\s+([a-zéèàâêîôûùä]+)",
            query.lower()
        )
        if between_match:
            meds = list(between_match[0])
            # Chercher des médicaments supplémentaires après "et"
            extra = re.findall(r"\bet\s+([a-zéèàâêîôûùä]{5,})\b", query.lower())
            meds.extend(extra)
            return [m for m in dict.fromkeys(meds) if m not in stop_words][:10]

        # 2. Pattern "X + Y" ou "X, Y"
        plus_match = re.findall(r"([a-zéèàâêîôûùä]{5,})\s*[+,]\s*([a-zéèàâêîôûùä]{5,})", query.lower())
        if plus_match:
            meds = []
            for pair in plus_match:
                meds.extend(pair)
            return [m for m in dict.fromkeys(meds) if m not in stop_words][:10]

        # 3. Fallback : tous les mots d'au moins 5 lettres hors stop-words
        words = re.findall(r"\b[a-zéèàâêîôûùä]{5,}\b", query.lower())
        return [w for w in words if w not in stop_words][:10]

    # ── Méthode utilitaire : nettoyage Markdown pour Google Calendar ──
    @staticmethod
    def _clean_for_calendar(text: str, max_chars: int = 900) -> str:
        """
        Convertit un texte Markdown en texte brut lisible dans Google Calendar.

        Google Calendar n'interprète pas le Markdown — les ** et # s'affichent
        tels quels, ce qui est illisible. On les supprime proprement.

        Transformations :
          **texte**  → TEXTE  (majuscules pour garder l'emphase)
          *texte*    → texte
          ## Titre   → TITRE
          # Titre    → TITRE
          ---        → ──────

        Paramètres :
          text      : texte Markdown brut
          max_chars : longueur maximale (défaut 900 pour Google Calendar)

        Retourne :
          Texte propre, sans Markdown, tronqué si nécessaire
        """
        import re as _re

        # 1. Titres Markdown → MAJUSCULES
        text = _re.sub(r"^#{1,3}\s+(.+)$", lambda m: m.group(1).upper(), text, flags=_re.MULTILINE)

        # 2. **texte** → TEXTE (gras → majuscules)
        text = _re.sub(r"\*\*(.+?)\*\*", lambda m: m.group(1).upper(), text)

        # 3. *texte* ou _texte_ → texte (italique → normal)
        text = _re.sub(r"[*_](.+?)[*_]", r"\1", text)

        # 4. Séparateurs --- → ligne simple
        text = _re.sub(r"^-{3,}$", "──────────", text, flags=_re.MULTILINE)

        # 5. Listes - item → • item
        text = _re.sub(r"^- ", "• ", text, flags=_re.MULTILINE)

        # 6. Supprimer les lignes vides multiples (max 1 ligne vide)
        text = _re.sub(r"\n{3,}", "\n\n", text)

        # 7. Tronquer proprement à la fin d'une phrase/ligne si trop long
        text = text.strip()
        if len(text) > max_chars:
            cut = text[:max_chars].rfind("\n")  # Couper à la dernière ligne complète
            if cut < max_chars // 2:
                cut = text[:max_chars].rfind(". ")  # Sinon à la dernière phrase
            if cut > 0:
                text = text[:cut] + "\n[...résumé tronqué]"
            else:
                text = text[:max_chars] + "…"

        return text

    # ══════════════════════════════════════════════════════════════════
    # EXECUTION
    # ══════════════════════════════════════════════════════════════════
    def execute_step(self, tool_name: str, params: dict) -> ToolResult:
        """
        Exécute un outil par son nom avec les params fournis.
        """
        tool = self.tools.get(tool_name)
        if tool is None:
            return ToolResult.fail(f"Outil inconnu : {tool_name}")
        return tool.execute(params)

    def confirm(self, session_id: str, approved: bool) -> Optional[ToolResult]:
        """
        Reprend l'exécution d'un step en attente après confirmation utilisateur.
        """
        step = self._pending.pop(session_id, None)
        if step is None:
            return None
        if not approved:
            return ToolResult.fail("Action refusée par l'utilisateur")
        return self.execute_step(step["tool_name"], step["params"])

    # ── Streaming SSE ─────────────────────────────────────────────────
    # ══════════════════════════════════════════════════════════════════
    async def run(
        self,
        query: str,
        session_id: Optional[str] = None,
        user_id: Optional[int] = None,
        llm_mode: Optional[str] = None,   # "local" | "cloud" | None (auto)
    ) -> AsyncGenerator[dict, None]:
        """
        Exécute une requête en streaming.
        Yield un dict (Map) par événement : STEP_START, STEP_COMPLETE,
        CONFIRMATION_REQUEST, ANSWER, ou ERROR.
        user_id permet d'utiliser le vrai Google Calendar de l'utilisateur.
        """
        session_id = session_id or str(uuid.uuid4())
        self._history.setdefault(session_id, [])

        try:
            # Utiliser intentDetector (nouveau nom UML) avec alias classify() pour compat
            intent = self.intentDetector.detectAction(query)
            steps  = self.plan(query, intent)

            # Résultats des steps précédents (pour injection inter-steps)
            step_results: dict = {}

            for step in steps:
                # ── Injections inter-steps avant exécution ────────────
                if step["tool_name"] == "calendar_write" and "calendar_read" in step_results:
                    cal_data = step_results["calendar_read"]
                    action = step["params"].get("action")

                    # CREATE : description Google Calendar = lien sécurisé UNIQUEMENT
                    # ✅ Aucune donnée médicale n'est envoyée à Google.
                    # Le médecin clique le lien → son navigateur interroge notre serveur
                    # → résumé affiché depuis notre base RAG (authentification requise).
                    if action == "create":
                        ev = step["params"]["event"]
                        patient_name = ev.get("patient_name", "")
                        doctor_name  = ev.get("doctor_name", "")
                        start_iso    = ev.get("start", "")

                        rdv_link = self._generate_rdv_link(
                            patient_name, doctor_name, start_iso, user_id
                        )
                        step["params"]["event"]["description"] = (
                            f"Patient : {patient_name}\n"
                            f"Médecin : {doctor_name}\n\n"
                            f"🔒 Dossier médical sécurisé :\n{rdv_link}\n\n"
                            f"Les données médicales sont protégées et ne sont pas\n"
                            f"stockées dans Google Calendar."
                        )

                    # DELETE / UPDATE : injecter l'event_id du premier RDV trouvé
                    if action in ("delete", "update"):
                        events = cal_data.get("events", [])
                        if events:
                            first_evt = events[0]
                            step["params"]["event_id"] = first_evt["id"]
                            # Pour UPDATE : reprendre le titre et patient du RDV existant
                            if action == "update" and "event" in step["params"]:
                                step["params"]["event"].setdefault("title", first_evt.get("title", ""))
                                step["params"]["event"].setdefault("patient_name", first_evt.get("patient_name", ""))

                # ── Émet STEP_START (label CDC §5.4) ────────────────
                ev_start = _event(
                    AgentEventType.STEP_START, step["tool_name"],
                    {
                        "order":  step["order"],
                        "params": step["params"],
                        "label":  step.get("label", ""),
                    },
                )
                self._history[session_id].append(ev_start)
                yield ev_start

                # ── Confirmation requise ? ───────────────────────────
                if step["requires_confirmation"]:
                    step["status"] = Status.AWAITING_CONFIRMATION.value
                    # Injecter user_id pour que l'outil accède au vrai calendrier
                    if user_id:
                        step["params"]["user_id"] = user_id
                    self._pending[session_id] = step

                    ev_conf = _event(
                        AgentEventType.CONFIRMATION_REQUEST, step["tool_name"],
                        {
                            "step_order": step["order"],
                            "tool":       step["tool_name"],
                            "params":     {k: v for k, v in step["params"].items() if k != "user_id"},
                            "message":    f"Confirmer l'exécution de {step['tool_name']} ?",
                        },
                    )
                    self._history[session_id].append(ev_conf)
                    yield ev_conf
                    return  # Pause jusqu'à /confirm

                # ── Injecter user_id + llm_mode dans les params ──────
                exec_params = dict(step["params"])
                if user_id and step["tool_name"].startswith("calendar"):
                    exec_params["user_id"] = user_id
                if llm_mode and step["tool_name"] == "rag_query":
                    exec_params["llm_mode"] = llm_mode

                # ── Exécution (thread ≠ blocage event loop) ──────────
                step["status"] = Status.RUNNING.value
                result = await asyncio.to_thread(
                    self.execute_step, step["tool_name"], exec_params
                )
                step["status"] = (
                    Status.COMPLETED.value if result.success else Status.FAILED.value
                )

                ev_done = _event(
                    AgentEventType.STEP_COMPLETE, step["tool_name"],
                    {
                        "order":             step["order"],
                        "success":           result.success,
                        "data":              result.data,
                        "error":             result.error_message,
                        "execution_time_ms": result.execution_time_ms,
                    },
                )
                self._history[session_id].append(ev_done)
                yield ev_done

                # Mémoriser le résultat pour les steps suivants
                if result.success and result.data:
                    step_results[step["tool_name"]] = result.data

            # ── ANSWER final (message lisible CDC §5.4) ──────────────
            entities_out = self.intentDetector.extract_entities(query)
            # Sérialiser date/time pour JSON
            if isinstance(entities_out.get("date"), datetime):
                entities_out["date"] = entities_out["date"].isoformat()
            entities_out.pop("time", None)   # tuple non JSON-sérialisable

            ev_ans = _event(
                AgentEventType.ANSWER, "",
                {
                    "intent":      intent.value,
                    "entities":    entities_out,
                    "steps_count": len(steps),
                    "summary":     " | ".join(
                        f"[{s['status']}] {s['tool_name']}" for s in steps
                    ),
                    "message":     self._build_answer_message(
                        intent, step_results, entities_out
                    ),
                },
            )
            self._history[session_id].append(ev_ans)
            yield ev_ans

        except Exception as exc:
            logger.exception("[MedicalAgent] run error: %s", exc)
            ev_err = _event(AgentEventType.ERROR, "", {"message": str(exc)})
            self._history[session_id].append(ev_err)
            yield ev_err

    def get_history(self, session_id: str) -> List[dict]:
        """Retourne l'historique des événements d'une session."""
        return self._history.get(session_id, [])

    def close(self):
        self._pending.clear()
        logger.info("[MedicalAgent] Fermé")

# ── Helpers module-level (évite la répétition) ────────────────────────
def _step(
    order: int,
    tool_name: str,
    params: dict,
    requires_confirmation: bool = False,
    label: str = "",
) -> dict:
    return {
        "order":                 order,
        "tool_name":             tool_name,
        "params":                params,
        "requires_confirmation": requires_confirmation,
        "status":                Status.PENDING.value,
        "label":                 label or tool_name,
    }

def _event(event_type: AgentEventType, step_name: str, data: dict) -> dict:
    return {
        "type":      event_type.value,
        "step_name": step_name,
        "data":      data,
        "timestamp": datetime.utcnow().isoformat(),
    }
