/**
 * SystemConfig.jsx — Configuration système (admin)
 * ══════════════════════════════════════════════════
 *
 * RÔLE
 * ─────
 * Interface d'administration pour consulter et modifier les paramètres
 * de la plateforme RAG : LLM actif, seuils RAG, clés API, GPU.
 *
 * DONNÉES
 * ────────
 *   GET  /admin/settings         → liste des paramètres clé/valeur
 *   PUT  /admin/settings/{key}   → modifier un paramètre
 *   GET  /dashboard/health       → état de santé des services
 *   POST /dashboard/gpu/start    → démarrer le GPU (si disponible)
 *   POST /dashboard/gpu/stop     → arrêter le GPU
 *
 * PARAMÈTRES AFFICHÉS
 * ────────────────────
 *   • LLM     : modèle actif, température, max_tokens, contexte
 *   • RAG     : TOP_K, reranker, threshold, chunk_size
 *   • API     : clés Groq / OpenRouter (masquées à l'affichage)
 *   • Serveur : RAM, CPU, espace disque
 *
 * ACCÈS
 * ──────
 * Réservé aux utilisateurs avec rôle "admin".
 * Les médecins (rôle "doctor") ne voient pas ce menu.
 */
import { useState, useEffect, useCallback } from 'react';
import { Server, Brain, Database, ShieldCheck, Zap, Cpu, RefreshCw, Power, PowerOff, Loader2 } from 'lucide-react';
import api from '../api/client';

function SettingRow({ label, description, value }) {
    return (
        <div className="flex justify-between items-start pb-6 border-b border-[#141414]/5 last:border-0 last:pb-0">
            <div className="max-w-md">
                <h4 className="text-sm font-bold mb-1">{label}</h4>
                <p className="text-xs opacity-40 leading-relaxed">{description}</p>
            </div>
            <div className="bg-[#141414]/5 px-4 py-2 rounded-lg text-[10px] font-mono font-bold uppercase tracking-widest flex-shrink-0 ml-4">
                {value}
            </div>
        </div>
    );
}

