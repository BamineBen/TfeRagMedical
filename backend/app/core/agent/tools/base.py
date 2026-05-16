"""
tools/base.py : Contrat abstrait des outils (Pattern Strategy).

AgentTool définit l'interface que chaque outil concret doit respecter.
"""
from abc import ABC, abstractmethod
from app.core.agent.models import ToolResult

class AgentTool(ABC):
    """
    Interface abstraite — Pattern Strategy.
    Chaque outil (CalendarReadTool, RAGQueryTool…) implémente execute().
    L'agent appelle tool.execute(params) sans connaître l'outil concret.
    """

    name:                  str  = "base_tool"
    description:           str  = ""
    requires_confirmation: bool = False

    @abstractmethod
    def execute(self, params: dict) -> ToolResult:
        """Exécute l'outil. Chaque sous-classe implémente sa logique métier."""

    def validate_params(self, params: dict) -> bool:
        """Validation minimale. Les sous-classes surchargent si besoin."""
        return isinstance(params, dict)
