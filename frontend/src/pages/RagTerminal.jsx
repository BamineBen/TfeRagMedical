/**
 * RagTerminal.jsx — Interface de chat médical RAG
 * ═══════════════════════════════════════════════
 *
 * RÔLE DANS L'ARCHITECTURE
 * ─────────────────────────
 * Page principale de l'application. C'est l'interface où le médecin
 * pose des questions sur les dossiers patients.
 *
 * STRUCTURE DE LA PAGE (de gauche à droite) :
 * ┌─────────────┬──────────────────────────────────────────┐
 * │ PatientSidebar │            Chat Area                  │
 * │ (liste des  │  ┌──── Header (LLM mode, synthèse) ────┐ │
 * │  patients)  │  │                                     │ │
 * │             │  │     ChatMessages (SSE stream)        │ │
 * │             │  │                                     │ │
 * │             │  │     SuggestionsPanel (onglets)       │ │
 * │             │  │                                     │ │
 * │             │  └──── Input (textarea + send) ────────┘ │
 * └─────────────┴──────────────────────────────────────────┘
 *
 * FLUX D'UNE QUESTION
 * ────────────────────
 * 1. Médecin tape une question + presse Entrée
 * 2. sendMessage() envoie patient_id (ID DB) comme paramètre explicite
 * 3. _sseStream() ouvre une connexion SSE vers POST /api/v1/chat/stream
 * 4. Les tokens arrivent 1 par 1 et s'affichent en temps réel
 * 5. Quand done=true, le timer s'arrête et le badge de temps apparaît
 *
 * ÉTAT REACT (useState)
 * ──────────────────────
 * - documents    : liste des documents/patients indexés (depuis /api/v1/documents)
 * - selectedDoc  : patient actuellement sélectionné
 * - messages     : historique du chat [{role, content, sources, citations}]
 * - llmMode      : 'local' | 'mistral' | 'gemini' (persiste en localStorage)
 * - loading      : true pendant le stream SSE
 * - elapsed      : millisecondes écoulées (timer live affiché dans le header)
 *
 * PRINCIPE DRY APPLIQUÉ
 * ──────────────────────
 * extractPatientName() est importé depuis utils/patient.js
 * (était copié-collé dans 4 fichiers avant la refactorisation).
 */
import { useState, useEffect, useRef } from 'react';
import { Send, Globe, Search, Trash2, Loader2, ClipboardList, Cpu, Eye, Users, X, FilePlus, Cloud, Sparkles, AlertTriangle } from 'lucide-react';
import ChatMessages from '../components/ChatMessages';
import SuggestionsPanel from '../components/SuggestionsPanel';
import api from '../api/client';
// Import centralisé depuis utils/patient.js (principe DRY)
import { extractPatientName, normalizePatientName } from '../utils/patient';

/* ── Constantes ───────────────────────────────────────────────── */
const MODEL_MODES = { EXPERT: 'expert' };

/* 3 modes LLM disponibles côté frontend.
   IMPORTANT : doit rester synchronisé avec LLMMode dans llm_client.py.
   Chaque mode a des implications RGPD différentes (voir rgpd field). */
const LLM_MODES = [
    {
        id: 'local',
        label: 'Local',
        icon: Cpu,
        color: 'emerald',
        rgpd: 'strict',
        title: 'Ollama (Contabo) — RGPD strict',
        desc: 'Données patient restent sur le VPS. Aucun envoi externe.',
    },
    {
        id: 'mistral',
        label: 'Mistral',
        icon: Cloud,
        color: 'sky',
        rgpd: 'dpa',
        title: 'Mistral La Plateforme — DPA français',
        desc: 'Hébergement France, ISO 27001. Conforme vraies données patient.',
    },
    {
        id: 'gemini',
        label: 'Gemini',
        icon: Sparkles,
        color: 'amber',
        rgpd: 'anonymized',
        title: 'Google Gemini — données anonymisées uniquement',
        desc: 'Hébergé hors UE. Réservé démo / patients fictifs.',
    },
];

