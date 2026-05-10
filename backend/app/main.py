"""
main.py — Point d'entrée de l'application FastAPI
══════════════════════════════════════════════════

RÔLE DANS L'ARCHITECTURE
─────────────────────────
Ce fichier est LE point d'entrée de toute l'application backend.
C'est lui que Uvicorn (le serveur HTTP) démarre :
    uvicorn app.main:app --host 0.0.0.0 --port 8000

RESPONSABILITÉS
───────────────
1. Initialisation au démarrage (lifespan) :
   - Chargement de l'index FAISS en mémoire
   - Construction de l'index BM25
   - Initialisation de la base de données PostgreSQL
   - Création de l'utilisateur admin si nécessaire
   - Lancement du hot-folder watcher (indexation automatique)

2. Configuration CORS (Cross-Origin Resource Sharing) :
   Permet au frontend (port 5000 ou 5173) d'appeler le backend (port 8000).

3. Enregistrement des routes API :
   Toutes les routes /api/v1/... sont définies dans app/api/v1/router.py

4. Quelques routes utilitaires directes :
   - GET /health           → statut du service
   - POST /api/query-stream → streaming RAG (legacy, pour tests)
   - POST /api/upload      → upload direct (sans auth, legacy)
   - GET /api/documents    → liste des documents (legacy)
   - DELETE /api/documents/{filename} → suppression (legacy)

ÉTAT GLOBAL
───────────
_index          : index FAISS en mémoire (chargé une fois au démarrage)
_chunks_mapping : liste des métadonnées des chunks (chargée avec l'index)

Ces deux variables sont globales car l'index est partagé entre toutes
les requêtes HTTP simultanées. Chaque requête lit l'index mais ne l'écrit
jamais directement (thread-safe en lecture).

HOT-FOLDER WATCHER
──────────────────
Le _hot_folder_watcher() tourne en arrière-plan (asyncio.Task) et surveille
le dossier medical_docs/ toutes les 60s. Si un nouveau fichier PDF/TXT
apparaît (déposé par SCP/SSH), il est automatiquement indexé.
→ Permet d'indexer des documents sans passer par l'interface web.
"""
import asyncio
import logging
import time
import json
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import settings
from app.core import vector_store
from app.core.bm25_engine import bm25_engine
from app.core import rag_engine
from app.core.llm_client import LLMMessage, get_llm_client
from app.core.document_processor import index_single_document, index_all_documents
from app.core.query_cache import query_cache
from app.core.rag_state import rag_state

logging.basicConfig(level=settings.LOG_LEVEL, format=settings.LOG_FORMAT)
logger = logging.getLogger(__name__)

#  État global migré vers RagStateService 
# Les variables _index et _chunks_mapping sont maintenant gérées par
# app.core.rag_state.rag_state (singleton thread-safe).
#
# Pour la rétrocompatibilité, _load_index() est conservé comme fonction
# utilitaire — il délègue maintenant à rag_state.set().
# Accès depuis les autres modules : from app.core.rag_state import rag_state


def _load_index():
    """
    Charge (ou recharge) l'index FAISS et le mapping depuis le disque.

    Appelé :
    - Au démarrage de l'application (lifespan)
    - Après chaque indexation de document (nouveaux chunks disponibles)
    - Après suppression d'un document (reconstruction de l'index)
    - Par le hot-folder watcher (fichiers déposés via SCP)

    Délègue à rag_state.set() — le singleton thread-safe.
    Si l'index n'existe pas encore, rag_state reste vide → frontend affiche
    "Aucun document indexé".
    """
    try:
        index = vector_store.load_index()
        chunks = vector_store.load_chunks_mapping()
        logger.info(f"[API] Index chargé : {index.ntotal} vecteurs, {len(chunks)} chunks")
        bm25_engine.build(chunks)
        rag_state.set(index, chunks)
    except FileNotFoundError:
        logger.info("[API] Aucun index trouvé. Uploadez des documents.")
        rag_state.set(None, [])


