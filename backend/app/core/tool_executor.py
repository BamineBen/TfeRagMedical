"""
Exécuteur de Tools - Système d'outils pour l'IA
Architecture plugin pour étendre les capacités
"""

import logging
import time
import json
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Type
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class ToolResult:
    """Résultat d'exécution d'un outil"""
    success: bool
    output: Any
    error: str | None = None
    execution_time_ms: int = 0


class BaseTool(ABC):
    """Classe de base pour les outils"""

    name: str = "base_tool"
    description: str = "Base tool"

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Exécute l'outil"""
        pass

    @property
    @abstractmethod
    def parameters_schema(self) -> Dict:
        """Schéma JSON des paramètres"""
        pass

    def to_openai_tool(self) -> Dict:
        """Convertit en format OpenAI tool"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema
            }
        }


class DateTimeTool(BaseTool):
    """Outil pour obtenir la date et l'heure"""

    name = "get_datetime"
    description = "Obtient la date et l'heure actuelles dans différents fuseaux horaires"

    @property
    def parameters_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": "Fuseau horaire (ex: Europe/Paris, UTC)",
                    "default": "UTC"
                },
                "format": {
                    "type": "string",
                    "description": "Format de date (ex: %Y-%m-%d %H:%M:%S)",
                    "default": "%Y-%m-%d %H:%M:%S"
                }
            },
            "required": []
        }

    async def execute(
        self,
        timezone: str = "UTC",
        format: str = "%Y-%m-%d %H:%M:%S"
    ) -> ToolResult:
        start_time = time.time()
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(timezone)
            now = datetime.now(tz)
            formatted = now.strftime(format)

            return ToolResult(
                success=True,
                output={
                    "datetime": formatted,
                    "timezone": timezone,
                    "timestamp": now.timestamp()
                },
                execution_time_ms=int((time.time() - start_time) * 1000)
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output=None,
                error=str(e),
                execution_time_ms=int((time.time() - start_time) * 1000)
            )


class SQLQueryTool(BaseTool):
    """Outil pour exécuter des requêtes SQL (lecture seule)"""

    name = "sql_query"
    description = "Exécute une requête SQL en lecture seule sur une base de données externe"

    def __init__(self, connection_string: str | None = None):
        self.connection_string = connection_string

    @property
    def parameters_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Requête SQL SELECT à exécuter"
                },
                "database": {
                    "type": "string",
                    "description": "Nom de la base de données",
                    "default": "default"
                }
            },
            "required": ["query"]
        }

    async def execute(
        self,
        query: str,
        database: str = "default"
    ) -> ToolResult:
        start_time = time.time()

        # Validation: seulement SELECT
        if not query.strip().upper().startswith("SELECT"):
            return ToolResult(
                success=False,
                output=None,
                error="Seules les requêtes SELECT sont autorisées",
                execution_time_ms=int((time.time() - start_time) * 1000)
            )

        # Vérification des mots-clés dangereux
        dangerous_keywords = ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE"]
        query_upper = query.upper()
        for keyword in dangerous_keywords:
            if keyword in query_upper:
                return ToolResult(
                    success=False,
                    output=None,
                    error=f"Mot-clé interdit détecté: {keyword}",
                    execution_time_ms=int((time.time() - start_time) * 1000)
                )

        try:
            # Note: Implémentation réelle à adapter selon la config
            # Ceci est un placeholder
            return ToolResult(
                success=True,
                output={
                    "message": "SQL tool configured but no database connected",
                    "query": query
                },
                execution_time_ms=int((time.time() - start_time) * 1000)
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output=None,
                error=str(e),
                execution_time_ms=int((time.time() - start_time) * 1000)
            )


class CalculatorTool(BaseTool):
    """Outil calculatrice simple"""

    name = "calculator"
    description = "Effectue des calculs mathématiques simples"

    @property
    def parameters_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Expression mathématique (ex: 2 + 2, sqrt(16))"
                }
            },
            "required": ["expression"]
        }

    async def execute(self, expression: str) -> ToolResult:
        start_time = time.time()
        try:
            # Fonctions mathématiques autorisées
            import math
            allowed_names = {
                k: v for k, v in math.__dict__.items()
                if not k.startswith("_")
            }
            allowed_names.update({
                "abs": abs,
                "round": round,
                "min": min,
                "max": max,
                "sum": sum,
            })

            # Évaluation sécurisée
            result = eval(expression, {"__builtins__": {}}, allowed_names)

            return ToolResult(
                success=True,
                output={"result": result, "expression": expression},
                execution_time_ms=int((time.time() - start_time) * 1000)
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output=None,
                error=str(e),
                execution_time_ms=int((time.time() - start_time) * 1000)
            )


