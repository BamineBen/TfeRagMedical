/**
 * Dashboard.jsx — Tableau de bord principal (admin)
 * ════════════════════════════════════════════════════
 *
 * DONNÉES AFFICHÉES
 * ──────────────────
 *   stats          → GET /dashboard/stats     : totaux documents, chunks, messages...
 *   recentDocs     → GET /documents           : 5 derniers documents indexés
 *   health         → GET /dashboard/health    : état des services (DB, LLM, CPU, RAM)
 *
 * POLLING
 * ────────
 * Toutes les 15 secondes pour refléter les uploads en cours en temps réel.
 * Le cleanup `clearInterval` évite les fuites mémoire quand on quitte la page.
 *
 * COMPOSANTS INTERNES
 * ────────────────────
 *   StatCard        → carte chiffre clé (Documents, Chunks, Messages)
 *   DocStatusBadge  → badge coloré selon le statut d'indexation
 *   HealthItem      → ligne de statut d'un service (OK / Erreur)
 */
import { useState, useEffect } from 'react';
import { Activity, Cpu, Database, FileText, MessageSquare, Users, Wifi } from 'lucide-react';
import api from '../api/client';
import { extractPatientName } from '../utils/patient';

function StatCard({ label, value, sub, icon: Icon, category }) {
    return (
        <div className="bg-white border border-[#141414]/10 p-4 md:p-8 rounded-2xl shadow-sm group hover:-translate-y-1 transition-all duration-300 cursor-default">
            <div className="flex justify-between items-start mb-3 md:mb-5">
                <div className="p-2 md:p-3 bg-[#141414]/5 rounded-xl group-hover:bg-[#141414] group-hover:text-white transition-colors">
                    <Icon size={18} />
                </div>
                <span className="text-[9px] font-mono opacity-20 uppercase tracking-widest">{category}</span>
            </div>
            <div className="text-2xl md:text-4xl font-serif italic font-bold mb-1">{value ?? 0}</div>
            {sub && <div className="text-[10px] opacity-40 mb-1">{sub}</div>}
            <div className="text-[10px] font-mono uppercase tracking-[0.3em] opacity-40 font-bold">{label}</div>
        </div>
    );
}

function DocStatusBadge({ status }) {
    const map = {
        completed: { cls: 'bg-emerald-50 text-emerald-700', label: 'Traité' },
        processing: { cls: 'bg-amber-50 text-amber-700', label: 'En cours' },
        pending: { cls: 'bg-blue-50 text-blue-700', label: 'En attente' },
        failed: { cls: 'bg-red-50 text-red-700', label: 'Erreur' },
    };
    const cfg = map[status?.toLowerCase()] || { cls: 'bg-gray-50 text-gray-600', label: status || '—' };
    return (
        <span className={`text-[9px] font-bold px-2 py-0.5 rounded-full flex-shrink-0 ${cfg.cls}`}>{cfg.label}</span>
    );
}

function HealthItem({ label, status }) {
    const cfg = {
        ok: { dot: 'bg-emerald-500', text: 'OK', glow: 'shadow-[0_0_8px_rgba(16,185,129,0.4)]' },
        configured: { dot: 'bg-emerald-400', text: 'Configuré', glow: '' },
        not_configured: { dot: 'bg-amber-400', text: 'N/A', glow: '' },
        error: { dot: 'bg-red-500', text: 'Erreur', glow: '' },
    }[status] || { dot: 'bg-gray-300', text: status || '—', glow: '' };
    return (
        <div className="flex items-center justify-between py-3 border-b border-[#141414]/5 last:border-0">
            <span className="text-xs font-semibold opacity-70">{label}</span>
            <div className="flex items-center gap-2.5">
                <span className="text-[9px] font-mono uppercase opacity-40 font-bold">{cfg.text}</span>
                <div className={`w-2 h-2 rounded-full flex-shrink-0 ${cfg.dot} ${cfg.glow}`} />
            </div>
        </div>
    );
}