async def _hot_folder_watcher():
    """
    Surveille medical_docs/ et indexe automatiquement tout nouveau fichier PDF/TXT.
    Pilier 3 de l'architecture dynamique : Trigger automatique sans action manuelle.
    Intervalle : 60 secondes.
    """
    await asyncio.sleep(15)  # Attendre que l'index initial soit chargé
    while True:
        try:
            docs_dir = vector_store.MEDICAL_DOCS_DIR
            if docs_dir.exists():
                _, chunks = rag_state.get()
                known_sources = {m["source"] for m in chunks}
                new_files = [
                    fp for fp in list(docs_dir.glob("*.pdf")) + list(docs_dir.glob("*.txt"))
                    if fp.name not in known_sources
                ]
                for fp in new_files:
                    logger.info(f"[hot-folder] Nouveau fichier détecté: {fp.name}")
                    try:
                        num = await asyncio.to_thread(index_single_document, str(fp))
                        _load_index()
                        query_cache.invalidate_all()
                        logger.info(f"[hot-folder] ✅ {fp.name} auto-indexé ({num} chunks)")
                    except Exception as e:
                        logger.error(f"[hot-folder] ❌ Erreur {fp.name}: {e}")
        except Exception as e:
            logger.warning(f"[hot-folder] Watcher error: {e}")
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting RAG Platform...")
    _load_index()

    # Init DB + admin si nécessaire (garder la compat avec le frontend existant)
    try:
        from app.database import init_db
        await init_db()
        from app.init_admin import init_admin_user
        await init_admin_user()
        from app.models.setting import DEFAULT_SETTINGS, SystemSetting
        from app.database import AsyncSessionLocal
        from sqlalchemy import select as sa_select
        async with AsyncSessionLocal() as session:
            for s in DEFAULT_SETTINGS:
                existing = (await session.execute(
                    sa_select(SystemSetting).where(SystemSetting.key == s["key"])
                )).scalar_one_or_none()
                if not existing:
                    session.add(SystemSetting(key=s["key"], value=s["value"], description=s["description"]))
            await session.commit()
    except Exception as e:
        logger.warning(f"DB init skipped: {e}")

    # Hot-folder watcher désactivé en local (FAISS complet depuis VPS).
    # En production Docker, réactiver en décommentant la ligne ci-dessous.
    # watcher = asyncio.create_task(_hot_folder_watcher())
    watcher = None

    yield

    if watcher:
        watcher.cancel()
    logger.info("Shutting down...")
    try:
        from app.database import close_db
        await close_db()
    except Exception:
        pass


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/api/v1/openapi.json"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_HOSTS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Garder les routes existantes du frontend (auth, users, dashboard, etc.) ──
from app.api.v1.router import api_router
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


#  LLM async helper (Ollama local) 
async def _stream_main(prompt: str):
    """Async generator pour /api/query-stream."""
    async for token in get_llm_client().generate_stream(
        messages=[LLMMessage(role="user", content=prompt)]
    ):
        yield token


#  Routes RAG (sans préfixe /api/v1 pour accès direct) 

@app.get("/health")
async def health_check():
    _index, _chunks_mapping = rag_state.get()
    doc_names = set(m["source"] for m in _chunks_mapping) if _chunks_mapping else set()
    return {
        "status": "ready" if _index is not None else "no_index",
        "indexed_documents": len(doc_names),
        "total_chunks": len(_chunks_mapping),
        "timestamp": time.time(),
        "version": settings.APP_VERSION,
    }


@app.get("/api/health")
async def api_health():
    return await health_check()


class QueryRequest(BaseModel):
    question: str
    top_k: int = 15
    min_score: float = 0.05
    source_filter: str | None = None