function GpuControlRow({ gpu, onRefresh }) {
    const [acting, setActing] = useState(false);

    const status = gpu?.status || 'off';
    const isReady = status === 'ready';
    const isStarting = status === 'starting';
    const isOff = status === 'off';
    const isError = status === 'error';

    const idleSeconds = gpu?.idle_seconds || 0;
    const idleMin = Math.floor(idleSeconds / 60);
    const idleSec = idleSeconds % 60;

    const handleStart = async () => {
        setActing(true);
        try {
            await api.post('/dashboard/gpu/start');
            setTimeout(onRefresh, 1000);
        } catch (e) {
            console.error('GPU start failed', e);
        } finally {
            setActing(false);
        }
    };

    const handleStop = async () => {
        setActing(true);
        try {
            await api.post('/dashboard/gpu/stop');
            setTimeout(onRefresh, 1000);
        } catch (e) {
            console.error('GPU stop failed', e);
        } finally {
            setActing(false);
        }
    };

    const statusLabel = isReady
        ? 'Actif'
        : isStarting
            ? 'Demarrage...'
            : isError
                ? 'Erreur'
                : 'Eteint';

    const statusColor = isReady
        ? 'bg-emerald-500'
        : isStarting
            ? 'bg-amber-400'
            : isError
                ? 'bg-red-500'
                : 'bg-[#141414]/20';

    return (
        <div className="pb-6 border-b border-[#141414]/5 last:border-0 last:pb-0">
            <div className="flex justify-between items-start">
                <div className="max-w-md">
                    <h4 className="text-sm font-bold mb-1">GPU Instance</h4>
                    <p className="text-xs opacity-40 leading-relaxed">
                        Vast.ai 2x RTX 3090 · Auto-shutdown apres 10 min d'inactivite
                    </p>
                </div>

                {/* Status badge */}
                <div className="flex items-center gap-2 flex-shrink-0 ml-4">
                    <div className={`w-2 h-2 rounded-full ${statusColor} ${isStarting ? 'animate-pulse' : ''}`} />
                    <span className="text-[10px] font-mono font-bold uppercase tracking-widest">
                        {statusLabel}
                    </span>
                </div>
            </div>

            {/* Controls */}
            <div className="mt-4 flex items-center gap-3">
                {/* Start button */}
                <button
                    onClick={handleStart}
                    disabled={acting || isReady || isStarting}
                    className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold transition-all ${
                        isOff || isError
                            ? 'bg-emerald-500 text-white hover:bg-emerald-600 shadow-sm'
                            : 'bg-[#141414]/5 text-[#141414]/30 cursor-not-allowed'
                    }`}
                >
                    {acting && !isReady ? (
                        <Loader2 size={13} className="animate-spin" />
                    ) : (
                        <Power size={13} />
                    )}
                    Demarrer le GPU
                </button>

                {/* Stop button */}
                <button
                    onClick={handleStop}
                    disabled={acting || isOff}
                    className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold transition-all ${
                        isReady || isStarting
                            ? 'bg-red-500 text-white hover:bg-red-600 shadow-sm'
                            : 'bg-[#141414]/5 text-[#141414]/30 cursor-not-allowed'
                    }`}
                >
                    {acting && isReady ? (
                        <Loader2 size={13} className="animate-spin" />
                    ) : (
                        <PowerOff size={13} />
                    )}
                    Arreter le GPU
                </button>

                {/* Idle info */}
                {isReady && idleSeconds > 0 && (
                    <span className="text-[10px] text-[#141414]/40 font-mono ml-auto">
                        Inactif depuis {idleMin > 0 ? `${idleMin}m ` : ''}{idleSec}s
                        {' '}/ {gpu?.idle_shutdown_minutes || 10}m
                    </span>
                )}

                {isError && gpu?.error && (
                    <span className="text-[10px] text-red-500 font-mono ml-auto truncate max-w-xs">
                        {gpu.error}
                    </span>
                )}
            </div>
        </div>
    );
}

