/**
 * AgentMedical.jsx — Agent Médical Autonome Multi-Outils (Section 5)
 * ══════════════════════════════════════════════════════════════════
 * Interface SSE : affiche les étapes de l'agent en temps réel,
 * confirmation RDV, calendrier visuel, vérification d'interactions.
 */
import { useState, useEffect, useRef, useMemo } from 'react';
import { useLocation } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
    Send, Loader2, Bot, CheckCircle2, XCircle, AlertCircle,
    Calendar, FileSearch, FileText, CalendarPlus, Clock,
    Wand2, ChevronRight, ChevronDown, Trash2, PlayCircle,
    Link2, Unlink, User, Stethoscope, Sparkles, Zap, Cpu,
    ArrowRight, ExternalLink, Info, Activity, Pill, ShieldAlert,
    Cloud, Server, Lock,
} from 'lucide-react';

/* ── Helpers ──────────────────────────────────────────────────────── */
const genSessionId = () =>
    'sess_' + Math.random().toString(36).slice(2, 10) + '_' + Date.now();

const TOOL_META = {
    rag_query:         { label: 'Recherche dossier patient',  icon: FileSearch,   color: '#0284c7', bg: '#f0f9ff', border: '#bae6fd', pkg: 'existant',    pkgColor: '#7986CB' },
    patient_summary:   { label: 'Résumé patient',             icon: FileText,     color: '#7c3aed', bg: '#faf5ff', border: '#e9d5ff', pkg: 'existant',    pkgColor: '#7986CB' },
    calendar_read:     { label: 'Lecture agenda',             icon: Calendar,     color: '#059669', bg: '#ecfdf5', border: '#a7f3d0', pkg: 'calendar',    pkgColor: '#F48FB1' },
    calendar_write:    { label: 'Écriture agenda',            icon: CalendarPlus, color: '#e11d48', bg: '#fff1f2', border: '#fecdd3', pkg: 'calendar',    pkgColor: '#F48FB1' },
    interaction_check: { label: 'Vérification interactions',  icon: Pill,         color: '#9333ea', bg: '#faf5ff', border: '#d8b4fe', pkg: 'interaction', pkgColor: '#E040FB' },
};

function PackageTag({ pkg, color }) {
    if (!pkg) return null;
    return (
        <span
            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-mono font-bold uppercase tracking-wider"
            style={{ backgroundColor: color + '25', color, border: `1px solid ${color}40` }}
        >
            <span className="w-1 h-1 rounded-full" style={{ backgroundColor: color }} />
            {pkg}
        </span>
    );
}

const EXAMPLE_QUERIES = [
    { label: 'Consulter planning',    text: 'Consulte le planning du Dr Martin demain',                    icon: Calendar,     color: '#059669' },
    { label: 'Créer un RDV',          text: 'Crée un RDV pour DUPONT Jean demain avec Dr Martin à 14h',    icon: CalendarPlus, color: '#e11d48' },
    { label: 'Résumé patient',        text: 'Donne-moi un résumé complet du dossier de DUPONT Jean',       icon: FileText,     color: '#7c3aed' },
    { label: 'Vérifier interactions', text: 'Vérifier les interactions entre warfarine et aspirine',       icon: Pill,         color: '#9333ea' },
];

const INTENT_LABELS = {
    CONSULT_PLANNING:   { label: 'Consultation planning',     color: '#059669' },
    CREATE_APPOINTMENT: { label: 'Création RDV',              color: '#e11d48' },
    MODIFY_APPOINTMENT: { label: 'Modification RDV',          color: '#ea580c' },
    DELETE_APPOINTMENT: { label: 'Suppression RDV',           color: '#dc2626' },
    QUERY_PATIENT:      { label: 'Requête patient',           color: '#0284c7' },
    CHECK_INTERACTIONS: { label: 'Vérification interactions', color: '#9333ea' },
    MIXED:              { label: 'Intention mixte',           color: '#7c3aed' },
    REJECTED:           { label: 'Rejeté',                    color: '#6b7280' },
};

