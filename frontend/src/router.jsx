/**
 * router.jsx : Toutes les routes de l'application.
 * Application principale (/login, /dashboard...).
 */
import { createBrowserRouter, Navigate } from 'react-router-dom';

// Application principale
import MainLayout         from './layouts/MainLayout';
import LoginPage          from './pages/Login';
import Dashboard          from './pages/Dashboard';
import KnowledgeBase      from './pages/KnowledgeBase';
import RagTerminal        from './pages/RagTerminal';
import SystemConfig       from './pages/SystemConfig';
import NoteAtomique       from './pages/NoteAtomique';
import Conversations      from './pages/Conversations';
import UserManagement     from './pages/UserManagement';
import RdvView            from './pages/RdvView';
import ProtectedRoute     from './components/ProtectedRoute';

// Sandbox /medrag/*
import MedragLogin          from './pages/MedragLogin';
import MedragLayout         from './layouts/MedragLayout';
import MedragProtectedRoute from './components/MedragProtectedRoute';
import WsDashboard          from './pages/medrag/WsDashboard';
import WsRag                from './pages/medrag/WsRag';
import WsKnowledge          from './pages/medrag/WsKnowledge';
import WsNotes              from './pages/medrag/WsNotes';
import WsConversations      from './pages/medrag/WsConversations';
import WsUsers              from './pages/medrag/WsUsers';
import WsSettings           from './pages/medrag/WsSettings';

export const router = createBrowserRouter([
    // Routes publiques
    { path: '/login',       element: <LoginPage /> },
    { path: '/rdv',         element: <RdvView /> },
    { path: '/medrag/login', element: <MedragLogin /> },

    // Application principale (protégée)
    {
        path: '/',
        element: <ProtectedRoute><MainLayout /></ProtectedRoute>,
        children: [
            { index: true,           element: <Navigate to="/dashboard" replace /> },
            { path: 'dashboard',     element: <Dashboard /> },
            { path: 'knowledge',     element: <KnowledgeBase /> },
            { path: 'rag',           element: <RagTerminal /> },
            { path: 'notes',         element: <NoteAtomique /> },
            { path: 'conversations', element: <Conversations /> },
            { path: 'admin/users',   element: <UserManagement /> },
            { path: 'settings',      element: <SystemConfig /> },
        ],
    },

    // Sandbox d'entraînement (protégé par token medrag séparé)
    {
        path: '/medrag',
        element: <MedragProtectedRoute><MedragLayout /></MedragProtectedRoute>,
        children: [
            { index: true,              element: <Navigate to="/medrag/dashboard" replace /> },
            { path: 'dashboard',        element: <WsDashboard /> },
            { path: 'rag',              element: <WsRag /> },
            { path: 'knowledge',        element: <WsKnowledge /> },
            { path: 'notes',            element: <WsNotes /> },
            { path: 'conversations',    element: <WsConversations /> },
            { path: 'users',            element: <WsUsers /> },
            { path: 'settings',         element: <WsSettings /> },
        ],
    },
]);