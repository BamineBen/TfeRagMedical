import { Outlet, Link, useLocation } from 'react-router-dom';

const NAV_ITEMS = [
    { path: '/medrag/dashboard',     label: 'Dashboard' },
    { path: '/medrag/rag',           label: 'Terminal RAG' },
    { path: '/medrag/knowledge',     label: 'Base de connaissances' },
    { path: '/medrag/notes',         label: 'Notes' },
    { path: '/medrag/conversations', label: 'Conversations' },
    { path: '/medrag/users',         label: 'Utilisateurs' },
    { path: '/medrag/settings',      label: 'Configuration' },
];

export default function MedragLayout() {
    const location = useLocation();
    const completed = NAV_ITEMS.filter(item => location.pathname !== item.path).length;

    return (
        <div className="flex h-screen bg-gray-50">
            <aside className="w-64 bg-violet-900 text-white flex flex-col">
                <div className="p-5 border-b border-violet-800">
                    <p className="text-xs font-bold uppercase tracking-widest text-violet-300 mb-1">Sandbox</p>
                    <h1 className="font-bold text-lg">MedRAG Training</h1>
                    <p className="text-xs text-violet-400 mt-1">{completed}/8 pages complétées</p>
                    <div className="w-full bg-violet-800 rounded-full h-1 mt-2">
                        <div
                            className="bg-violet-400 h-1 rounded-full transition-all"
                            style={{ width: `${(completed / 8) * 100}%` }}
                        />
                    </div>
                </div>
                <nav className="flex-1 p-3 space-y-1">
                    {NAV_ITEMS.map(item => (
                        <Link
                            key={item.path}
                            to={item.path}
                            className={`block px-3 py-2.5 rounded-xl text-sm font-medium transition-colors ${
                                location.pathname === item.path
                                    ? 'bg-violet-700 text-white'
                                    : 'text-violet-300 hover:bg-violet-800 hover:text-white'
                            }`}
                        >
                            {item.label}
                        </Link>
                    ))}
                </nav>
            </aside>
            <main className="flex-1 overflow-auto">
                <Outlet />
            </main>
        </div>
    );
}
