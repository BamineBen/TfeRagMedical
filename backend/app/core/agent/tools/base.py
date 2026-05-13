tools/base.py : Contrat des outils (Pattern Strategy + Template Method).

AgentTool définit l'INTERFACE que chaque outil doit respecter.
Avantage : l'agent appelle tool.execute(params) sans connaître l'outil.

from abc import ABC, abstractmethod
from app.core.agent.models import ToolResult


class AgentTool(ABC):
    Classe abstraite (contrat) de tous les outils de l'agent.
    
    Pattern Strategy : CalendarReadTool, InteractionCheckTool... sont
    des implémentations interchangeables de ce même contrat.

    name: str = "base_tool"
    description: str = "Outil de base"
    requires_confirmation: bool = False  # True = attend OK médecin avant exécution

    @abstractmethod
    def execute(self, params: dict) -> ToolResult:
        Exécute l'outil. Chaque sous-classe implémente sa logique métier.
        params : dict d'entrée (ex: {"date": "2024-01-01"})


    def validate_params(self, params: dict) -> bool:

        Pattern Template Method : validation par défaut (dict non vide).
        Chaque outil peut surcharger pour une validation plus stricte.
        
        return isinstance(params, dict)