/* ── Helpers ──────────────────────────────────────────────────── */
// SUPPRIMÉ : extractPatientName() est maintenant importé depuis utils/patient.js (DRY)

/**
 * Flux SSE commun — retourne un async generator de données parsées.
 *
 * SSE (Server-Sent Events) = protocole HTTP unidirectionnel serveur→client.
 * Le serveur envoie des lignes "data: {json}\n\n" en continu.
 * On lit ces lignes avec un ReadableStream et on yield chaque objet JSON.
 *
 * Séquence des événements reçus :
 *   {sources: [...]}         → sources RAG trouvées
 *   {type: 'citations', ...} → numéros de citations [1], [2]...
 *   {content: 'token'}       → tokens LLM (1 par 1)
 *   {content: '', done: true}→ fin du stream
 */
/**
 * Stream SSE vers le backend.
 *
 * PARAMÈTRES :
 *   prompt        — question du médecin (texte brut, sans annotation)
 *   modelMode     — mode RAG ('expert')
 *   conversationId — ID de conversation pour historique (null = nouvelle)
 *   llmMode       — 'local' | 'mistral' | 'gemini'
 *   patientId     — ID DB du document patient (null = cohorte/notes-only)
 *   signal        — AbortSignal pour annuler la requête (timeout ou composant démonté)
 *
 * POURQUOI AbortController ?
 *   Sans timeout, si le LLM ou le réseau bloque, la requête reste ouverte
 *   indéfiniment et l'utilisateur voit un spinner infini.
 *   Avec AbortController, on peut annuler proprement depuis sendMessage().
 */
async function* _sseStream(prompt, modelMode, conversationId, llmMode, patientId, signal) {
    const token = localStorage.getItem('access_token');
    const res = await fetch('/api/v1/chat/stream', {
        method: 'POST',
        signal,   // ← permet l'annulation depuis l'extérieur
        headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
            message: prompt,
            patient_id: patientId || undefined,  // ID DB explicite (null = cohorte/notes)
            conversation_id: conversationId || undefined,
            channel: 'web',
            use_rag: true,
            model_mode: modelMode,
            llm_mode: llmMode,
        }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const reader  = res.body.getReader();
    const decoder = new TextDecoder();

    // ── Bufferisation SSE correcte ──────────────────────────────────
    // Le protocole SSE sépare les événements par \n\n (double newline).
    // Un événement peut être découpé en plusieurs chunks TCP (surtout
    // la citation_map qui fait ~10KB avec 26+ entrées).
    // On accumule les chunks dans `buf` et on parse SEULEMENT quand
    // on a un événement complet (présence de \n\n).
    let buf = '';
    while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });

        // Découper sur double newline = fin d'événement SSE
        const events = buf.split('\n\n');
        buf = events.pop();   // dernier fragment incomplet → garde en buffer

        for (const event of events) {
            const dataLine = event.split('\n').find(l => l.startsWith('data: '));
            if (!dataLine) continue;
            try { yield JSON.parse(dataLine.slice(6)); } catch (_) {}
        }
    }
    // Traiter ce qui reste dans le buffer (dernier événement sans \n\n final)
    if (buf.trim()) {
        const dataLine = buf.split('\n').find(l => l.startsWith('data: '));
        if (dataLine) try { yield JSON.parse(dataLine.slice(6)); } catch (_) {}
    }
}

