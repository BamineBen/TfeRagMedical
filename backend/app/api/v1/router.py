from fastapi import APIRouter
from app.api.v1 import auth, users, documents, conversations, chat, dashboard, settings, notes, patients
from app.api.v1 import agent

api_router = APIRouter()
api_router.include_router(auth.router,          prefix="/auth",           tags=["Authentification"])
api_router.include_router(users.router,         prefix="/users",          tags=["Utilisateurs"])
api_router.include_router(documents.router,     prefix="/documents",      tags=["Documents"])
api_router.include_router(conversations.router, prefix="/conversations",  tags=["Conversations"])
api_router.include_router(chat.router,          prefix="/chat",           tags=["Chat"])
api_router.include_router(dashboard.router,     prefix="/dashboard",      tags=["Dashboard"])
api_router.include_router(settings.router,      prefix="/admin/settings", tags=["Administration"])
api_router.include_router(notes.router,         prefix="/notes",          tags=["Notes"])
api_router.include_router(patients.router,      prefix="/patients",       tags=["Patients"])
api_router.include_router(agent.router,         prefix="/agent",          tags=["Agent"])