class DoctorScheduleTool(BaseTool):
    """Outil pour vérifier l'emploi du temps d'un médecin"""

    name = "check_doctor_schedule"
    description = "Vérifie l'emploi du temps ou les horaires de disponibilité d'un médecin spécifique. À utiliser quand on pose une question sur l'horaire ou la disponibilité d'un docteur."

    @property
    def parameters_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "doctor_name": {
                    "type": "string",
                    "description": "Nom de famille ou prénom du médecin (ex: 'Dupont', 'Martin')"
                },
                "day": {
                    "type": "string",
                    "description": "Jour de la semaine recherché (ex: 'lundi', 'mardi', 'aujourd\\'hui')",
                    "default": "aujourd'hui"
                }
            },
            "required": ["doctor_name"]
        }

    # URL du Google Sheet public (plannings des médecins)
    SHEETS_CSV_URL = (
        "https://docs.google.com/spreadsheets/d/e/"
        "2PACX-1vSJRqJ-0IiuCX3kJx4pVaOiaetUkl7w3DbAINJjZCi57z28TQYd2OH7y-VGCiflK527ay6o6tJewupi"
        "/pub?output=csv&gid=0"
    )

    async def _fetch_schedule(self) -> dict:
        """Lit le Google Sheet en temps réel et retourne un dict {medecin: {jour: horaires}}."""
        import csv, io, time
        import urllib.request
        # Timestamp dans l'URL pour bypasser le cache Google (~5 min sinon)
        url = f"{self.SHEETS_CSV_URL}&_t={int(time.time())}"
        req = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=5) as r:
            content = r.read().decode("utf-8")
        schedule = {}
        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            name = row.get("medecin", "").strip().lower()
            if name:
                schedule[name] = {k: v for k, v in row.items() if k != "medecin"}
        return schedule

    async def execute(self, doctor_name: str, day: str = "aujourd'hui") -> ToolResult:
        start_time = time.time()

        doc_lower = doctor_name.lower().strip()
        day_lower = day.lower().strip()

        # Résoudre "aujourd'hui" / "demain" en nom de jour réel
        days_fr = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
        if day_lower == "aujourd'hui":
            day_lower = days_fr[datetime.now().weekday()]
        elif day_lower == "demain":
            day_lower = days_fr[(datetime.now().weekday() + 1) % 7]

        try:
            # Lecture en temps réel depuis Google Sheets
            planning = await self._fetch_schedule()

            # Recherche souple du médecin (dupont matche "Dr. Dupont")
            found_doctor = None
            for key in planning:
                if key in doc_lower or doc_lower in key:
                    found_doctor = key
                    break

            if not found_doctor:
                return ToolResult(
                    success=False,
                    output={"error": f"Médecin '{doctor_name}' introuvable dans le planning Google Sheets."},
                    execution_time_ms=int((time.time() - start_time) * 1000)
                )

            schedule = planning[found_doctor].get(day_lower, "Information non disponible pour ce jour")

            return ToolResult(
                success=True,
                output={
                    "medecin": found_doctor.capitalize(),
                    "jour": day_lower.capitalize(),
                    "horaires": schedule,
                    "source": "Google Sheets (temps réel)",
                    "message_brut": f"Le docteur {found_doctor.capitalize()} consulte le {day_lower} selon les horaires : {schedule}"
                },
                execution_time_ms=int((time.time() - start_time) * 1000)
            )

        except Exception as e:
            return ToolResult(
                success=False,
                output=None,
                error=f"Erreur lecture Google Sheets : {e}",
                execution_time_ms=int((time.time() - start_time) * 1000)
            )




class ToolRegistry:
    """Registre des outils disponibles"""

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
        self._register_default_tools()

    def _register_default_tools(self):
        """Enregistre les outils par défaut"""
        self.register(DateTimeTool())
        self.register(SQLQueryTool())
        self.register(CalculatorTool())
        self.register(DoctorScheduleTool())

    def register(self, tool: BaseTool):
        """Enregistre un outil"""
        self._tools[tool.name] = tool
        logger.info(f"Tool registered: {tool.name}")

    def unregister(self, name: str):
        """Désenregistre un outil"""
        if name in self._tools:
            del self._tools[name]

    def get(self, name: str) -> BaseTool | None:
        """Récupère un outil par son nom"""
        return self._tools.get(name)

    def list_tools(self) -> List[str]:
        """Liste les outils disponibles"""
        return list(self._tools.keys())

    def get_openai_tools(self) -> List[Dict]:
        """Retourne tous les outils au format OpenAI"""
        return [tool.to_openai_tool() for tool in self._tools.values()]


class ToolExecutor:
    """Exécuteur d'outils"""

    def __init__(self, registry: ToolRegistry | None = None):
        self.registry = registry or ToolRegistry()

    async def execute(
        self,
        tool_name: str,
        parameters: Dict
    ) -> ToolResult:
        """
        Exécute un outil

        Args:
            tool_name: Nom de l'outil
            parameters: Paramètres de l'outil

        Returns:
            Résultat de l'exécution
        """
        tool = self.registry.get(tool_name)
        if not tool:
            return ToolResult(
                success=False,
                output=None,
                error=f"Tool not found: {tool_name}"
            )

        try:
            logger.info(f"Executing tool: {tool_name} with params: {parameters}")
            result = await tool.execute(**parameters)
            logger.info(f"Tool {tool_name} completed: success={result.success}")
            return result
        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            return ToolResult(
                success=False,
                output=None,
                error=str(e)
            )

    async def execute_tool_calls(
        self,
        tool_calls: List[Dict]
    ) -> List[Dict]:
        """
        Exécute plusieurs appels d'outils

        Args:
            tool_calls: Liste des appels d'outils (format OpenAI)

        Returns:
            Liste des résultats
        """
        results = []
        for call in tool_calls:
            tool_name = call["function"]["name"]
            try:
                parameters = json.loads(call["function"]["arguments"])
            except json.JSONDecodeError:
                parameters = {}

            result = await self.execute(tool_name, parameters)
            results.append({
                "tool_call_id": call.get("id", ""),
                "tool_name": tool_name,
                "result": result
            })

        return results


# Instance singleton
_tool_executor: ToolExecutor | None = None


def get_tool_executor() -> ToolExecutor:
    """Retourne l'instance singleton de l'exécuteur d'outils"""
    global _tool_executor
    if _tool_executor is None:
        _tool_executor = ToolExecutor()
    return _tool_executor
