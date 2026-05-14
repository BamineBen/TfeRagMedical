/**
 * AgentMedical.jsx : Interface de l'agent médical autonome.
 *
 * FLUX SSE :
 *   sendQuery() → POST /api/v1/agent/stream
 *   Pour chaque événement reçu :
 *     STEP_START           → afficher spinner
 *     STEP_COMPLETE        → afficher résultat (tableau RDV, interactions...)
 *     CONFIRMATION_REQUEST → afficher boutons Confirmer/Annuler
 *     ANSWER               → afficher intent final
 *     DONE                 → arrêter le stream
 *
 * CONFIRMATION :
 *   Clic Confirmer → POST /api/v1/agent/confirm {session_id, approved: true}
 *   Clic Annuler   → POST /api/v1/agent/confirm {session_id, approved: false}
 */
import { useState, useRef, useCallback } from 'react';
import {
    Wand2, Send, Loader2, CheckCircle, XCircle,
    Calendar, Pill, Search, AlertTriangle, Sparkles,
} from 'lucide-react';

/*  Constantes  */
const TOOL_META = {
    rag_query:         { label: 'Recherche dossier',   icon: Search,   color: '#6366f1' },
    calendar_read:     { label: 'Lecture calendrier',  icon: Calendar, color: '#0ea5e9' },
    calendar_write:    { label: 'Modification agenda', icon: Calendar, color: '#f59e0b' },
    interaction_check: { label: 'Vérification médicaments', icon: Pill, color: '#ef4444' },
};

const SEVERITY_COLORS = {
    LOW:      { bg: '#f0fdf4', border: '#86efac', text: '#166534' },
    MEDIUM:   { bg: '#fffbeb', border: '#fcd34d', text: '#92400e' },
    HIGH:     { bg: '#fff1f2', border: '#fca5a5', text: '#991b1b' },
    CRITICAL: { bg: '#fdf4ff', border: '#e879f9', text: '#701a75' },
};

/*  Générateur SSE  */
async function* agentStream(query, sessionId, llmMode, signal) {
    const token = localStorage.getItem('access_token');
    const res = await fetch('/api/v1/agent/stream', {
        method: 'POST',
        signal,
        headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ query, session_id: sessionId, llm_mode: llmMode }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const events = buf.split('\n\n');
        buf = events.pop();
        for (const ev of events) {
            const line = ev.split('\n').find(l => l.startsWith('data: '));
            if (!line) continue;
            try { yield JSON.parse(line.slice(6)); } catch (_) {}
        }
    }
}