export default function Dashboard() {
    const [stats, setStats] = useState(null);
    const [recentDocs, setRecentDocs] = useState([]);
    const [health, setHealth] = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const load = async () => {
            try {
                const [sRes, dRes, hRes] = await Promise.all([
                    api.get('/dashboard/stats'),
                    api.get('/documents'),
                    api.get('/dashboard/health'),
                ]);
                setStats(sRes.data);
                const docs = dRes.data?.items || dRes.data?.documents || (Array.isArray(dRes.data) ? dRes.data : []);
                setRecentDocs(docs.slice(0, 5));
                setHealth(hRes.data);
            } catch (e) {
            } finally {
                setLoading(false);
            }
        };
        load();
        const interval = setInterval(load, 15000);
        return () => clearInterval(interval);
    }, []);

    if (loading) {
        return (
            <div className="p-12 flex items-center justify-center h-64">
                <div className="flex gap-1.5 opacity-30">
                    <span className="loading-dot" /><span className="loading-dot" /><span className="loading-dot" />
                </div>
            </div>
        );
    }

    const docsTotal = stats?.documents?.total ?? 0;
    const docsProcessed = stats?.documents?.processed ?? 0;
    const docsPending = Math.max(0, docsTotal - docsProcessed);

    return (
        <div className="p-4 md:p-10 max-w-7xl mx-auto space-y-6">
            {/* Stat cards */}
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 md:gap-6">
                <StatCard
                    label="Dossiers patients"
                    value={docsTotal}
                    sub={`${docsProcessed} traités · ${docsPending} en attente`}
                    icon={Database}
                    category="Documents"
                />
                <StatCard
                    label="Messages IA"
                    value={stats?.messages?.total ?? 0}
                    sub={`${stats?.conversations?.total ?? 0} conversation${(stats?.conversations?.total ?? 0) !== 1 ? 's' : ''}`}
                    icon={MessageSquare}
                    category="Requêtes"
                />
                <div className="col-span-2 sm:col-span-1">
                    <StatCard
                        label="Chunks vectorisés"
                        value={(stats?.chunks?.total ?? 0).toLocaleString('fr-FR')}
                        sub="index FAISS en mémoire"
                        icon={Database}
                        category="Vectoriel"
                    />
                </div>
            </div>

            {/* Recent docs + Health */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Recent documents */}
                <div className="bg-white border border-[#141414]/10 rounded-2xl p-6 md:p-8 shadow-sm">
                    <h3 className="text-[10px] font-mono uppercase tracking-widest mb-6 opacity-40">Dossiers récents</h3>
                    <div>
                        {recentDocs.length > 0 ? recentDocs.map((doc, i) => {
                            const name = extractPatientName(doc.title || doc.filename || '');
                            return (
                                <div key={doc.id || i} className="flex gap-3 items-center py-3.5 border-b border-[#141414]/5 last:border-0">
                                    <div className="bg-[#141414]/5 p-2 rounded-lg flex-shrink-0">
                                        <FileText size={14} className="opacity-60" />
                                    </div>
                                    <div className="flex-1 min-w-0">
                                        <p className="text-xs font-bold truncate">{name}</p>
                                        <p className="text-[10px] opacity-40 truncate">
                                            {doc.chunk_count ?? '?'} chunks
                                            {doc.created_at && ` · ${new Date(doc.created_at).toLocaleDateString('fr-FR')}`}
                                        </p>
                                    </div>
                                    <DocStatusBadge status={doc.status} />
                                </div>
                            );
                        }) : (
                            <p className="text-sm italic opacity-30 py-4">Aucun document indexé</p>
                        )}
                    </div>
                </div>

                {/* System Health */}
                <div className="bg-white border border-[#141414]/10 rounded-2xl p-6 md:p-8 shadow-sm">
                    <h3 className="text-[10px] font-mono uppercase tracking-widest mb-6 opacity-40">System Health</h3>
                    {health ? (
                        <div>
                            <div className="mb-5">
                                <HealthItem label="LLM / Ollama" status={health.ollama?.status || 'error'} />
                                <HealthItem label="Base vectorielle (pgvector)" status={health.database?.status || 'error'} />
                                <HealthItem label="Gemini API" status={health.gemini?.status || 'not_configured'} />
                            </div>
                            {health.system && (
                                <div className="bg-[#141414]/3 rounded-xl p-4 space-y-3">
                                    <div>
                                        <div className="flex justify-between items-center mb-1.5">
                                            <div className="flex items-center gap-2">
                                                <Cpu size={12} className="opacity-40" />
                                                <span className="text-[10px] opacity-50 uppercase tracking-wide font-bold">CPU</span>
                                            </div>
                                            <span className="text-xs font-mono font-bold">{health.system.cpu_percent?.toFixed(1)}%</span>
                                        </div>
                                        <div className="h-1.5 bg-[#141414]/8 rounded-full overflow-hidden">
                                            <div className="h-full bg-[#141414] rounded-full transition-all" style={{ width: `${health.system.cpu_percent || 0}%` }} />
                                        </div>
                                    </div>
                                    <div>
                                        <div className="flex justify-between items-center mb-1.5">
                                            <div className="flex items-center gap-2">
                                                <Wifi size={12} className="opacity-40" />
                                                <span className="text-[10px] opacity-50 uppercase tracking-wide font-bold">RAM</span>
                                            </div>
                                            <span className="text-xs font-mono font-bold">
                                                {health.system.ram_used_gb}GB / {health.system.ram_total_gb}GB ({health.system.ram_percent}%)
                                            </span>
                                        </div>
                                        <div className="h-1.5 bg-[#141414]/8 rounded-full overflow-hidden">
                                            <div className={`h-full rounded-full transition-all ${
                                                health.system.ram_percent > 85 ? 'bg-red-500' :
                                                health.system.ram_percent > 70 ? 'bg-amber-500' : 'bg-emerald-500'
                                            }`} style={{ width: `${health.system.ram_percent || 0}%` }} />
                                        </div>
                                    </div>
                                </div>
                            )}
                        </div>
                    ) : (
                        <p className="text-sm italic opacity-30">Chargement...</p>
                    )}
                </div>
            </div>

            {/* Quick stats bar */}
            <div className="bg-white border border-[#141414]/10 rounded-2xl p-4 md:p-6 shadow-sm">
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 md:gap-0 md:divide-x divide-[#141414]/5">
                    {[
                        { label: 'Utilisateurs', value: stats?.users?.total ?? 0, icon: Users },
                        { label: 'Docs traités', value: docsProcessed, icon: FileText },
                        { label: 'Chunks vectorisés', value: (stats?.chunks?.total ?? 0).toLocaleString('fr-FR'), icon: Database },
                        { label: 'Conv. actives', value: stats?.conversations?.active ?? 0, icon: Activity },
                    ].map(({ label, value, icon: Icon }, i) => (
                        <div key={i} className="md:px-6 md:first:pl-0 md:last:pr-0 flex items-center gap-3">
                            <div className="p-2 bg-[#141414]/5 rounded-lg">
                                <Icon size={14} className="opacity-60" />
                            </div>
                            <div>
                                <div className="text-xl font-serif italic font-bold">{value}</div>
                                <div className="text-[9px] font-mono uppercase tracking-widest opacity-35">{label}</div>
                            </div>
                        </div>
                    ))}
                </div>
            </div>

        </div>
    );
}