const fmt = (iso, opts) => {
    if (!iso) return '—';
    try { return new Date(iso).toLocaleString('fr-FR', opts); } catch { return iso; }
};
const formatDate     = (iso) => fmt(iso, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
const formatTime     = (iso) => fmt(iso, { hour: '2-digit', minute: '2-digit' });
const formatDateTime = (iso) => fmt(iso, { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });

/* ── API helpers ──────────────────────────────────────────────────── */
const authHeaders = () => {
    const t = localStorage.getItem('access_token');
    return t ? { Authorization: `Bearer ${t}` } : {};
};

async function apiFetch(path, opts = {}) {
    const res = await fetch(path, {
        ...opts,
        headers: { 'Content-Type': 'application/json', ...authHeaders(), ...(opts.headers || {}) },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
}

async function* agentStream(query, sessionId, signal, llmMode = 'cloud') {
    const res = await fetch('/api/v1/agent/stream', {
        method: 'POST', signal,
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ query, session_id: sessionId, llm_mode: llmMode }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const reader = res.body.getReader();
    const dec    = new TextDecoder();
    let buf = '';
    while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const events = buf.split('\n\n');
        buf = events.pop();
        for (const ev of events) {
            const line = ev.split('\n').find(l => l.startsWith('data: '));
            if (!line) continue;
            try { yield JSON.parse(line.slice(6)); } catch (_) {}
        }
    }
}

/* ── Google Status Banner ─────────────────────────────────────────── */
function GoogleStatusBanner({ connected, onConnect, onDisconnect, connecting }) {
    if (connected) return (
        <div className="flex items-center gap-2 px-4 py-2.5 bg-gradient-to-r from-emerald-50 to-green-50 border-b border-emerald-200 flex-shrink-0">
            <CheckCircle2 size={16} className="text-emerald-600 flex-shrink-0" />
            <div className="flex-1 min-w-0">
                <p className="text-[11px] font-bold text-emerald-900">Google Calendar connecté</p>
                <p className="text-[10px] text-emerald-700">Les RDV sont créés dans votre agenda Google</p>
            </div>
            <button onClick={onDisconnect} className="text-[10px] text-emerald-700 hover:text-rose-700 font-bold px-2 py-1 rounded transition-colors flex items-center gap-1">
                <Unlink size={11} /> Déconnecter
            </button>
        </div>
    );
    return (
        <div className="flex items-center gap-2 px-4 py-2.5 bg-gradient-to-r from-amber-50 to-orange-50 border-b border-amber-200 flex-shrink-0">
            <AlertCircle size={16} className="text-amber-500 flex-shrink-0 animate-pulse" />
            <div className="flex-1 min-w-0">
                <p className="text-[11px] font-bold text-amber-900">Google Calendar non connecté</p>
                <p className="text-[10px] text-amber-700">Connectez votre compte pour créer des RDV réels</p>
            </div>
            <button onClick={onConnect} disabled={connecting}
                className="flex items-center gap-1.5 bg-[#141414] hover:bg-[#141414]/85 disabled:opacity-40 text-white px-3 py-1.5 rounded-lg text-[10px] font-bold uppercase tracking-wider transition-all flex-shrink-0">
                {connecting ? <Loader2 size={11} className="animate-spin" /> : <Link2 size={11} />}
                Connecter Google
            </button>
        </div>
    );
}

/* ── ConfirmationCard ─────────────────────────────────────────────── */
function ConfirmationCard({ event, index, onConfirm, confirmingId }) {
    const isConfirming = confirmingId === index;
    const p      = event.data?.params || {};
    const action = p.action || 'create';
    const evt    = p.event || {};
    return (
        <div className="border-2 border-amber-400 bg-gradient-to-br from-amber-50 to-orange-50 rounded-2xl p-5 shadow-sm">
            <div className="flex items-start gap-3 mb-4">
                <div className="w-10 h-10 rounded-xl bg-amber-500 flex items-center justify-center flex-shrink-0 animate-pulse">
                    <AlertCircle size={18} className="text-white" />
                </div>
                <div>
                    <p className="text-[10px] font-bold uppercase tracking-wider text-amber-700 mb-0.5">Validation requise</p>
                    <p className="text-sm font-bold text-amber-900">
                        {action === 'create' && 'Confirmer la création du rendez-vous'}
                        {action === 'update' && 'Confirmer la modification du rendez-vous'}
                        {action === 'delete' && 'Confirmer la suppression du rendez-vous'}
                    </p>
                </div>
            </div>
            <div className="bg-white rounded-xl border border-amber-200 p-4 mb-4">
                <div className="grid grid-cols-2 gap-3 text-[11px]">
                    {evt.patient_name && (
                        <div>
                            <div className="flex items-center gap-1 text-[9px] font-bold uppercase tracking-wider text-gray-400 mb-0.5"><User size={9} /> Patient</div>
                            <p className="text-gray-900 font-semibold">{evt.patient_name}</p>
                        </div>
                    )}
                    {evt.doctor_name && (
                        <div>
                            <div className="flex items-center gap-1 text-[9px] font-bold uppercase tracking-wider text-gray-400 mb-0.5"><Stethoscope size={9} /> Médecin</div>
                            <p className="text-gray-900 font-semibold">{evt.doctor_name}</p>
                        </div>
                    )}
                    {evt.start && (
                        <div className="col-span-2">
                            <div className="flex items-center gap-1 text-[9px] font-bold uppercase tracking-wider text-gray-400 mb-0.5"><Calendar size={9} /> Date & heure</div>
                            <p className="text-gray-900 font-semibold">
                                {formatDate(evt.start)}{' '}
                                <span className="font-mono text-gray-600">{formatTime(evt.start)} – {formatTime(evt.end)}</span>
                            </p>
                        </div>
                    )}
                </div>
            </div>
            <div className="flex gap-2">
                <button onClick={() => onConfirm(index, true)} disabled={isConfirming}
                    className="flex-1 flex items-center justify-center gap-2 bg-emerald-600 hover:bg-emerald-700 disabled:opacity-40 text-white px-4 py-2.5 rounded-xl text-sm font-bold transition-all">
                    {isConfirming ? <Loader2 size={15} className="animate-spin" /> : <CheckCircle2 size={15} />}
                    Confirmer
                </button>
                <button onClick={() => onConfirm(index, false)} disabled={isConfirming}
                    className="flex items-center justify-center gap-2 bg-white border-2 border-rose-300 hover:bg-rose-50 disabled:opacity-40 text-rose-700 px-4 py-2.5 rounded-xl text-sm font-bold transition-all">
                    <XCircle size={15} /> Rejeter
                </button>
            </div>
        </div>
    );
}

/* ── ResultView ───────────────────────────────────────────────────── */
function ResultView({ data, toolName }) {
    if (toolName === 'calendar_read' && data?.events !== undefined) return (
        <div className="space-y-2.5">
            {data.events?.length > 0 && (
                <div>
                    <p className="text-[9px] font-bold uppercase tracking-wider text-gray-500 mb-1.5">
                        <Calendar size={10} className="inline mr-1" />Événements ({data.events.length})
                    </p>
                    <div className="space-y-1.5">
                        {data.events.map((ev, i) => (
                            <div key={i} className="bg-white rounded-lg p-2.5 border border-emerald-100 flex items-center gap-2">
                                <Stethoscope size={14} className="text-emerald-700 flex-shrink-0" />
                                <div className="flex-1 min-w-0">
                                    <p className="text-xs font-bold text-gray-900 truncate">{ev.title}</p>
                                    <p className="text-[10px] text-gray-500 font-mono">
                                        {formatTime(ev.start)} → {formatTime(ev.end)}
                                        {ev.patient_name && ` · ${ev.patient_name}`}
                                    </p>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}
            {data.free_slots?.length > 0 && (
                <div>
                    <p className="text-[9px] font-bold uppercase tracking-wider text-gray-500 mb-1.5">
                        <Clock size={10} className="inline mr-1" />Créneaux libres ({data.free_slots.length})
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                        {data.free_slots.slice(0, 12).map((s, i) => (
                            <span key={i} className="bg-emerald-100 text-emerald-900 px-2.5 py-1.5 rounded-lg text-[10px] font-mono font-bold border border-emerald-200">
                                <Clock size={9} className="inline mr-1" />{formatTime(s.start)}
                                <span className="opacity-50"> ({s.duration_minutes}min)</span>
                            </span>
                        ))}
                    </div>
                </div>
            )}
            {!data.events?.length && !data.free_slots?.length && (
                <p className="text-[11px] text-gray-500 italic">Aucun événement trouvé.</p>
            )}
        </div>
    );

    if (toolName === 'calendar_write' && (data?.created || data?.updated)) return (
        <div className="bg-white rounded-xl border-2 border-emerald-200 overflow-hidden">
            <div className="bg-emerald-50 px-3 py-2 border-b border-emerald-100 flex items-center gap-2">
                <CheckCircle2 size={14} className="text-emerald-700" />
                <span className="text-[10px] font-bold uppercase tracking-wider text-emerald-800">
                    RDV {data.created ? 'Créé' : 'Modifié'}
                </span>
            </div>
            <div className="p-3 space-y-2 text-[11px]">
                {data.title && <p className="font-bold text-gray-900">{data.title}</p>}
                {data.start && (
                    <p className="text-gray-700">
                        {formatDate(data.start)}{' '}
                        <span className="font-mono">{formatTime(data.start)} – {formatTime(data.end)}</span>
                    </p>
                )}
                {data.calendar_link && (
                    <a href={data.calendar_link} target="_blank" rel="noopener noreferrer"
                        className="inline-flex items-center gap-1.5 bg-sky-50 hover:bg-sky-100 text-sky-700 px-2.5 py-1.5 rounded-lg text-[10px] font-bold uppercase tracking-wider border border-sky-200 transition-colors">
                        <ExternalLink size={10} /> Ouvrir dans Google Calendar
                    </a>
                )}
            </div>
        </div>
    );

    if (toolName === 'calendar_write' && data?.deleted !== undefined) return (
        <div className="bg-white rounded-xl border border-gray-200 p-3 text-[11px] flex items-center gap-2">
            <CheckCircle2 size={14} className="text-emerald-600 flex-shrink-0" />
            <span className="text-gray-700">RDV {data.deleted ? 'supprimé' : 'introuvable'}</span>
        </div>
    );

    if ((toolName === 'rag_query' || toolName === 'patient_summary') && data?.answer) return (
        <div className="bg-white rounded-xl border border-sky-200 overflow-hidden">
            <div className="bg-sky-50 px-3 py-2 border-b border-sky-100 flex items-center gap-2 flex-wrap">
                <FileText size={12} className="text-sky-700" />
                <span className="text-[10px] font-bold uppercase tracking-wider text-sky-800">
                    {data.patient ? `Dossier : ${data.patient}` : 'Résumé médical'}
                </span>
                {data.sources !== undefined && (
                    <span className="text-[9px] text-sky-600 font-mono">{data.sources} source{data.sources > 1 ? 's' : ''}</span>
                )}
            </div>
            <div className="p-3 prose prose-sm max-w-none text-[12px] leading-relaxed">
                <ReactMarkdown remarkPlugins={[remarkGfm]}
                    components={{
                        h1: ({ children }) => <h3 className="text-sm font-bold text-gray-900 mt-3 mb-1">{children}</h3>,
                        h2: ({ children }) => <h4 className="text-xs font-bold text-gray-900 mt-2 mb-1">{children}</h4>,
                        p:  ({ children }) => <p className="text-[11px] text-gray-700 my-1 leading-relaxed">{children}</p>,
                        ul: ({ children }) => <ul className="my-1 pl-4 text-[11px] list-disc">{children}</ul>,
                        li: ({ children }) => <li className="my-0.5 text-gray-700">{children}</li>,
                    }}>
                    {data.answer}
                </ReactMarkdown>
            </div>
        </div>
    );

    if (toolName === 'interaction_check' && data?.severity !== undefined) {
        const sevColors = {
            LOW:      { bg: '#f0fdf4', border: '#86efac', text: '#166534', badge: '#dcfce7' },
            MEDIUM:   { bg: '#fffbeb', border: '#fcd34d', text: '#92400e', badge: '#fef3c7' },
            HIGH:     { bg: '#fff1f2', border: '#fecdd3', text: '#9f1239', badge: '#ffe4e6' },
            CRITICAL: { bg: '#fdf2f8', border: '#f0abfc', text: '#701a75', badge: '#fae8ff' },
        };
        const sev    = data.severity || 'LOW';
        const colors = sevColors[sev] || sevColors.LOW;
        return (
            <div className="rounded-xl border-2 overflow-hidden" style={{ borderColor: colors.border, backgroundColor: colors.bg }}>
                <div className="px-4 py-3 border-b flex items-center gap-2" style={{ borderColor: colors.border }}>
                    <ShieldAlert size={15} style={{ color: colors.text }} />
                    <span className="text-[10px] font-bold uppercase tracking-wider" style={{ color: colors.text }}>
                        {data.has_interaction ? `Interaction détectée — Sévérité ${sev}` : 'Aucune interaction'}
                    </span>
                    <span className="ml-auto text-[9px] font-mono px-2 py-0.5 rounded-full font-bold" style={{ backgroundColor: colors.badge, color: colors.text }}>{sev}</span>
                </div>
                <div className="px-4 py-3">
                    {data.medications?.length > 0 && (
                        <div className="flex flex-wrap gap-1.5 mb-3">
                            {data.medications.map((m, i) => (
                                <span key={i} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-white border" style={{ borderColor: colors.border, color: colors.text }}>
                                    <Pill size={9} /> {m}
                                </span>
                            ))}
                        </div>
                    )}
                    <p className="text-[12px] text-gray-800 leading-relaxed mb-3">{data.description}</p>
                    {data.recommendations?.length > 0 && (
                        <ul className="space-y-1">
                            {data.recommendations.map((r, i) => (
                                <li key={i} className="flex items-start gap-2 text-[11px] text-gray-700">
                                    <CheckCircle2 size={11} className="mt-0.5 flex-shrink-0" style={{ color: colors.text }} /> {r}
                                </li>
                            ))}
                        </ul>
                    )}
                </div>
            </div>
        );
    }

    return (
        <pre className="text-[10px] bg-white/70 p-2.5 rounded-lg overflow-x-auto border border-gray-200">
            {JSON.stringify(data, null, 2)}
        </pre>
    );
}

/*  PlanningCalendar  */
function PlanningCalendar({ calendarData, doctorName }) {
    const HOUR_PX  = 58;
    const DAY_START = 8;
    const DAY_END   = 18;
    const HOURS = Array.from({ length: DAY_END - DAY_START + 1 }, (_, i) => DAY_START + i);

    const toPx  = (iso) => { const d = new Date(iso); return ((d.getHours() - DAY_START) * 60 + d.getMinutes()) / 60 * HOUR_PX; };
    const durPx = (s, e) => Math.max(22, ((new Date(e) - new Date(s)) / 3600000) * HOUR_PX);

    if (!calendarData) return (
        <div className="h-full flex flex-col items-center justify-center gap-3 text-center px-4">
            <Calendar size={22} className="text-gray-400" />
            <div>
                <p className="text-xs font-bold text-gray-600">Planning</p>
                <p className="text-[11px] text-gray-400 mt-0.5">Consultez un planning pour visualiser le calendrier</p>
            </div>
        </div>
    );

    const { events = [], free_slots = [] } = calendarData;
    const firstDate  = events[0]?.start || free_slots[0]?.start;
    const displayDay = firstDate ? new Date(firstDate) : new Date();

    return (
        <div className="h-full flex flex-col overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-100 flex-shrink-0 bg-gray-50">
                <p className="text-[10px] font-bold uppercase tracking-wider text-gray-500 mb-0.5">
                    Planning · {doctorName || 'Dr Martin'}
                </p>
                <p className="text-sm font-bold text-gray-900 capitalize">
                    {displayDay.toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long' })}
                </p>
                <div className="flex gap-3 mt-1">
                    <span className="text-[10px] font-semibold text-blue-700"><span className="w-2 h-2 rounded-sm bg-blue-500 inline-block mr-1" />{events.length} RDV</span>
                    <span className="text-[10px] font-semibold text-emerald-700"><span className="w-2 h-2 rounded-sm bg-emerald-400 inline-block mr-1" />{free_slots.length} libre{free_slots.length !== 1 ? 's' : ''}</span>
                </div>
            </div>
            <div className="flex-1 overflow-y-auto py-2">
                <div className="flex" style={{ minHeight: `${(DAY_END - DAY_START) * HOUR_PX + 32}px` }}>
                    <div className="relative flex-shrink-0" style={{ width: '36px' }}>
                        {HOURS.map(h => (
                            <div key={h} className="absolute right-2 text-[9px] font-mono text-gray-400 leading-none" style={{ top: `${(h - DAY_START) * HOUR_PX - 5}px` }}>{h}h</div>
                        ))}
                    </div>
                    <div className="flex-1 relative border-l border-gray-100 mr-2">
                        {HOURS.map(h => <div key={h} className="absolute left-0 right-0 border-t border-gray-100" style={{ top: `${(h - DAY_START) * HOUR_PX}px` }} />)}
                        {free_slots.map((slot, i) => (
                            <div key={`free-${i}`} className="absolute inset-x-1 rounded-md bg-emerald-50 border border-emerald-200 border-dashed flex flex-col justify-center px-2 overflow-hidden"
                                style={{ top: `${toPx(slot.start)}px`, height: `${durPx(slot.start, slot.end)}px` }}>
                                <p className="text-[9px] text-emerald-700 font-bold leading-tight">Libre</p>
                                <p className="text-[8px] text-emerald-600 font-mono">{formatTime(slot.start)}–{formatTime(slot.end)}</p>
                            </div>
                        ))}
                        {events.map((ev, i) => {
                            const h = durPx(ev.start, ev.end);
                            return (
                                <div key={`ev-${i}`} className="absolute inset-x-1 rounded-md bg-blue-500 text-white px-2 py-1 overflow-hidden shadow-sm"
                                    style={{ top: `${toPx(ev.start)}px`, height: `${h}px` }}>
                                    <p className="text-[9px] font-bold leading-tight truncate">{ev.title}</p>
                                    {h > 30 && <p className="text-[8px] opacity-80 font-mono">{formatTime(ev.start)}–{formatTime(ev.end)}</p>}
                                </div>
                            );
                        })}
                    </div>
                </div>
            </div>
        </div>
    );
}

/*  EventCard  */
function EventCard({ event, index, onConfirm, confirmingId, totalSteps }) {
    const [expanded, setExpanded] = useState(false);

    if (event.type === 'STEP_START') {
        const meta = TOOL_META[event.step_name] || { label: event.step_name, icon: PlayCircle, color: '#6b7280', bg: '#f9fafb', border: '#e5e7eb' };
        const Icon = meta.icon;
        return (
            <div className="border rounded-2xl p-4 flex items-start gap-3 shadow-sm" style={{ backgroundColor: meta.bg, borderColor: meta.border }}>
                <div className="relative flex-shrink-0">
                    <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ backgroundColor: meta.color + '20' }}>
                        <Icon size={18} style={{ color: meta.color }} />
                    </div>
                    <Loader2 size={12} className="animate-spin absolute -bottom-1 -right-1 bg-white rounded-full p-0.5" style={{ color: meta.color }} />
                </div>
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap mb-1">
                        <span className="text-[10px] font-bold uppercase tracking-wider" style={{ color: meta.color }}>
                            Étape {event.data?.order || '?'}{totalSteps ? `/${totalSteps}` : ''} · {meta.label}
                        </span>
                        <PackageTag pkg={meta.pkg} color={meta.pkgColor} />
                    </div>
                    {/* Label CDC §5.4 : étape lisible en français */}
                    <p className="text-xs text-gray-700">{event.data?.label || 'En cours d\'exécution…'}</p>
                    <button onClick={() => setExpanded(!expanded)} className="text-[10px] text-gray-500 hover:text-gray-900 mt-2 flex items-center gap-1">
                        {expanded ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
                        {expanded ? 'Masquer' : 'Voir'} les paramètres
                    </button>
                    {expanded && (
                        <pre className="mt-2 text-[10px] bg-white/70 p-2.5 rounded-lg overflow-x-auto border border-white/50">
                            {JSON.stringify(event.data?.params, null, 2)}
                        </pre>
                    )}
                </div>
            </div>
        );
    }

    if (event.type === 'STEP_COMPLETE') {
        const meta = TOOL_META[event.step_name] || { label: event.step_name, icon: CheckCircle2, color: '#059669', bg: '#ecfdf5', border: '#a7f3d0' };
        const Icon = meta.icon;
        const ok   = event.data?.success;
        return (
            <div className="border rounded-2xl p-4 shadow-sm" style={{ backgroundColor: ok ? meta.bg : '#fef2f2', borderColor: ok ? meta.border : '#fecaca' }}>
                <div className="flex items-start gap-3">
                    <div className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0" style={{ backgroundColor: (ok ? meta.color : '#e11d48') + '20' }}>
                        {ok ? <Icon size={18} style={{ color: meta.color }} /> : <XCircle size={18} className="text-rose-600" />}
                    </div>
                    <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-[10px] font-bold uppercase tracking-wider" style={{ color: ok ? meta.color : '#e11d48' }}>
                                {meta.label} — {ok ? 'Terminé' : 'Échec'}
                            </span>
                            <PackageTag pkg={meta.pkg} color={meta.pkgColor} />
                            {event.data?.execution_time_ms !== undefined && (
                                <span className="text-[9px] font-mono text-gray-400 ml-auto">
                                    {event.data.execution_time_ms < 1000
                                        ? `${event.data.execution_time_ms} ms`
                                        : `${(event.data.execution_time_ms / 1000).toFixed(1)} s`}
                                </span>
                            )}
                        </div>
                        {event.data?.error && (
                            <div className="mt-2 bg-rose-100 border border-rose-200 rounded-lg p-2.5 text-xs text-rose-900 flex items-start gap-2">
                                <Info size={12} className="text-rose-600 mt-0.5 flex-shrink-0" />{event.data.error}
                            </div>
                        )}
                        {event.data?.data && (
                            <div className="mt-2">
                                <ResultView data={event.data.data} toolName={event.step_name} />
                            </div>
                        )}
                    </div>
                </div>
            </div>
        );
    }

    if (event.type === 'CONFIRMATION_REQUEST')
        return <ConfirmationCard event={event} index={index} onConfirm={onConfirm} confirmingId={confirmingId} />;

    if (event.type === 'ANSWER') {
        const { intent, entities = {}, steps_count, summary, message } = event.data || {};
        const intentInfo = INTENT_LABELS[intent] || { label: intent, color: '#6b7280' };
        const pipelineSteps = (summary || '').split('|').map(s => s.trim()).filter(Boolean)
            .map(s => { const m = s.match(/\[(\w+)\]\s+(\w+)/); return m ? { status: m[1], tool: m[2] } : null; })
            .filter(Boolean);
        return (
            <div className="border border-[#141414]/10 bg-gradient-to-br from-[#141414] to-[#2a2a2a] text-white rounded-2xl p-5 shadow-lg">
                <div className="flex items-center gap-2 mb-3">
                    <div className="w-8 h-8 rounded-lg bg-white/10 flex items-center justify-center"><Bot size={16} /></div>
                    <div>
                        <p className="text-[10px] font-bold uppercase tracking-wider opacity-60">Réponse finale</p>
                        <p className="text-xs font-bold">Agent Médical Autonome</p>
                    </div>
                    <span className="ml-auto text-[9px] font-bold uppercase tracking-wider px-2 py-1 rounded-full"
                        style={{ backgroundColor: intentInfo.color + '30', color: intentInfo.color }}>
                        {intentInfo.label}
                    </span>
                </div>

                {/* Message lisible CDC §5.4 */}
                {message && (
                    <p className="mt-2 mb-3 text-sm text-white/90 font-medium">{message}</p>
                )}

                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-[11px]">
                    <div>
                        <p className="text-[8px] font-bold uppercase tracking-wider opacity-40 mb-0.5">Étapes</p>
                        <p className="font-mono text-sm font-bold">{steps_count}</p>
                    </div>
                    {entities.doctor  && <div><p className="text-[8px] font-bold uppercase tracking-wider opacity-40 mb-0.5">Médecin</p><p className="font-semibold truncate">{entities.doctor}</p></div>}
                    {entities.patient && <div><p className="text-[8px] font-bold uppercase tracking-wider opacity-40 mb-0.5">Patient</p><p className="font-semibold truncate">{entities.patient}</p></div>}
                    {entities.date    && <div><p className="text-[8px] font-bold uppercase tracking-wider opacity-40 mb-0.5">Date</p><p className="font-mono text-[10px]">{formatDateTime(entities.date)}</p></div>}
                </div>

                {pipelineSteps.length > 0 && (
                    <div className="mt-3 pt-3 border-t border-white/10">
                        <p className="text-[8px] font-bold uppercase tracking-wider opacity-40 mb-2">Pipeline</p>
                        <div className="flex items-center gap-1.5 flex-wrap">
                            {pipelineSteps.map((step, i) => {
                                const m  = TOOL_META[step.tool] || { label: step.tool, color: '#6b7280' };
                                const ok = step.status === 'COMPLETED';
                                return (
                                    <span key={i} className="inline-flex items-center gap-1">
                                        <span className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[9px] font-mono font-bold"
                                            style={{ backgroundColor: (ok ? m.color : '#f87171') + '30', color: ok ? '#ffffff' : '#fecaca', border: `1px solid ${(ok ? m.color : '#f87171')}60` }}>
                                            {ok ? <CheckCircle2 size={9} /> : <XCircle size={9} />}{m.label}
                                        </span>
                                        {i < pipelineSteps.length - 1 && <ArrowRight size={10} className="opacity-40" />}
                                    </span>
                                );
                            })}
                        </div>
                    </div>
                )}
            </div>
        );
    }

    if (event.type === 'ERROR') return (
        <div className="border-2 border-rose-300 bg-rose-50 rounded-2xl p-4 flex items-start gap-3">
            <div className="w-10 h-10 rounded-xl bg-rose-200 flex items-center justify-center flex-shrink-0">
                <XCircle size={18} className="text-rose-700" />
            </div>
            <div>
                <p className="text-[10px] font-bold uppercase tracking-wider text-rose-700 mb-1">Erreur</p>
                <p className="text-sm text-rose-900">{event.data?.message}</p>
            </div>
        </div>
    );

    return null;
}

/*  Page principale  */
export default function AgentMedical() {
    const location = useLocation();
    const [query,           setQuery]           = useState('');
    const [events,          setEvents]          = useState([]);
    const [loading,         setLoading]         = useState(false);
    const [sessionId,       setSessionId]       = useState(genSessionId());
    const [confirmingId,    setConfirmingId]    = useState(null);
    const [googleConnected, setGoogleConnected] = useState(null);
    const [connectingGoogle,setConnectingGoogle]= useState(false);
    const [toast,           setToast]           = useState('');
    const [calendarData,    setCalendarData]    = useState(null);
    const [planningDoctor,  setPlanningDoctor]  = useState('Dr Martin');
    const [llmMode,         setLlmMode]         = useState(
        () => localStorage.getItem('agent_llm_mode') || 'cloud'
    );
    const scrollRef = useRef(null);

    const totalSteps = useMemo(() => events.filter(e => e.type === 'STEP_START').length, [events]);

    useEffect(() => {
        scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
    }, [events, loading]);

    useEffect(() => {
        const params = new URLSearchParams(location.search);
        if (params.get('google_connected') === '1') {
            setToast('✓ Google Calendar connecté !');
            setTimeout(() => setToast(''), 4000);
            window.history.replaceState({}, '', '/agent');
        }
        if (params.get('google_error')) {
            setToast(`⚠ Erreur Google : ${params.get('google_error')}`);
            setTimeout(() => setToast(''), 5000);
            window.history.replaceState({}, '', '/agent');
        }
        apiFetch('/api/v1/agent/google/status')
            .then(d => setGoogleConnected(d.connected))
            .catch(() => setGoogleConnected(false));
    }, []);

    const handleConnectGoogle = async () => {
        setConnectingGoogle(true);
        try {
            const { auth_url } = await apiFetch('/api/v1/agent/google/auth');
            window.location.href = auth_url;
        } catch (err) {
            setToast(`⚠ ${err.message}`);
            setTimeout(() => setToast(''), 4000);
            setConnectingGoogle(false);
        }
    };

    const handleDisconnectGoogle = async () => {
        try {
            await apiFetch('/api/v1/agent/google/disconnect', { method: 'DELETE' });
            setGoogleConnected(false);
            setToast('Google Calendar déconnecté.');
            setTimeout(() => setToast(''), 3000);
        } catch (err) {
            setToast(`⚠ ${err.message}`);
            setTimeout(() => setToast(''), 4000);
        }
    };

    const runQuery = async (text) => {
        const q = (text || query).trim();
        if (!q || loading) return;
        setQuery('');
        setLoading(true);
        setEvents(prev => [...prev, { type: 'USER_QUERY', data: { text: q } }]);

        const ctrl = new AbortController();
        const tmo  = setTimeout(() => ctrl.abort(), 120_000);
        try {
            for await (const ev of agentStream(q, sessionId, ctrl.signal, llmMode)) {
                if (ev.type === 'DONE') continue;
                setEvents(prev => [...prev, ev]);
                if (ev.type === 'STEP_COMPLETE' && ev.step_name === 'calendar_read' && ev.data?.success)
                    setCalendarData(ev.data.data);
                if (ev.type === 'ANSWER' && ev.data?.entities?.doctor)
                    setPlanningDoctor(ev.data.entities.doctor);
            }
        } catch (err) {
            const msg = err.name === 'AbortError' ? 'Délai dépassé (120s)' : err.message;
            setEvents(prev => [...prev, { type: 'ERROR', data: { message: msg } }]);
        } finally {
            clearTimeout(tmo);
            setLoading(false);
        }
    };

    const handleConfirm = async (eventIndex, approved) => {
        setConfirmingId(eventIndex);
        try {
            const result = await apiFetch('/api/v1/agent/confirm', {
                method: 'POST',
                body: JSON.stringify({ session_id: sessionId, approved }),
            });
            setEvents(prev => [...prev,
                { type: 'STEP_COMPLETE', step_name: 'calendar_write', data: { success: result.success, data: result.data, error: result.error, execution_time_ms: result.execution_time_ms } },
                { type: 'ANSWER', data: { intent: approved ? 'CREATE_APPOINTMENT' : 'REJECTED', entities: {}, steps_count: totalSteps + 1, summary: approved ? '[COMPLETED] calendar_write' : '[CANCELLED] action rejetée', message: approved ? 'Action confirmée et exécutée.' : 'Action annulée par l\'utilisateur.' } },
            ]);
        } catch (err) {
            setEvents(prev => [...prev, { type: 'ERROR', data: { message: err.message } }]);
        } finally {
            setConfirmingId(null);
        }
    };

    const resetSession = () => { setEvents([]); setSessionId(genSessionId()); setCalendarData(null); };

    const hasPending = events.some((e, i) =>
        e.type === 'CONFIRMATION_REQUEST' &&
        !events.slice(i + 1).some(n => n.type === 'STEP_COMPLETE' && n.step_name === e.step_name)
    );

    return (
        <div className="h-full flex flex-col overflow-hidden bg-[#F4F4F2]">
            {toast && (
                <div className="fixed top-4 right-4 z-50 bg-[#141414] text-white text-sm px-4 py-3 rounded-xl shadow-2xl animate-in slide-in-from-top-2">
                    {toast}
                </div>
            )}

            {/* Header */}
            <div className="bg-gradient-to-r from-[#141414] to-[#2a2a2a] text-white px-4 md:px-6 py-3 md:py-4 flex items-center justify-between flex-shrink-0">
                <div className="flex items-center gap-3 min-w-0">
                    <div className="bg-white/10 p-2.5 rounded-xl flex-shrink-0"><Wand2 size={18} /></div>
                    <div className="min-w-0">
                        <p className="text-[9px] font-mono uppercase tracking-widest opacity-50">Section 5 · Agent Autonome</p>
                        <p className="text-sm font-bold truncate">Agent Médical</p>
                    </div>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                    {loading && (
                        <span className="flex items-center gap-1.5 bg-white/10 px-2.5 py-1.5 rounded-lg text-[10px] font-bold uppercase tracking-wider">
                            <Activity size={11} className="animate-pulse text-emerald-300" />
                            <span className="hidden md:inline">En exécution</span>
                        </span>
                    )}
                    <button onClick={() => { const next = llmMode === 'cloud' ? 'local' : 'cloud'; setLlmMode(next); localStorage.setItem('agent_llm_mode', next); setToast(next === 'local' ? '🔒 Mode Local (Ollama)' : '☁ Mode Cloud (Mistral)'); setTimeout(() => setToast(''), 3000); }}
                        className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[10px] font-bold uppercase tracking-wider transition-all border ${llmMode === 'local' ? 'bg-emerald-500/20 border-emerald-400/40 text-emerald-300' : 'bg-white/10 border-white/20 text-white/70'}`}>
                        {llmMode === 'local' ? <><Lock size={11} /><span className="hidden sm:inline">Local</span></> : <><Cloud size={11} /><span className="hidden sm:inline">Cloud</span></>}
                    </button>
                    {events.length > 0 && (
                        <button onClick={resetSession} className="flex items-center gap-1.5 bg-white/10 hover:bg-white/20 px-2 md:px-3 py-2 rounded-lg text-[10px] font-bold uppercase tracking-wide transition-all">
                            <Trash2 size={12} /><span className="hidden md:inline">Nouvelle session</span>
                        </button>
                    )}
                </div>
            </div>

            {/* Banner Google */}
            {googleConnected !== null && (
                <GoogleStatusBanner connected={googleConnected} onConnect={handleConnectGoogle} onDisconnect={handleDisconnectGoogle} connecting={connectingGoogle} />
            )}

            {/* Corps */}
            <div className="flex flex-1 overflow-hidden min-h-0">

                {/* Colonne gauche */}
                <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
                    <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 md:px-6 py-4 space-y-3">
                        {events.length === 0 && !loading && (
                            <div className="max-w-2xl mx-auto py-8 md:py-12">
                                <div className="text-center mb-8">
                                    <div className="inline-flex w-16 h-16 rounded-2xl bg-gradient-to-br from-[#141414] to-[#2a2a2a] items-center justify-center mb-4 shadow-lg">
                                        <Bot size={28} className="text-white" />
                                    </div>
                                    <h2 className="text-xl font-bold text-gray-900 mb-2">Agent Médical Autonome</h2>
                                    <p className="text-sm text-gray-500 max-w-md mx-auto">
                                        Formule ta demande en langage naturel — l'agent planifie et exécute automatiquement les étapes nécessaires.
                                    </p>
                                </div>
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                                    {EXAMPLE_QUERIES.map((ex, i) => {
                                        const Icon = ex.icon;
                                        return (
                                            <button key={i} onClick={() => runQuery(ex.text)}
                                                className="group flex items-start gap-3 p-4 bg-white border border-gray-200 rounded-2xl hover:border-[#141414]/40 hover:shadow-md transition-all text-left">
                                                <div className="w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0 transition-transform group-hover:scale-110" style={{ backgroundColor: ex.color + '20' }}>
                                                    <Icon size={16} style={{ color: ex.color }} />
                                                </div>
                                                <div className="min-w-0 flex-1">
                                                    <p className="text-[10px] font-bold uppercase tracking-wider text-gray-500 mb-0.5">{ex.label}</p>
                                                    <p className="text-xs text-gray-900 leading-relaxed">{ex.text}</p>
                                                </div>
                                                <ArrowRight size={14} className="text-gray-300 group-hover:text-gray-900 group-hover:translate-x-0.5 transition-all mt-1 flex-shrink-0" />
                                            </button>
                                        );
                                    })}
                                </div>
                            </div>
                        )}

                        {events.map((event, i) => {
                            if (event.type === 'USER_QUERY') return (
                                <div key={i} className="flex justify-end">
                                    <div className="max-w-[85%] bg-[#141414] text-white rounded-2xl rounded-tr-sm px-4 py-3 text-sm shadow-sm">
                                        {event.data.text}
                                    </div>
                                </div>
                            );
                            if (event.type === 'STEP_START') {
                                const alreadyDone = events.slice(i + 1).some(e => e.type === 'STEP_COMPLETE' && e.step_name === event.step_name);
                                if (alreadyDone) return null;
                            }
                            return <EventCard key={i} event={event} index={i} onConfirm={handleConfirm} confirmingId={confirmingId} totalSteps={totalSteps} />;
                        })}

                        {loading && !events.some(e => e.type === 'STEP_START') && (
                            <div className="flex items-center gap-2 text-xs text-gray-500 px-2 py-3 animate-pulse">
                                <Loader2 size={14} className="animate-spin" />
                                <span>Analyse de votre requête…</span>
                            </div>
                        )}
                    </div>

                    {/* Zone de saisie */}
                    <div className="px-3 sm:px-5 py-3 border-t border-gray-200 bg-white flex-shrink-0 shadow-lg">
                        <div className="flex gap-2 items-end max-w-4xl mx-auto">
                            <div className="flex-1 relative">
                                <textarea
                                    value={query}
                                    onChange={e => setQuery(e.target.value)}
                                    onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); runQuery(); } }}
                                    placeholder={hasPending ? 'Confirmez ou rejetez l\'action en attente…' : 'Ex : Crée un RDV pour DUPONT Jean demain à 14h…'}
                                    rows={1}
                                    disabled={loading || hasPending}
                                    className="w-full resize-none border border-gray-300 rounded-2xl px-4 py-3 text-sm outline-none focus:border-[#141414] focus:ring-2 focus:ring-[#141414]/10 transition-all disabled:opacity-40 disabled:bg-gray-50"
                                    style={{ minHeight: '50px', maxHeight: '150px' }}
                                />
                            </div>
                            <button onClick={() => runQuery()} disabled={loading || !query.trim() || hasPending}
                                className="bg-[#141414] text-white w-12 h-12 rounded-2xl flex items-center justify-center hover:bg-[#141414]/90 active:scale-95 transition-all disabled:opacity-30 flex-shrink-0 shadow-sm">
                                {loading ? <Loader2 size={17} className="animate-spin" /> : <Send size={17} />}
                            </button>
                        </div>
                        {!hasPending && !loading && (
                            <p className="text-center text-[10px] text-gray-400 mt-2 font-mono">
                                Entrée pour envoyer · Maj+Entrée pour nouvelle ligne
                            </p>
                        )}
                    </div>
                </div>

                {/* Colonne droite — planning visuel */}
                <div className="hidden lg:flex flex-col w-72 xl:w-80 border-l border-gray-200 flex-shrink-0 bg-white overflow-hidden">
                    <div className="px-4 pt-3 pb-0 flex-shrink-0 flex items-center justify-between">
                        <span className="text-[9px] font-bold uppercase tracking-widest text-gray-400">Calendrier</span>
                        {calendarData && <span className="text-[9px] font-mono text-gray-300">Mode {googleConnected ? 'réel' : 'démo'}</span>}
                    </div>
                    <div className="flex-1 overflow-hidden">
                        <PlanningCalendar calendarData={calendarData} doctorName={planningDoctor} />
                    </div>
                </div>

            </div>
        </div>
    );
}