/* ── Patient sidebar ─────────────────────────────────────────── */
function PatientSidebar({ documents, selectedDoc, onSelect, multipatient, onToggleMulti, visible, onClose }) {
    const [search, setSearch] = useState('');

    const filtered = documents.filter(doc => {
        if (!search.trim()) return true;
        const q = search.toLowerCase();
        const name = extractPatientName(doc.title || '').toLowerCase();
        return name.includes(q) || (doc.title || '').toLowerCase().includes(q);
    });

    return (
        <>
            {/* Mobile backdrop */}
            {visible && (
                <div
                    className="fixed inset-0 bg-black/30 z-30 md:hidden"
                    onClick={onClose}
                />
            )}
            <div className={`
                fixed inset-y-0 left-0 z-40
                md:relative md:inset-auto md:z-auto md:translate-x-0
                w-64 flex-shrink-0 border-r border-[#141414]/10 bg-white flex flex-col
                shadow-xl md:shadow-none
                transition-transform duration-300
                ${visible ? 'translate-x-0' : '-translate-x-full md:translate-x-0'}
            `}>
                {/* Mobile close button */}
                <div className="md:hidden flex items-center justify-between px-4 pt-4 pb-2">
                    <span className="text-[9px] font-bold uppercase tracking-widest opacity-40">Patients</span>
                    <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-[#141414]/5">
                        <X size={14} />
                    </button>
                </div>

                {/* Patient list */}
                <div className="flex-1 overflow-y-auto">
                    <div className="p-4 border-b border-[#141414]/5">
                        <div className="flex items-center justify-between mb-3">
                            <h3 className="text-[9px] font-bold uppercase tracking-widest opacity-40 hidden md:block">
                                Patients ({documents.length})
                            </h3>
                        </div>

                        {/* Multi-patient toggle */}
                        <button
                            onClick={onToggleMulti}
                            className={`w-full flex items-center gap-2 px-3 py-2.5 rounded-xl text-xs font-bold transition-all mb-3 ${
                                multipatient
                                    ? 'bg-[#141414] text-white'
                                    : 'bg-[#141414]/5 hover:bg-[#141414]/10 opacity-70 hover:opacity-100'
                            }`}
                        >
                            <Globe size={13} />
                            Mode tous les patients
                        </button>

                        {/* Search */}
                        {documents.length > 4 && (
                            <div className="relative mb-2">
                                <Search size={12} className="absolute left-3 top-1/2 -translate-y-1/2 opacity-35" />
                                <input
                                    type="text"
                                    placeholder="Rechercher un patient..."
                                    value={search}
                                    onChange={e => setSearch(e.target.value)}
                                    className="w-full pl-8 pr-3 py-2 text-[11px] border border-[#141414]/10 rounded-lg outline-none focus:ring-1 ring-[#141414]/10"
                                />
                            </div>
                        )}
                    </div>

                    <div className="p-2">
                        {filtered.length === 0 ? (
                            <p className="text-[10px] italic opacity-30 text-center py-6">
                                {search ? 'Aucun résultat' : 'Aucun document indexé'}
                            </p>
                        ) : filtered.map((doc) => {
                            const name = doc.patientLabel || extractPatientName(doc.title || '');
                            const isSelected = selectedDoc?.id === doc.id;
                            return (
                                <div
                                    key={doc.id}
                                    onClick={() => { onSelect(doc); onClose(); }}
                                    className={`flex items-center gap-2.5 p-3 rounded-xl cursor-pointer group transition-all mb-1 ${
                                        isSelected
                                            ? 'bg-[#141414] text-white'
                                            : 'hover:bg-[#141414]/5'
                                    }`}
                                >
                                    <div className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                                        isSelected ? 'bg-white' : 'bg-[#141414]/20'
                                    }`} />
                                    <div className="flex-1 min-w-0">
                                        <p className="text-xs font-bold truncate">{name}</p>
                                        <p className={`text-[9px] truncate ${isSelected ? 'opacity-60' : 'opacity-35'}`}>
                                            {doc.isNoteOnly
                                                ? '📝 Note atomique'
                                                : `${doc.chunk_count ?? '?'} chunks · ${doc.title?.split('_')[0] || ''}`
                                            }
                                        </p>
                                    </div>
                                    {!doc.isNoteOnly && (
                                        <button
                                            onClick={e => {
    e.stopPropagation();
    const token = localStorage.getItem('access_token');
    // Utilise /patients/{id}/pdf avec token en query param (même auth que KnowledgeBase)
    const url = doc.patient_id
        ? `/api/v1/patients/${doc.patient_id}/pdf?token=${encodeURIComponent(token)}`
        : `/api/v1/patients/${doc.id}/pdf?token=${encodeURIComponent(token)}`;
    window.open(url, '_blank', 'noopener,noreferrer');
}}
                                            className={`opacity-0 group-hover:opacity-100 p-1 rounded-md transition-all flex-shrink-0 ${
                                                isSelected ? 'hover:bg-white/20' : 'hover:bg-[#141414]/10'
                                            }`}
                                            title="Voir le PDF"
                                        >
                                            <Eye size={12} />
                                        </button>
                                    )}
                                    {doc.isNoteOnly && (
                                        <FilePlus size={11} className={`flex-shrink-0 ${isSelected ? 'opacity-60' : 'opacity-25'}`} />
                                    )}
                                </div>
                            );
                        })}
                    </div>
                </div>
            </div>
        </>
    );
}

/* ── LLM Mode Toggle (3 modes : Local / Mistral / Gemini) ─────── */
function LLMModeToggle({ currentMode, onChange, disabled }) {
    return (
        <div className="flex items-center bg-white/10 rounded-lg p-0.5 gap-0.5">
            {LLM_MODES.map((m) => {
                const Icon = m.icon;
                const active = currentMode === m.id;
                return (
                    <button
                        key={m.id}
                        onClick={() => !disabled && onChange(m.id)}
                        disabled={disabled}
                        title={`${m.title}\n${m.desc}`}
                        className={`flex items-center gap-1 md:gap-1.5 px-2 md:px-2.5 py-1.5 rounded-md text-[10px] font-bold uppercase tracking-wide transition-all disabled:opacity-40 ${
                            active
                                ? 'bg-white text-[#141414]'
                                : 'text-white/70 hover:text-white hover:bg-white/10'
                        }`}
                    >
                        <Icon size={11} />
                        <span className="hidden lg:inline">{m.label}</span>
                    </button>
                );
            })}
        </div>
    );
}

/* Bannière d'avertissement Gemini (données anonymisées uniquement) */
function GeminiWarningBanner() {
    return (
        <div className="flex items-center gap-2 px-4 py-2 bg-amber-50 border-b border-amber-200 flex-shrink-0">
            <AlertTriangle size={13} className="text-amber-600 flex-shrink-0" />
            <span className="text-[11px] text-amber-800 font-medium">
                Mode démo — données anonymisées uniquement. Gemini est hébergé hors UE,
                ne soumettez aucune information patient identifiable.
            </span>
        </div>
    );
}

/* ── Main RagTerminal ─────────────────────────────────────────── */
export default function RagTerminal() {
    const [documents, setDocuments] = useState([]);
    const [selectedDoc, setSelectedDoc] = useState(null);
    const [multipatient, setMultipatient] = useState(false);

    // Persiste le patient sélectionné entre les refreshs (sessionStorage = onglet courant)
    const setSelectedDocPersisted = (doc) => {
        setSelectedDoc(doc);
        if (doc) sessionStorage.setItem('rag_selected_doc_id', String(doc.id));
        else sessionStorage.removeItem('rag_selected_doc_id');
    };
    const [messages, setMessages] = useState([]);
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);
    const [specialLoading, setSpecialLoading] = useState(false);
    const [elapsed, setElapsed] = useState(0);
    const timerRef = useRef(null);
    const [conversationId, setConversationId] = useState(null);
    const [modelMode, setModelMode] = useState(MODEL_MODES.EXPERT);
    const [llmMode, setLlmMode] = useState(() => localStorage.getItem('rag_llm_mode') || 'local');
    const [lang, setLang] = useState(() => localStorage.getItem('rag_lang') || 'fr');
    const [patientPanelOpen, setPatientPanelOpen] = useState(false);
    const messagesEndRef = useRef(null);
    const textareaRef = useRef(null);

    useEffect(() => {
        fetchDocuments();
        // Charge la préférence LLM enregistrée côté serveur (overrides localStorage)
        api.get('/users/me/llm-modes')
            .then(res => {
                if (res.data?.current) {
                    setLlmMode(res.data.current);
                    localStorage.setItem('rag_llm_mode', res.data.current);
                }
            })
            .catch(() => { /* utilise la valeur localStorage en fallback */ });
    }, []);

    /* Persiste la préférence LLM côté serveur (et localStorage) */
    const handleLlmModeChange = async (mode) => {
        setLlmMode(mode);
        localStorage.setItem('rag_llm_mode', mode);
        try {
            await api.put('/users/me/llm-mode', { preferred_llm_mode: mode });
        } catch (e) {
            // Erreur silencieuse : la préférence reste valide pour la session
        }
    };

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages, loading]);

    useEffect(() => {
        if (textareaRef.current) {
            textareaRef.current.style.height = 'auto';
            textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 150) + 'px';
        }
    }, [input]);

    const fetchDocuments = async () => {
        try {
            const [docsRes, noteRes] = await Promise.all([
                api.get('/documents'),
                api.get('/notes/patients').catch(() => ({ data: { patients: [] } })),
            ]);
            const docs = docsRes.data?.items || docsRes.data?.documents || (Array.isArray(docsRes.data) ? docsRes.data : []);
            const notePatients = noteRes.data?.patients || [];

            // Noms déjà couverts par un PDF (normalisation via utils/patient.js)
            const knownNames = new Set(
                docs.map(d => normalizePatientName(d.patientLabel || extractPatientName(d.title || '')))
            );

            // Patients uniquement en notes (pas de PDF correspondant)
            const virtualDocs = notePatients
                .filter(name => !knownNames.has(normalizePatientName(name)))
                .map((name, i) => ({
                    id: `note_virtual_${i}`,
                    title: name,
                    patientLabel: name,
                    isNoteOnly: true,
                    chunk_count: null,
                    status: 'COMPLETED',
                }));

            const allDocs = [...docs, ...virtualDocs];
            setDocuments(allDocs);

            // Restaure le dernier patient sélectionné (survit aux refreshs)
            const savedId = sessionStorage.getItem('rag_selected_doc_id');
            const restored = savedId ? allDocs.find(d => String(d.id) === savedId) : null;
            if (restored) setSelectedDoc(restored);
            else if (allDocs.length > 0) setSelectedDoc(allDocs[0]);
        } catch (e) {
        }
    };

    // Nom affiché : utilise patientLabel si présent (notes), sinon extractPatientName
    const patientName = selectedDoc
        ? (selectedDoc.patientLabel || extractPatientName(selectedDoc.title || ''))
        : 'le patient';

    const buildQuery = (text) => {
        if (multipatient || !selectedDoc) return text;

        // Pour les PDFs (id numérique) : patient_id est envoyé dans la requête API.
        // Le backend fait un lookup direct DB → pas besoin d'injecter le nom dans le texte.
        if (typeof selectedDoc.id === 'number') return text;

        // Pour les notes-only (id = "note_virtual_0", pas d'entrée DB) :
        // fallback → annotation textuelle pour le backend NLP.
        const name = selectedDoc.patientLabel || extractPatientName(selectedDoc.title || '');
        const lastName = name.split(' ').pop() || '';
        if (lastName && text.toLowerCase().includes(lastName.toLowerCase())) return text;
        return `${text} (Dossier: ${name})`;
    };

    const _startTimer = () => {
        const start = Date.now();
        setElapsed(0);
        timerRef.current = setInterval(() => setElapsed(Date.now() - start), 100);
        return start;
    };
    const _stopTimer = (start) => {
        clearInterval(timerRef.current);
        timerRef.current = null;
        return Date.now() - start;
    };

    const sendMessage = async (text, forceGlobal = false) => {
        const question = (text || input).trim();
        if (!question || loading || specialLoading) return;
        setInput('');
        setLoading(true);
        const start = _startTimer();

        const query = forceGlobal ? question : buildQuery(question);
        // patient_id : ID DB du document (null si cohorte, notes-only, ou aucune sélection)
        const patientId = (!forceGlobal && selectedDoc && typeof selectedDoc.id === 'number')
            ? selectedDoc.id
            : undefined;
        const tempId = Date.now();
        setMessages(prev => [...prev, { role: 'user', content: question }]);

        // AbortController : annule automatiquement si le LLM ne répond pas en 120s.
        // Sans ça, une requête bloquée laisse l'UI en spinner infini.
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 120_000);

        let content = '', sources = [], citations = [], created = false;
        try {
            for await (const data of _sseStream(query, modelMode, conversationId, llmMode, patientId, controller.signal)) {
                if (data.sources) {
                    sources = data.sources;
                    if (created) setMessages(prev => prev.map(m => m.id === tempId ? { ...m, sources } : m));
                }
                if (data.type === 'citations') {
                    citations = data.data || [];
                    if (created) setMessages(prev => prev.map(m => m.id === tempId ? { ...m, citations } : m));
                }
                if (data.content !== undefined) {
                    content += data.content;
                    if (!created) {
                        created = true;
                        setMessages(prev => [...prev, { role: 'assistant', content, sources, citations, id: tempId }]);
                    } else {
                        setMessages(prev => prev.map(m => m.id === tempId ? { ...m, content } : m));
                    }
                }
                if (data.conversation_id) setConversationId(data.conversation_id);
            }
        } catch (err) {
            // AbortError = timeout 120s ou annulation volontaire — message clair pour le médecin
            const errMsg = err.name === 'AbortError'
                ? '⏱ Délai dépassé (120s). Le modèle met trop de temps. Réessayez.'
                : `Erreur : ${err.message}`;
            if (created) setMessages(prev => prev.map(m => m.id === tempId ? { ...m, content: errMsg } : m));
            else setMessages(prev => [...prev, { role: 'assistant', content: errMsg, sources: [] }]);
        } finally {
            clearTimeout(timeoutId);   // annule le timer si la réponse est arrivée à temps
            const totalMs = _stopTimer(start);
            setLoading(false);
            setMessages(prev => prev.map(m => {
                const n = { ...m };
                const isTarget = n.id === tempId;
                delete n.id;
                if (isTarget) n.responseTime = totalMs;
                return n;
            }));
        }
    };

    const runSpecialAction = async (label, promptText) => {
        if (loading || specialLoading) return;
        setSpecialLoading(true);
        const tempId = Date.now();
        setMessages(prev => [...prev, { role: 'user', content: label }]);

        let content = '', sources = [], citations = [], created = false;
        try {
            for await (const data of _sseStream(promptText, modelMode, conversationId, llmMode)) {
                if (data.sources) { sources = data.sources; }
                if (data.type === 'citations') { citations = data.data || []; }
                if (data.content !== undefined) {
                    content += data.content;
                    if (!created) {
                        created = true;
                        setMessages(prev => [...prev, { role: 'assistant', content, sources, citations, id: tempId }]);
                    } else {
                        setMessages(prev => prev.map(m => m.id === tempId ? { ...m, content, sources, citations } : m));
                    }
                }
            }
        } catch (err) {
            const msg = `Erreur : ${err.message}`;
            if (created) setMessages(prev => prev.map(m => m.id === tempId ? { ...m, content: msg } : m));
            else setMessages(prev => [...prev, { role: 'assistant', content: msg, sources: [] }]);
        } finally {
            setSpecialLoading(false);
            setMessages(prev => prev.map(m => { const n = { ...m }; delete n.id; return n; }));
        }
    };

    const generateSummary = () => lang === 'en'
        ? runSpecialAction(
            `Complete medical summary of ${patientName}`,
            `Generate a complete and structured medical summary for ${patientName}. Include: identity, medical history, diagnoses, treatments, lab results, and follow-up plan. Answer in English.`
        )
        : runSpecialAction(
            `Fiche de synthèse complète de ${patientName}`,
            `Génère une fiche de synthèse médicale complète et structurée de ${patientName}. Inclus : identité, antécédents, diagnostics, traitements, résultats biologiques, et plan de suivi.`
        );

    const handleKeyDown = (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    };

    const anyLoading = loading || specialLoading;

    return (
        /* h-full : le parent <main> est déjà flex-1 min-h-0 overflow-hidden = bonne hauteur */
        <div className="h-full flex overflow-hidden">
            {/* Patient sidebar — drawer on mobile, static on desktop */}
            <PatientSidebar
                documents={documents}
                selectedDoc={selectedDoc}
                onSelect={(doc) => { setSelectedDocPersisted(doc); setMultipatient(false); }}
                multipatient={multipatient}
                onToggleMulti={() => { setMultipatient(!multipatient); if (!multipatient) setSelectedDocPersisted(null); }}
                visible={patientPanelOpen}
                onClose={() => setPatientPanelOpen(false)}
            />

            {/* Chat area */}
            <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
                {/* Chat header */}
                <div className="bg-[#141414] text-white px-4 md:px-6 py-3 md:py-4 flex items-center justify-between flex-shrink-0 gap-2">
                    <div className="flex items-center gap-3 min-w-0">
                        {/* Mobile: patient panel toggle */}
                        <button
                            onClick={() => setPatientPanelOpen(true)}
                            className="md:hidden flex-shrink-0 p-2 bg-white/10 hover:bg-white/20 rounded-lg transition-all"
                            title="Patients"
                        >
                            <Users size={15} />
                        </button>
                        <div className="min-w-0">
                            <p className="text-[9px] font-mono uppercase tracking-widest opacity-50 hidden md:block">RAG Terminal · Secure Channel</p>
                            <p className="text-sm font-bold truncate">
                                {multipatient ? 'Tous les patients' : (selectedDoc ? patientName : 'Sélectionner un patient')}
                            </p>
                        </div>
                    </div>

                    <div className="flex items-center gap-1.5 md:gap-2 flex-shrink-0">
                        {/* LLM mode toggle (Local / Mistral / Gemini) */}
                        <LLMModeToggle
                            currentMode={llmMode}
                            onChange={handleLlmModeChange}
                            disabled={anyLoading}
                        />

                        {selectedDoc && !multipatient && (
                            <button
                                onClick={generateSummary}
                                disabled={anyLoading}
                                className="flex items-center gap-1.5 bg-white/10 hover:bg-white/20 disabled:opacity-40 px-2 md:px-3 py-2 rounded-lg text-[10px] font-bold uppercase tracking-wide transition-all"
                            >
                                {specialLoading ? <Loader2 size={12} className="animate-spin" /> : <ClipboardList size={12} />}
                                <span className="hidden md:inline">{lang === 'en' ? 'Summary' : 'Synthèse'}</span>
                            </button>
                        )}

                        {/* Language toggle */}
                        <div className="flex items-center bg-white/10 rounded-lg p-0.5">
                            <button
                                onClick={() => { setLang('fr'); localStorage.setItem('rag_lang', 'fr'); }}
                                className={`px-2 py-1.5 rounded-md text-[10px] font-bold tracking-wide transition-all ${
                                    lang === 'fr' ? 'bg-white text-[#141414]' : 'text-white/60 hover:text-white'
                                }`}
                            >FR</button>
                            <button
                                onClick={() => { setLang('en'); localStorage.setItem('rag_lang', 'en'); }}
                                className={`px-2 py-1.5 rounded-md text-[10px] font-bold tracking-wide transition-all ${
                                    lang === 'en' ? 'bg-white text-[#141414]' : 'text-white/60 hover:text-white'
                                }`}
                            >EN</button>
                        </div>

                        {messages.length > 0 && (
                            <button
                                onClick={() => { setMessages([]); setConversationId(null); }}
                                className="flex items-center gap-1.5 bg-white/10 hover:bg-white/20 px-2 md:px-3 py-2 rounded-lg text-[10px] font-bold uppercase tracking-wide transition-all"
                            >
                                <Trash2 size={12} />
                                <span className="hidden md:inline">{lang === 'en' ? 'Clear' : 'Vider'}</span>
                            </button>
                        )}

                        {anyLoading && (
                            <div className="flex items-center gap-1 bg-white/10 px-2 py-1.5 rounded-lg">
                                <Loader2 size={10} className="animate-spin text-white/60" />
                                <span className="text-[10px] font-mono text-white/80 tabular-nums">
                                    {(elapsed / 1000).toFixed(1)}s
                                </span>
                            </div>
                        )}

                        <div className="hidden sm:flex items-center gap-1.5 ml-1">
                            <div className="w-1.5 h-1.5 bg-emerald-400 rounded-full" />
                            <span className="text-[9px] font-mono opacity-40 hidden md:inline">ENCRYPTED</span>
                        </div>
                    </div>
                </div>

                {/* Avertissement Gemini (mode démo, données anonymisées) */}
                {llmMode === 'gemini' && <GeminiWarningBanner />}

                {/* Bannière mode groupe */}
                {multipatient && (
                    <div className="flex items-center gap-2 px-4 py-2 bg-indigo-50 border-b border-indigo-100 flex-shrink-0">
                        <Users size={13} className="text-indigo-500 flex-shrink-0" />
                        <span className="text-[11px] text-indigo-600 font-medium">
                            {lang === 'en' ? 'Group mode — comparative search across all indexed records' : 'Mode groupe — recherche comparative sur tous les dossiers indexés'}
                        </span>
                        <span className="text-[10px] text-indigo-400 ml-auto">
                            {lang === 'en' ? 'Select a patient to return to individual mode' : 'Sélectionnez un patient pour revenir au mode individuel'}
                        </span>
                    </div>
                )}

                {/* Messages */}
                <ChatMessages messages={messages} loading={anyLoading} messagesEndRef={messagesEndRef} />

                {/* Suggestions */}
                {!anyLoading && (selectedDoc || multipatient) && (
                    <SuggestionsPanel
                        patientName={patientName}
                        lang={lang}
                        onSelect={(prompt, opts) => {
                            if (opts?.global) {
                                // Onglet Cohorte : passer en mode tous les patients
                                setMultipatient(true);
                                setSelectedDocPersisted(null);
                                sendMessage(prompt, true); // forceGlobal: pas de (Dossier: ...)
                            } else {
                                sendMessage(prompt);
                            }
                        }}
                    />
                )}

                {/* Input */}
                <div className="px-2 sm:px-5 py-2 sm:py-4 border-t border-[#141414]/8 bg-white flex-shrink-0">
                    <div className="flex gap-2 items-end">
                        <textarea
                            ref={textareaRef}
                            value={input}
                            onChange={e => setInput(e.target.value)}
                            onKeyDown={handleKeyDown}
                            placeholder={
                                multipatient
                                    ? (lang === 'en' ? 'Question about all patients...' : 'Question sur tous les patients...')
                                    : selectedDoc
                                        ? (lang === 'en' ? `Question about ${patientName}...` : `Question sur ${patientName}...`)
                                        : (lang === 'en' ? 'Select a patient...' : 'Sélectionnez un patient...')
                            }
                            rows={1}
                            disabled={anyLoading || (!selectedDoc && !multipatient)}
                            className="flex-1 resize-none border border-[#141414]/12 rounded-xl px-3 py-3 text-sm outline-none focus:ring-2 ring-[#141414]/8 transition-all disabled:opacity-40"
                            style={{ minHeight: '46px', maxHeight: '150px' }}
                        />
                        <button
                            onClick={() => sendMessage()}
                            disabled={anyLoading || !input.trim() || (!selectedDoc && !multipatient)}
                            className="bg-[#141414] text-white w-12 h-12 rounded-xl flex items-center justify-center hover:bg-[#141414]/85 transition-all disabled:opacity-40 flex-shrink-0"
                        >
                            {anyLoading ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}
