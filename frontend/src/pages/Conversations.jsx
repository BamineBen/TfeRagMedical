/**
 * Conversations.jsx — Historique des conversations RAG
 * ══════════════════════════════════════════════════════
 *
 * RÔLE
 * ─────
 * Affiche toutes les conversations médicales passées entre le médecin
 * et le LLM RAG. Permet de relire, rechercher et supprimer des échanges.
 *
 * DONNÉES
 * ────────
 *   GET /conversations?page=1&page_size=20 → liste paginée
 *   GET /conversations/{id}/messages       → messages d'une conversation
 *   DELETE /conversations/{id}             → suppression
 *
 * AFFICHAGE
 * ──────────
 *   - Vue liste    : titre, date, nombre de messages
 *   - Vue détail   : messages en bulles (user | assistant)
 *                    ReactMarkdown pour le rendu du Markdown LLM
 *   - Impression   : window.print() pour sortie papier
 *
 * RECHERCHE
 * ──────────
 * Filtre local côté frontend sur le titre de la conversation.
 * (Les 20 dernières conversations sont chargées en une fois.)
 */
import { useState, useEffect } from 'react';
import { MessageSquare, Search, ChevronRight, X, Printer, Trash2, ArrowLeft, Clock, User } from 'lucide-react';
import api from '../api/client';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

function formatDate(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleString('fr-FR', {
        day: '2-digit', month: '2-digit', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
    });
}

function StatusBadge({ status }) {
    const map = {
        active:   'bg-emerald-50 text-emerald-700',
        closed:   'bg-gray-100 text-gray-500',
        archived: 'bg-amber-50 text-amber-600',
    };
    return (
        <span className={`text-[9px] font-bold px-2 py-0.5 rounded-full ${map[status] || 'bg-gray-100 text-gray-500'}`}>
            {status || '—'}
        </span>
    );
}