@app.post("/api/query-stream")
async def query_stream_rag(request: QueryRequest):
    """Query RAG en streaming SSE."""
    from app.core.rag.prompts import classify_query, GREETING_RESPONSE

    intent = classify_query(request.question)

    # Greeting → réponse directe sans RAG
    if intent == "greeting":
        async def greeting_sse():
            yield f"data: {json.dumps({'type': 'sources', 'data': []})}\n\n"
            yield f"data: {json.dumps({'type': 'citations', 'data': []})}\n\n"
            for i in range(0, len(GREETING_RESPONSE), 80):
                yield f"data: {json.dumps({'type': 'token', 'data': GREETING_RESPONSE[i:i+80]})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        return StreamingResponse(greeting_sse(), media_type="text/event-stream")

    # General → LLM direct sans RAG
    if intent == "general":
        prompt = (
            f"Tu es un assistant médical. L'utilisateur dit : \"{request.question}\"\n"
            f"Réponds naturellement en français. Si la question n'est pas médicale, "
            f"rappelle que tu es spécialisé dans l'analyse de dossiers patients."
        )
        async def general_sse():
            yield f"data: {json.dumps({'type': 'sources', 'data': []})}\n\n"
            yield f"data: {json.dumps({'type': 'citations', 'data': []})}\n\n"
            async for token in _stream_main(prompt):
                yield f"data: {json.dumps({'type': 'token', 'data': token})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        return StreamingResponse(general_sse(), media_type="text/event-stream")

    # Medical → RAG complet
    _index, _chunks_mapping = rag_state.get()
    if _index is None or _index.ntotal == 0:
        raise HTTPException(status_code=400, detail="Aucun document indexé.")

    cache_key = query_cache.make_key(request.question, request.source_filter)
    cached = query_cache.get(cache_key)

    if cached:
        sources, answer, cmap = cached

        async def cached_sse():
            yield f"data: {json.dumps({'type': 'sources', 'data': sources})}\n\n"
            yield f"data: {json.dumps({'type': 'citations', 'data': cmap})}\n\n"
            for i in range(0, len(answer), 50):
                yield f"data: {json.dumps({'type': 'token', 'data': answer[i:i+50]})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        return StreamingResponse(cached_sse(), media_type="text/event-stream")

    prompt, hits, citation_map = rag_engine.build_rag_prompt(
        query=request.question, index=_index, chunks_mapping=_chunks_mapping,
        k=request.top_k, min_score=request.min_score, source_filter=request.source_filter,
    )
    sources = [
        {"text": h["text"][:200], "score": round(h["score"], 4), "source": h["source"]}
        for h in hits
    ]

    async def sse_gen():
        yield f"data: {json.dumps({'type': 'sources', 'data': sources})}\n\n"
        yield f"data: {json.dumps({'type': 'citations', 'data': citation_map})}\n\n"
        full = ""
        async for token in _stream_main(prompt):
            full += token
            yield f"data: {json.dumps({'type': 'token', 'data': token})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"
        query_cache.set(cache_key, (sources, full, citation_map))

    return StreamingResponse(sse_gen(), media_type="text/event-stream")


@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...)):
    ext = Path(file.filename).suffix.lower()
    if ext not in (".pdf", ".txt"):
        raise HTTPException(400, "Format non supporté. PDF ou TXT uniquement.")
    dest = vector_store.MEDICAL_DOCS_DIR / file.filename
    with open(dest, "wb") as f:
        f.write(await file.read())
    try:
        num = index_single_document(str(dest))
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(500, f"Erreur d'indexation : {e}")
    _load_index()
    query_cache.invalidate_all()
    _, chunks = rag_state.get()
    return {"message": f"'{file.filename}' indexé", "chunks_created": num, "total_chunks": len(chunks)}


@app.get("/api/documents")
async def list_documents():
    _, chunks = rag_state.get()
    if not chunks:
        return {"documents": []}
    stats = {}
    for m in chunks:
        src = m["source"]
        stats[src] = stats.get(src, 0) + 1
    return {"documents": [{"name": n, "chunks": c} for n, c in stats.items()]}


@app.delete("/api/documents/{filename}")
async def delete_document(filename: str):
    doc_path = vector_store.MEDICAL_DOCS_DIR / filename
    if doc_path.exists():
        doc_path.unlink()
    _, _chunks_mapping = rag_state.get()
    remaining = [m for m in _chunks_mapping if m["source"] != filename]
    if not remaining:
        vector_store.FAISS_INDEX_PATH.unlink(missing_ok=True)
        vector_store.CHUNKS_MAPPING_PATH.unlink(missing_ok=True)
        rag_state.set(None, [])
        return {"message": f"'{filename}' supprimé. Index vidé."}
    from app.core.embeddings import get_embedding_service
    emb = get_embedding_service()
    texts = [m["text"] for m in remaining]
    sources = [m["source"] for m in remaining]
    embeddings = emb.encode(texts)
    new_idx = vector_store.create_index(embeddings.shape[1])
    vector_store.add_vectors(new_idx, embeddings)
    vector_store.save_index(new_idx)
    vector_store.save_chunks_mapping(
        texts, sources,
        date_scores=[m.get("date_score", 0.0) for m in remaining],
        page_numbers=[m.get("page_number", 1) for m in remaining],
        categories=[m.get("category", "AUTRE") for m in remaining],
        parent_texts=[m.get("parent_text", m["text"]) for m in remaining],
    )
    _load_index()
    query_cache.invalidate_all()
    return {"message": f"'{filename}' supprimé. Index reconstruit."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