/*  PlanningCalendar  */
function PlanningCalendar({ data, doctorName }) {
    if (!data?.events) return null;

    const HOUR_PX  = 56;
    const DAY_START = 8;

    const toPx = (iso) => {
        const d = new Date(iso);
        return ((d.getHours() - DAY_START) * 60 + d.getMinutes()) / 60 * HOUR_PX;
    };
    const durPx = (s, e) => {
        const mins = (new Date(e) - new Date(s)) / 60000;
        return Math.max(24, (mins / 60) * HOUR_PX);
    };

    const hours = Array.from({ length: 10 }, (_, i) => i + DAY_START);

    return (
        <div className="border border-gray-200 rounded-xl overflow-hidden bg-white">
            <div className="bg-[#141414] text-white px-4 py-2 text-sm font-mono">
                <Calendar size={14} className="inline mr-2" />
                {doctorName} — {data.date}
            </div>
            <div className="flex">
                {/* Heures */}
                <div className="w-12 flex-shrink-0 border-r border-gray-100">
                    {hours.map(h => (
                        <div key={h} style={{ height: HOUR_PX }} className="flex items-start justify-end pr-2 pt-1">
                            <span className="text-[10px] text-gray-400">{h}h</span>
                        </div>
                    ))}
                </div>
                {/* Grille */}
                <div className="flex-1 relative" style={{ height: `${10 * HOUR_PX}px` }}>
                    {/* Lignes horaires */}
                    {hours.map(h => (
                        <div key={h} style={{ top: (h - DAY_START) * HOUR_PX }}
                             className="absolute w-full border-t border-gray-100" />
                    ))}
                    {/* RDV existants */}
                    {data.events.map((ev, i) => (
                        <div key={i} style={{
                            position: 'absolute', top: toPx(ev.start),
                            height: Math.max(durPx(ev.start, ev.end), 24),
                            left: '4px', right: '4px',
                            backgroundColor: '#3b82f6', borderRadius: 6,
                        }} className="text-white text-[10px] px-2 py-1 overflow-hidden">
                            {ev.title}
                        </div>
                    ))}
                    {/* Créneaux libres */}
                    {data.free_slots?.map((slot, i) => (
                        <div key={`slot-${i}`} style={{
                            position: 'absolute', top: toPx(slot.start),
                            height: Math.max(durPx(slot.start, slot.end), 24),
                            left: '4px', right: '4px',
                            backgroundColor: '#d1fae5', border: '1px dashed #059669',
                            borderRadius: 6,
                        }} className="text-green-700 text-[10px] px-2 py-1">
                            Libre {slot.duration_minutes}min
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}

/*  ResultView  */
function ResultView({ toolName, data }) {
    if (!data) return null;

    if (toolName === 'interaction_check' && data.has_interaction) {
        const colors = SEVERITY_COLORS[data.severity] || SEVERITY_COLORS.MEDIUM;
        return (
            <div style={{ backgroundColor: colors.bg, border: `1px solid ${colors.border}` }}
                 className="rounded-xl p-4 mt-2">
                <div className="flex items-center gap-2 mb-2">
                    <AlertTriangle size={16} style={{ color: colors.text }} />
                    <span className="font-semibold text-sm" style={{ color: colors.text }}>
                        Interaction {data.severity}
                    </span>
                </div>
                <p className="text-sm text-gray-700 mb-2">{data.description}</p>
                {data.recommendations?.map((r, i) => (
                    <p key={i} className="text-xs text-gray-600">• {r}</p>
                ))}
            </div>
        );
    }

    if (toolName === 'interaction_check' && !data.has_interaction) {
        return (
            <div className="bg-green-50 border border-green-200 rounded-xl p-3 mt-2 text-sm text-green-800">
                ✅ Aucune interaction médicamenteuse détectée.
            </div>
        );
    }

    if (toolName === 'rag_query' && data.answer) {
        return (
            <div className="bg-gray-50 rounded-xl p-3 mt-2 text-sm text-gray-700 max-h-40 overflow-y-auto">
                {data.answer.substring(0, 400)}...
            </div>
        );
    }

    return null;
}

/*  Composant principal  */
export default function AgentMedical() {
    const [query,     setQuery]     = useState('');
    const [events,    setEvents]    = useState([]);
    const [loading,   setLoading]   = useState(false);
    const [sessionId, setSessionId] = useState(null);
    const [calData,   setCalData]   = useState(null);
    const [calDoctor, setCalDoctor] = useState('');
    const abortRef = useRef(null);

    const sendQuery = useCallback(async () => {
        if (!query.trim() || loading) return;

        const sid = `sess_${Date.now()}`;
        setSessionId(sid);
        setEvents([{ type: 'USER_QUERY', data: { text: query } }]);
        setLoading(true);
        setCalData(null);
        const q = query;
        setQuery('');

        abortRef.current = new AbortController();

        try {
            for await (const event of agentStream(q, sid, 'gemini', abortRef.current.signal)) {
                if (event.type === 'DONE') break;
                setEvents(prev => {
                    const last = prev[prev.length - 1];
                    if (last?.type === 'STEP_START' && last.step_name === event.step_name && event.type === 'STEP_COMPLETE') {
                        return [...prev.slice(0, -1), event];
                    }
                    return [...prev, event];
                });
                // Mettre à jour le calendrier si c'est un résultat calendar_read
                if (event.type === 'STEP_COMPLETE' && event.step_name === 'calendar_read') {
                    setCalData(event.data);
                    setCalDoctor(event.data?.doctor || '');
                }
            }
        } catch (e) {
            if (e.name !== 'AbortError') {
                setEvents(prev => [...prev, { type: 'ERROR', data: { message: e.message } }]);
            }
        } finally {
            setLoading(false);
        }
    }, [query, loading]);

    const handleConfirm = async (approved) => {
        const token = localStorage.getItem('access_token');
        const res = await fetch('/api/v1/agent/confirm', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
            body: JSON.stringify({ session_id: sessionId, approved }),
        });
        const data = await res.json();
        setEvents(prev => [...prev, {
            type: 'STEP_COMPLETE',
            step_name: 'calendar_write',
            data: data.data || { message: data.message },
        }]);
        if (data.data?.events) {
            setCalData(data.data);
        }
    };

    return (
        <div className="h-full flex flex-col bg-[#F4F4F2]">
            {/* Header */}
            <div className="bg-[#141414] text-white px-6 py-4 flex items-center gap-4 flex-shrink-0">
                <Wand2 size={20} />
                <div>
                    <p className="text-[10px] font-mono uppercase tracking-widest text-gray-400">Agent Médical</p>
                    <p className="text-sm font-bold">Autonome Multi-Outils</p>
                </div>
            </div>

            {/* Corps */}
            <div className="flex-1 flex overflow-hidden">
                {/* Colonne gauche — Timeline */}
                <div className="flex-1 flex flex-col overflow-hidden p-4 gap-3">
                    <div className="flex-1 overflow-y-auto space-y-3">
                        {events.length === 0 && (
                            <div className="h-full flex items-center justify-center text-gray-400 text-sm">
                                <div className="text-center">
                                    <Wand2 size={40} className="mx-auto mb-3 opacity-20" />
                                    <p className="font-medium">Agent médical prêt</p>
                                    <p className="text-xs mt-1">Ex: "Planning Dr Martin demain" ou "Interactions warfarine aspirine"</p>
                                </div>
                            </div>
                        )}
                        {events.map((ev, i) => {
                            if (ev.type === 'USER_QUERY') return (
                                <div key={i} className="flex justify-end">
                                    <div className="bg-[#141414] text-white rounded-2xl rounded-tr-sm px-4 py-2 text-sm max-w-xs">
                                        {ev.data.text}
                                    </div>
                                </div>
                            );

                            const meta = TOOL_META[ev.step_name] || { label: ev.step_name, icon: Sparkles, color: '#6b7280' };
                            const Icon = meta.icon;

                            if (ev.type === 'STEP_START') return (
                                <div key={i} className="flex items-center gap-3 text-sm text-gray-500">
                                    <div style={{ color: meta.color }} className="flex-shrink-0">
                                        <Icon size={16} />
                                    </div>
                                    <span>{meta.label}...</span>
                                    <Loader2 size={14} className="animate-spin" />
                                </div>
                            );

                            if (ev.type === 'STEP_COMPLETE') return (
                                <div key={i} className="bg-white rounded-2xl rounded-tl-sm p-4 shadow-sm border border-gray-100">
                                    <div className="flex items-center gap-2 mb-2">
                                        <Icon size={14} style={{ color: meta.color }} />
                                        <span className="text-xs font-semibold text-gray-600">{meta.label}</span>
                                        {ev.execution_time_ms && (
                                            <span className="text-xs text-gray-400 ml-auto">{ev.execution_time_ms}ms</span>
                                        )}
                                    </div>
                                    <ResultView toolName={ev.step_name} data={ev.data} />
                                </div>
                            );

                            if (ev.type === 'CONFIRMATION_REQUEST') return (
                                <div key={i} className="bg-amber-50 border border-amber-200 rounded-2xl p-4">
                                    <p className="text-sm font-semibold text-amber-800 mb-1">Confirmation requise</p>
                                    <p className="text-sm text-amber-700 mb-3">{ev.data?.message}</p>
                                    <div className="flex gap-2">
                                        <button onClick={() => handleConfirm(true)}
                                                className="flex items-center gap-1 px-4 py-2 bg-[#141414] text-white text-sm rounded-xl hover:bg-gray-800">
                                            <CheckCircle size={14} /> Confirmer
                                        </button>
                                        <button onClick={() => handleConfirm(false)}
                                                className="flex items-center gap-1 px-4 py-2 border border-gray-200 text-sm rounded-xl hover:bg-gray-50">
                                            <XCircle size={14} /> Annuler
                                        </button>
                                    </div>
                                </div>
                            );

                            if (ev.type === 'ANSWER') return (
                                <div key={i} className="text-xs text-gray-400 flex items-center gap-2">
                                    <CheckCircle size={12} className="text-green-500" />
                                    Terminé — {ev.data?.intent}
                                </div>
                            );

                            if (ev.type === 'ERROR') return (
                                <div key={i} className="bg-red-50 border border-red-200 rounded-xl p-3 text-sm text-red-700">
                                    ❌ {ev.data?.message}
                                </div>
                            );

                            return null;
                        })}
                    </div>

                    {/* Zone de saisie */}
                    <div className="flex gap-2 flex-shrink-0">
                        <input
                            value={query}
                            onChange={e => setQuery(e.target.value)}
                            onKeyDown={e => e.key === 'Enter' && !e.shiftKey && sendQuery()}
                            placeholder="Ex: Planning Dr Martin demain / Interactions warfarine aspirine..."
                            className="flex-1 border border-gray-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#141414]/20"
                        />
                        <button onClick={sendQuery} disabled={loading || !query.trim()}
                                className="bg-[#141414] text-white px-4 py-2.5 rounded-xl hover:bg-gray-800 disabled:opacity-40 flex-shrink-0">
                            {loading ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
                        </button>
                    </div>
                </div>

                {/* Colonne droite — Calendrier */}
                {calData && (
                    <div className="w-72 p-4 border-l border-gray-200 overflow-y-auto flex-shrink-0">
                        <PlanningCalendar data={calData} doctorName={calDoctor} />
                    </div>
                )}
            </div>
        </div>
    );
}