export default function Conversations() {
    const [conversations, setConversations] = useState([]);
    const [total, setTotal] = useState(0);
    const [page, setPage] = useState(1);
    const [search, setSearch] = useState('');
    const [loading, setLoading] = useState(true);
    const [selected, setSelected] = useState(null);
    const [messages, setMessages] = useState([]);
    const [loadingMsgs, setLoadingMsgs] = useState(false);

    const loadConversations = async (p = 1, q = search) => {
        setLoading(true);
        try {
            const params = { page: p, page_size: 20 };
            if (q) params.q = q;
            const res = await api.get('/conversations', { params });
            const data = res.data;
            setConversations(data.items || []);
            setTotal(data.total || 0);
        } catch (e) {
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { loadConversations(1, ''); }, []);

    const openConversation = async (conv) => {
        setSelected(conv);
        setLoadingMsgs(true);
        try {
            const res = await api.get(`/conversations/${conv.id}/messages`);
            setMessages(res.data || []);
        } catch (e) {
            setMessages([]);
        } finally {
            setLoadingMsgs(false);
        }
    };

    const deleteConversation = async (id, e) => {
        e.stopPropagation();
        if (!confirm('Supprimer cette conversation ?')) return;
        try {
            await api.delete(`/conversations/${id}`);
            setConversations(prev => prev.filter(c => c.id !== id));
            if (selected?.id === id) setSelected(null);
        } catch {
            alert('Erreur suppression');
        }
    };

    const handleSearch = (e) => {
        e.preventDefault();
        loadConversations(1, search);
    };

    const deleteAllConversations = async () => {
        if (!confirm(`Supprimer les ${total} conversation(s) ? Cette action est irréversible.`)) return;
        try {
            const res = await api.delete('/conversations/bulk/delete-all');
            setConversations([]);
            setTotal(0);
            setSelected(null);
            alert(res.data.message || 'Historique effacé.');
        } catch {
            alert('Erreur lors de la suppression.');
        }
    };

    const printConversation = () => {
        window.print();
    };

    // Thread view
    if (selected) {
        return (
            <div className="p-4 md:p-8 max-w-4xl mx-auto print:p-0">
                {/* Print header */}
                <div className="hidden print:block mb-6 border-b pb-4">
                    <h1 className="text-2xl font-bold font-serif italic">RAG.Med — Historique de conversation</h1>
                    <p className="text-sm opacity-60 mt-1">
                        Session : {selected.session_id} · {formatDate(selected.created_at)}
                        {selected.contact_name && ` · ${selected.contact_name}`}
                    </p>
                </div>

                {/* Nav bar (hidden on print) */}
                <div className="print:hidden flex items-center justify-between mb-6">
                    <button
                        onClick={() => setSelected(null)}
                        className="flex items-center gap-2 text-sm font-semibold opacity-60 hover:opacity-100 transition-opacity"
                    >
                        <ArrowLeft size={16} /> Retour
                    </button>
                    <button
                        onClick={printConversation}
                        className="flex items-center gap-2 px-4 py-2 bg-[#141414] text-white text-xs font-bold rounded-xl hover:bg-[#141414]/80 transition-colors"
                    >
                        <Printer size={14} /> Exporter PDF
                    </button>
                </div>

                {/* Conversation header */}
                <div className="bg-white border border-[#141414]/10 rounded-2xl p-6 mb-6 shadow-sm">
                    <div className="flex items-center gap-3 mb-2">
                        <div className="bg-[#141414]/5 p-2 rounded-xl">
                            <MessageSquare size={16} className="opacity-60" />
                        </div>
                        <div>
                            <p className="font-bold text-sm">
                                {selected.contact_name || `Session ${selected.session_id?.slice(0, 8)}...`}
                            </p>
                            <p className="text-[10px] opacity-40">{formatDate(selected.created_at)}</p>
                        </div>
                        <StatusBadge status={selected.status} />
                    </div>
                    <p className="text-[10px] font-mono opacity-30">ID: {selected.session_id}</p>
                </div>

                {/* Messages thread */}
                <div className="space-y-4">
                    {loadingMsgs ? (
                        <div className="flex items-center justify-center py-12 opacity-30">
                            <div className="w-5 h-5 border-2 border-[#141414] border-t-transparent rounded-full animate-spin" />
                        </div>
                    ) : messages.length === 0 ? (
                        <div className="text-center py-12 opacity-30">
                            <MessageSquare size={32} className="mx-auto mb-2" />
                            <p className="text-sm">Aucun message dans cette conversation</p>
                        </div>
                    ) : messages.map((msg, i) => (
                        <div key={msg.id || i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                            <div className={`max-w-[85%] rounded-2xl px-5 py-4 shadow-sm ${
                                msg.role === 'user'
                                    ? 'bg-[#141414] text-white'
                                    : 'bg-white border border-[#141414]/10'
                            }`}>
                                <div className="flex items-center gap-2 mb-2">
                                    <User size={11} className="opacity-40 flex-shrink-0" />
                                    <span className="text-[9px] font-mono uppercase tracking-widest opacity-40">
                                        {msg.role === 'user' ? 'Médecin' : 'RAG.Med AI'}
                                    </span>
                                    {msg.created_at && (
                                        <span className="text-[9px] opacity-30 ml-auto">
                                            {new Date(msg.created_at).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}
                                        </span>
                                    )}
                                </div>
                                {msg.role === 'assistant' ? (
                                    <div className="text-sm prose prose-sm max-w-none">
                                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                            {msg.content || ''}
                                        </ReactMarkdown>
                                    </div>
                                ) : (
                                    <p className="text-sm leading-relaxed">{msg.content}</p>
                                )}
                            </div>
                        </div>
                    ))}
                </div>

                {/* Print footer */}
                <div className="hidden print:block mt-8 pt-4 border-t text-xs opacity-40 text-center">
                    Généré par RAG.Med · {new Date().toLocaleDateString('fr-FR')}
                </div>
            </div>
        );
    }

    // List view
    return (
        <div className="p-4 md:p-8 max-w-5xl mx-auto space-y-6">
            {/* Header + search */}
            <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center justify-between">
                <div>
                    <p className="text-[9px] font-mono uppercase tracking-[0.3em] opacity-30">
                        Traçabilité médicale
                    </p>
                    <p className="text-sm font-semibold opacity-60">{total} conversation{total !== 1 ? 's' : ''} enregistrée{total !== 1 ? 's' : ''}</p>
                </div>
                <form onSubmit={handleSearch} className="flex gap-2">
                    <div className="relative">
                        <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 opacity-30" />
                        <input
                            value={search}
                            onChange={e => setSearch(e.target.value)}
                            placeholder="Rechercher..."
                            className="pl-8 pr-4 py-2 text-xs bg-white border border-[#141414]/15 rounded-xl w-52 focus:outline-none focus:ring-2 focus:ring-[#141414]/20"
                        />
                        {search && (
                            <button type="button" onClick={() => { setSearch(''); loadConversations(1, ''); }}
                                className="absolute right-2 top-1/2 -translate-y-1/2 opacity-40 hover:opacity-80">
                                <X size={12} />
                            </button>
                        )}
                    </div>
                    <button type="submit"
                        className="px-4 py-2 bg-[#141414] text-white text-xs font-bold rounded-xl hover:bg-[#141414]/80 transition-colors">
                        Filtrer
                    </button>
                </form>
                {total > 0 && (
                    <button
                        onClick={deleteAllConversations}
                        className="flex items-center gap-2 px-4 py-2 bg-red-50 text-red-600 text-xs font-bold rounded-xl border border-red-200 hover:bg-red-100 transition-colors"
                    >
                        <Trash2 size={13} /> Supprimer tout
                    </button>
                )}
            </div>

            {/* List */}
            <div className="bg-white border border-[#141414]/10 rounded-2xl shadow-sm overflow-hidden">
                {loading ? (
                    <div className="flex items-center justify-center py-16 opacity-30">
                        <div className="w-6 h-6 border-2 border-[#141414] border-t-transparent rounded-full animate-spin" />
                    </div>
                ) : conversations.length === 0 ? (
                    <div className="text-center py-16 opacity-30">
                        <MessageSquare size={36} className="mx-auto mb-3" />
                        <p className="text-sm font-semibold">Aucune conversation trouvée</p>
                    </div>
                ) : (
                    <div>
                        {/* Table header */}
                        <div className="grid grid-cols-[1fr_auto_auto_auto_auto] gap-4 px-6 py-3 border-b border-[#141414]/5 bg-[#141414]/2">
                            {['Session / Patient', 'Statut', 'Canal', 'Date', ''].map((h, i) => (
                                <span key={i} className="text-[9px] font-mono uppercase tracking-widest opacity-30">{h}</span>
                            ))}
                        </div>
                        {conversations.map((conv) => (
                            <div
                                key={conv.id}
                                onClick={() => openConversation(conv)}
                                className="grid grid-cols-[1fr_auto_auto_auto_auto] gap-4 px-6 py-4 border-b border-[#141414]/5 last:border-0 hover:bg-[#141414]/3 cursor-pointer transition-colors items-center"
                            >
                                <div className="min-w-0">
                                    <p className="text-sm font-semibold truncate">
                                        {conv.contact_name || `Session ${conv.session_id?.slice(0, 12)}...`}
                                    </p>
                                    <p className="text-[10px] opacity-40 font-mono truncate">{conv.session_id}</p>
                                </div>
                                <StatusBadge status={conv.status} />
                                <span className="text-[10px] font-mono opacity-40 uppercase">{conv.channel || 'web'}</span>
                                <div className="flex items-center gap-1 text-[10px] opacity-40">
                                    <Clock size={10} />
                                    <span>{formatDate(conv.last_message_at || conv.created_at)}</span>
                                </div>
                                <div className="flex items-center gap-1">
                                    <button
                                        onClick={(e) => deleteConversation(conv.id, e)}
                                        className="p-1.5 rounded-lg hover:bg-red-50 hover:text-red-500 opacity-30 hover:opacity-100 transition-all"
                                    >
                                        <Trash2 size={13} />
                                    </button>
                                    <ChevronRight size={14} className="opacity-30" />
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {/* Pagination */}
            {total > 20 && (
                <div className="flex justify-center gap-2">
                    {Array.from({ length: Math.ceil(total / 20) }, (_, i) => i + 1).slice(0, 5).map(p => (
                        <button
                            key={p}
                            onClick={() => { setPage(p); loadConversations(p); }}
                            className={`w-8 h-8 text-xs font-bold rounded-lg transition-colors ${
                                page === p ? 'bg-[#141414] text-white' : 'bg-white border border-[#141414]/10 hover:bg-[#141414]/5'
                            }`}
                        >
                            {p}
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
}
