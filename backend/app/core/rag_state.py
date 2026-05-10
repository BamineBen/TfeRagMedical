"""
rag_state.py — Singleton thread-safe pour l'état partagé du RAG
════════════════════════════════════════════════════════════════

POURQUOI CE FICHIER ?
─────────────────────
Avant ce fichier, l'index FAISS et les métadonnées des chunks étaient
stockés dans deux variables globales dans main.py :

    # main.py (AVANT — antipattern)
    _index = None
    _chunks_mapping = []

N'importe quel fichier pouvait faire `from app.main import _chunks_mapping`
et modifier la liste directement. Problèmes :

  1. Couplage fort : tous les modules dépendent de main.py
  2. Pas thread-safe : si deux médecins uploadent en même temps, les deux
     coroutines peuvent modifier _chunks_mapping simultanément → corruption
  3. Difficile à tester : impossible d'injecter un état mocké

SOLUTION — PATTERN SINGLETON
──────────────────────────────
Un Singleton est un objet dont il n'existe QU'UNE SEULE instance en mémoire.
Tous les modules accèdent au MÊME objet → cohérence garantie.

    # Tous les modules font maintenant :
    from app.core.rag_state import rag_state
    index, chunks = rag_state.get()

THREAD SAFETY AVEC asyncio.Lock
────────────────────────────────
asyncio est mono-threadé (une seule coroutine s'exécute à la fois).
Mais avec `await`, une coroutine peut "lâcher le fil d'exécution" au milieu
d'une opération → une autre coroutine peut commencer à écrire → race condition.

Exemple de race condition SANS lock :
  Médecin A : upload → load_chunks (3462 items) → ...await encode... → save(3463 items)
  Médecin B : upload → load_chunks (3462 items) → ...await encode... → save(3463 items)
  Résultat : 3463 au lieu de 3464 — un chunk est perdu silencieusement !

Avec asyncio.Lock() :
  Médecin A : acquire lock → load → encode → save → release lock
  Médecin B : (attend)     → acquire lock → load → encode → save → release

LECTURE VS ÉCRITURE
────────────────────
- Lectures (get)  : pas de lock nécessaire (asyncio mono-threadé, lectures atomiques)
- Écritures (set) : lock obligatoire (protège les séquences read-modify-write)
"""
import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class RagStateService:
    """
    Service singleton pour l'index FAISS et les métadonnées chunks.

    Usage dans n'importe quel module :
        from app.core.rag_state import rag_state

        # Lecture
        index, chunks = rag_state.get()

        # Écriture sync (démarrage app, avant event loop)
        rag_state.set(index, chunks)

        # Écriture async thread-safe (upload, notes, hot-folder)
        await rag_state.update(index, chunks)

        # Opération atomique multi-étapes (ex: append note + save)
        async with rag_state.write_lock:
            mapping = load()
            mapping.append(new_entry)
            save(mapping)
    """

    # L'underscore signifie "attribut de classe privé"
    # Il est partagé entre TOUTES les instances (mais il n'y en aura qu'une)
    _instance: 'RagStateService | None' = None

    def __new__(cls) -> 'RagStateService':
        """
        __new__ est appelé AVANT __init__ lors de la création d'un objet.
        On l'override pour implémenter le Singleton :
        si l'instance existe déjà, on la retourne sans en créer une nouvelle.
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            # Initialisation des attributs (une seule fois)
            cls._instance._index = None           # Index FAISS
            cls._instance._chunks: list = []      # Métadonnées chunks
            cls._instance._write_lock = asyncio.Lock()  # Verrou asyncio
            logger.debug("[rag_state] Singleton créé")
        return cls._instance

    #  Lecture 

    def get(self) -> tuple[Any, list]:
        """
        Lecture rapide de l'état courant.

        PAS de lock : en asyncio mono-threadé, les accès en lecture sont
        toujours cohérents (pas d'interruption possible sans await).

        Returns:
            (index, chunks_mapping) — tuple déstructurable
        """
        return self._index, self._chunks

    @property
    def index(self) -> Any:
        """Accès direct à l'index FAISS."""
        return self._index

    @property
    def chunks(self) -> list:
        """Accès direct à la liste des chunks."""
        return self._chunks

    #  Écriture 

    def set(self, index: Any, chunks: list) -> None:
        """
        Mise à jour SYNCHRONE — pour le démarrage de l'application.

        Utilisé dans lifespan() et _load_index() car au démarrage
        l'event loop asyncio n'est pas encore pleinement opérationnel.

        ATTENTION : n'utilise pas le lock — réservé au contexte de
        démarrage où une seule coroutine s'exécute.

        Args:
            index  : index FAISS chargé (peut être None si aucun doc)
            chunks : liste des métadonnées chunks
        """
        self._index = index
        self._chunks = chunks
        count = len(chunks) if chunks else 0
        logger.info(f"[rag_state] État initialisé : {count} chunks")

    async def update(self, index: Any, chunks: list) -> None:
        """
        Mise à jour ASYNC thread-safe — pour les uploads et notes.

        Acquiert le lock avant de modifier l'état → si deux médecins
        uploadent simultanément, le second attend que le premier finisse.

        Args:
            index  : nouvel index FAISS
            chunks : nouvelle liste de chunks
        """
        async with self._write_lock:
            self._index = index
            self._chunks = chunks
            count = len(chunks) if chunks else 0
            logger.info(f"[rag_state] Index mis à jour : {count} chunks")

    @property
    def write_lock(self) -> asyncio.Lock:
        """
        Lock direct pour les opérations atomiques multi-étapes.

        Exemple d'utilisation dans notes.py :
            async with rag_state.write_lock:
                mapping = load_mapping()      # lecture
                mapping.append(new_chunk)     # modification
                save_mapping(mapping)         # écriture
                rag_state.set(idx, mapping)   # mise à jour mémoire
        """
        return self._write_lock


#  Instance globale unique 
# C'est LE point d'accès partagé par toute l'application.
# Import dans n'importe quel module :
#   from app.core.rag_state import rag_state
rag_state = RagStateService()
