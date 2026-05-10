/**
 * MainLayout.jsx — Squelette visuel de l'application (Sidebar + Header + Main)
 * ══════════════════════════════════════════════════════════════════════════════
 *
 * RÔLE
 * ─────
 * Ce composant est le "parent" de toutes les pages protégées.
 * Il contient la sidebar de navigation, le header avec le titre et le bouton de déconnexion,

 * POURQUOI <Outlet /> ?
 * <Outlet /> où la page active est injectée par React Router.
 * ──────────────────────
 * React Router v6 injecte la page enfant via <Outlet />.
 * Quand l'URL change (/dashboard → /rag), seul le contenu
 * de <Outlet /> change ; la sidebar et le header restent en place.
 *
 * GESTION DU SCROLL
 * ──────────────────
 * - Pages normales  : overflow-y-auto → scroll naturel dans la zone main
 * - Terminal RAG    : overflow-hidden → RagTerminal gère son propre scroll
 *   (nécessaire pour que la zone de chat soit fixe en hauteur)
 *
 * RESPONSIVE MOBILE
 * ──────────────────
 * - Desktop (md+) : sidebar toujours visible à gauche
 * - Mobile        : sidebar masquée, un bouton hamburger ☰ l'ouvre
 *                   en overlay par-dessus le contenu
 *
 * COULEURS (design Enterprise Health V2.0)
 * ─────────────────────────────────────────
 *   Fond général : #F4F4F2 (beige très clair)
 *   Accent       : #141414 (quasi-noir)
 *   Sidebar/cards: blanc pur
 */