export default function SystemConfig() {
    const [health, setHealth] = useState(null);
    const [refreshing, setRefreshing] = useState(false);

    const load = useCallback(async () => {
        setRefreshing(true);
        try {
            const res = await api.get('/dashboard/health');
            setHealth(res.data);
        } catch (e) {
        } finally {
            setRefreshing(false);
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    // Auto-refresh toutes les 30s quand le GPU est actif
    useEffect(() => {
        const gpuStatus = health?.gpu?.status;
        if (gpuStatus === 'ready' || gpuStatus === 'starting') {
            const interval = setInterval(load, 30000);
            return () => clearInterval(interval);
        }
    }, [health?.gpu?.status, load]);

    return (
        <div className="p-10 max-w-4xl mx-auto space-y-8">
            {/* Architecture config */}
            <div className="bg-white border border-[#141414]/10 rounded-3xl p-10 shadow-sm">
                <div className="flex items-center justify-between mb-10">
                    <h3 className="text-[10px] font-mono uppercase tracking-[0.4em] opacity-40">
                        System Architecture Configuration
                    </h3>
                    <button
                        onClick={load}
                        disabled={refreshing}
                        className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-widest opacity-40 hover:opacity-70 transition-opacity disabled:opacity-20"
                    >
                        <RefreshCw size={12} className={refreshing ? 'animate-spin' : ''} />
                        Refresh
                    </button>
                </div>

                <div className="space-y-6">
                    <SettingRow
                        label="Primary LLM Engine"
                        description="Qwen3.5 35B sur GPU (2x RTX 3090, 48GB VRAM) via Vast.ai · 100% local, aucune donnee externe"
                        value={health?.ollama?.model || 'qwen3.5:35b'}
                    />
                    <SettingRow
                        label="Vector Search Engine"
                        description="PostgreSQL + pgvector avec recherche hybride (vecteur + keywords) et fusion RRF"
                        value={health?.database?.status === 'ok' ? 'Actif' : 'Erreur'}
                    />
                    <SettingRow
                        label="Reranking Model"
                        description="Cross-encoder multilingue: cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
                        value="Active"
                    />
                    <SettingRow
                        label="Embedding Model"
                        description="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 · dimensions: 384"
                        value="MiniLM-L12"
                    />

                    {/* GPU Control — interactive */}
                    <GpuControlRow gpu={health?.gpu} onRefresh={load} />

                    <SettingRow
                        label="Data Privacy Mode"
                        description="Chiffrement bout-en-bout pour tous les dossiers patients · RGPD compliant"
                        value="Maximum"
                    />
                </div>
            </div>

            {/* RAG Pipeline params */}
            <div className="bg-white border border-[#141414]/10 rounded-3xl p-10 shadow-sm">
                <h3 className="text-[10px] font-mono uppercase tracking-[0.4em] mb-10 opacity-40">
                    RAG Pipeline Parameters
                </h3>
                <div className="grid grid-cols-2 gap-6">
                    {[
                        { label: 'Top-K Retrieval', value: '15 chunks', icon: Database },
                        { label: 'Reranker Top-K', value: '5 chunks', icon: Brain },
                        { label: 'Chunk Size', value: '800 tokens', icon: Server },
                        { label: 'Chunk Overlap', value: '150 tokens', icon: Server },
                        { label: 'Max Context', value: '3500 chars', icon: Cpu },
                        { label: 'Similarity Threshold', value: '0.15', icon: Zap },
                        { label: 'Temperature', value: '0.0', icon: ShieldCheck },
                        { label: 'Max Tokens Output', value: '1024', icon: ShieldCheck },
                    ].map(({ label, value, icon: Icon }, i) => (
                        <div key={i} className="flex items-center gap-3 p-4 bg-[#141414]/3 rounded-xl">
                            <div className="p-2 bg-white rounded-lg">
                                <Icon size={14} className="opacity-40" />
                            </div>
                            <div>
                                <div className="text-[10px] opacity-40 uppercase tracking-widest font-bold">{label}</div>
                                <div className="text-sm font-bold font-mono">{value}</div>
                            </div>
                        </div>
                    ))}
                </div>
            </div>

            {/* System resources */}
            {health?.system && (
                <div className="bg-white border border-[#141414]/10 rounded-3xl p-10 shadow-sm">
                    <h3 className="text-[10px] font-mono uppercase tracking-[0.4em] mb-8 opacity-40">
                        System Resources
                    </h3>
                    <div className="space-y-5">
                        <div>
                            <div className="flex justify-between items-center mb-2">
                                <div className="flex items-center gap-2">
                                    <Cpu size={13} className="opacity-40" />
                                    <span className="text-xs font-bold opacity-60">CPU Usage</span>
                                </div>
                                <span className="text-xs font-mono font-bold">{health.system.cpu_percent?.toFixed(1)}%</span>
                            </div>
                            <div className="h-1.5 bg-[#141414]/8 rounded-full overflow-hidden">
                                <div
                                    className="h-full bg-[#141414] rounded-full transition-all"
                                    style={{ width: `${health.system.cpu_percent || 0}%` }}
                                />
                            </div>
                        </div>
                        <div>
                            <div className="flex justify-between items-center mb-2">
                                <div className="flex items-center gap-2">
                                    <Server size={13} className="opacity-40" />
                                    <span className="text-xs font-bold opacity-60">RAM Usage</span>
                                </div>
                                <span className="text-xs font-mono font-bold">
                                    {health.system.ram_used_gb}GB / {health.system.ram_total_gb}GB
                                </span>
                            </div>
                            <div className="h-1.5 bg-[#141414]/8 rounded-full overflow-hidden">
                                <div
                                    className={`h-full rounded-full transition-all ${
                                        health.system.ram_percent > 85
                                            ? 'bg-red-500'
                                            : health.system.ram_percent > 70
                                                ? 'bg-amber-500'
                                                : 'bg-emerald-500'
                                    }`}
                                    style={{ width: `${health.system.ram_percent || 0}%` }}
                                />
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