import { useState } from 'react';
import { useLocation, Outlet, Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import {
    LayoutDashboard, BookOpen, MessageSquare, Settings,
    Menu, X, LogOut, FilePlus, History, Users, ShieldCheck,
} from 'lucide-react';

/** Éléments de navigation de la sidebar : ordre = ordre d'affichage. */
const NAV_ITEMS = [
    { path: '/dashboard',    label: 'Tableau de bord',       icon: LayoutDashboard },
    { path: '/knowledge',    label: 'Base de connaissances', icon: BookOpen },
    { path: '/notes',        label: 'Nouvelle Note',         icon: FilePlus },
    { path: '/rag',          label: 'Terminal RAG',          icon: MessageSquare },
    { path: '/conversations',label: 'Historique',            icon: History },
    { path: '/admin/users',  label: 'Utilisateurs',          icon: Users },
    { path: '/settings',     label: 'Configuration',         icon: Settings },
];

/** Titre affiché dans le header selon la route active. */
const PAGE_TITLES = {
    '/dashboard':     'Tableau de bord',
    '/knowledge':     'Base de connaissances',
    '/notes':         'Nouvelle Note',
    '/rag':           'Terminal RAG',
    '/conversations': 'Historique des conversations',
    '/admin/users':   'Gestion des utilisateurs',
    '/settings':      'Configuration',
};

export default function MainLayout() {
    const location  = useLocation();
    const { user, logout } = useAuth();
    const [mobileOpen, setMobileOpen] = useState(false);

    const currentTitle = PAGE_TITLES[location.pathname] || 'Tableau de bord';
    const displayName  = user?.full_name || `Dr. ${user?.username || 'Admin'}`;

    // Le Terminal RAG gère son propre scroll interne → on désactive le scroll global
    const isRag = location.pathname === '/rag';

    return (
        /*
         * height: 100dvh : hauteur dynamique du viewport (100vh ne fonctionne
         * pas bien sur mobile car la barre d'adresse est comptée).
         * overflow: hidden : bloque tout scroll parasite sur le body.
         */
        <div
            className="bg-[#F4F4F2] text-[#141414] font-sans flex overflow-hidden"
            style={{ height: '100dvh' }}
        >
            {/* Backdrop mobile — clic en dehors ferme la sidebar */}
            {mobileOpen && (
                <div
                    className="fixed inset-0 bg-black/30 z-40 md:hidden"
                    onClick={() => setMobileOpen(false)}
                />
            )}

            {/*  Sidebar  */}
            <aside className={`
                fixed inset-y-0 left-0 z-50
                md:relative md:inset-auto md:z-auto md:translate-x-0
                w-64 flex-shrink-0 border-r border-[#141414]/10 bg-white flex flex-col
                shadow-xl md:shadow-none
                transition-transform duration-300
                ${mobileOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'}
            `}>
                {/* Logo + bouton fermeture mobile */}
                <div className="px-6 py-5 border-b border-[#141414]/5 flex items-center justify-between flex-shrink-0">
                    <div>
                        <div className="flex items-center gap-3 mb-1">
                            <div className="bg-[#141414] p-2 rounded-xl text-white flex-shrink-0">
                                <ShieldCheck size={18} />
                            </div>
                            <h1 className="font-serif italic text-xl font-bold tracking-tight">RAG.Med</h1>
                        </div>
                    </div>
                    <button
                        onClick={() => setMobileOpen(false)}
                        className="md:hidden p-1.5 rounded-lg hover:bg-[#141414]/5"
                        aria-label="Fermer le menu"
                    >
                        <X size={16} />
                    </button>
                </div>

                {/* Navigation */}
                <nav className="flex-1 p-4 space-y-1 overflow-y-auto">
                    {NAV_ITEMS.map(({ path, label, icon: Icon }) => {
                        const active =
                            location.pathname === path ||
                            (path === '/dashboard' && location.pathname === '/');
                        return (
                            <Link
                                key={path}
                                to={path}
                                onClick={() => setMobileOpen(false)}
                                className={`flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-200 ${
                                    active
                                        ? 'bg-[#141414] text-white shadow-md'
                                        : 'hover:bg-[#141414]/5 opacity-55 hover:opacity-100'
                                }`}
                            >
                                <Icon size={17} />
                                <span className="text-sm font-semibold">{label}</span>
                                {active && <div className="ml-auto w-1.5 h-1.5 bg-white rounded-full" />}
                            </Link>
                        );
                    })}
                </nav>

                {/* Indicateur de statut des services */}
                <div className="px-4 py-4 border-t border-[#141414]/5 flex-shrink-0">
                    <div className="bg-[#141414]/4 px-4 py-3 rounded-xl flex items-center gap-2">
                        <div className="w-2 h-2 bg-emerald-500 rounded-full animate-pulse flex-shrink-0" />
                        <span className="text-[10px] font-semibold opacity-60">Tous les services actifs</span>
                    </div>
                </div>
            </aside>

            {/*  Zone principale (header + page)  */}
            <div className="flex-1 flex flex-col min-w-0 overflow-hidden">

                {/* Header : flex-shrink-0 = toujours visible, ne scroll pas */}
                <header className="flex-shrink-0 bg-[#F4F4F2] border-b border-[#141414]/8 px-4 md:px-8 py-3 md:py-4 flex items-center justify-between gap-3">
                    <div className="flex items-center gap-3 min-w-0">
                        {/* Bouton hamburger : visible uniquement sur mobile */}
                        <button
                            onClick={() => setMobileOpen(true)}
                            className="md:hidden p-2 rounded-xl hover:bg-[#141414]/8 transition-colors flex-shrink-0"
                            aria-label="Ouvrir le menu"
                        >
                            <Menu size={20} />
                        </button>
                        <div className="min-w-0">
                            <p className="text-[9px] font-mono uppercase tracking-[0.3em] opacity-30 hidden md:block">
                                Medical Intelligence Platform
                            </p>
                            <h2 className="text-lg md:text-2xl font-serif italic font-bold leading-tight truncate">
                                {currentTitle}
                            </h2>
                        </div>
                    </div>
                    <div className="flex items-center gap-2 md:gap-3 flex-shrink-0">
                        <span className="text-xs font-semibold opacity-50 hidden sm:block truncate max-w-32">
                            {displayName}
                        </span>
                        <button
                            onClick={logout}
                            className="flex items-center gap-1.5 px-3 py-2 bg-[#141414] text-white rounded-xl text-xs font-bold uppercase tracking-wide hover:bg-[#141414]/80 transition-colors"
                        >
                            <LogOut size={13} />
                            <span className="hidden sm:inline">Déconnexion</span>
                        </button>
                    </div>
                </header>

                {/* Page active : injectée par React Router via <Outlet /> */}
                <main className={`flex-1 min-h-0 ${isRag ? 'overflow-hidden' : 'overflow-y-auto overflow-x-hidden'}`}>
                    <Outlet />
                </main>
            </div>
        </div>
    );
}
