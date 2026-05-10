/**
 * NoteAtomique.jsx — Éditeur de notes médicales avec indexation RAG instantanée
 * ═══════════════════════════════════════════════════════════════════════════════
 *
 * RÔLE
 * ─────
 * Éditeur de texte libre permettant au médecin d'écrire une note clinique
 * (observation, traitement, résultat) et de l'indexer IMMÉDIATEMENT dans
 * le RAG, sans passer par un upload de PDF.
 *
 * AUTO-SAVE (sauvegarde automatique)
 * ────────────────────────────────────
 *   - Debounce 2 secondes après le dernier keystroke
 *   - 1ère sauvegarde → POST /notes  (crée la note + chunk FAISS)
 *   - Suivantes      → PUT  /notes/{id} (met à jour le chunk FAISS)
 *   - Indicateur visuel : "Indexation..." → "⚡ Indexé HH:MM:SS"
 *
 * TOOLBAR
 * ────────
 * Boutons de formatage Markdown inline :
 *   **gras**, _italique_, ## titre, - liste, --- séparateur
 *   + bouton "SOAP" qui insère un template médical standard :
 *     S: (Subjectif) / O: (Objectif) / A: (Assessment) / P: (Plan)
 *
 * AUTOCOMPLETE PATIENT
 * ─────────────────────
 * GET /notes/patients → liste des patients connus.
 * Filtrage en temps réel sur la saisie dans le champ patient.
 *
 * ROUTES API UTILISÉES
 * ─────────────────────
 *   GET  /notes/patients   → autocomplete
 *   POST /notes            → créer note + indexer
 *   PUT  /notes/{note_id}  → mettre à jour note + ré-indexer
 */
import { useState, useEffect, useRef } from 'react';
import {
    FilePlus, CheckCircle2, Loader2, AlertCircle, User,
    Calendar, Bold, Italic, List, Minus, Hash,
    FileText, Clock, Zap, Save, Trash2
} from 'lucide-react';
import api from '../api/client';

const CATEGORIES = [
    { value: 'CONSULTATIONS', label: 'Consultation' },
    { value: 'BIOLOGIE', label: 'Biologie / Analyses' },
    { value: 'TRAITEMENTS', label: 'Traitement / Ordonnance' },
    { value: 'IMAGERIE', label: 'Imagerie (Scanner, IRM…)' },
    { value: 'ECG', label: 'ECG / Cardiologie' },
    { value: 'CONSTANTES', label: 'Constantes vitales' },
    { value: 'ALLERGIES', label: 'Allergies' },
    { value: 'ANTECEDENTS', label: 'Antécédents' },
    { value: 'VACCINATIONS', label: 'Vaccinations' },
    { value: 'HOSPITALISATIONS', label: 'Hospitalisation' },
    { value: 'EXAMENS', label: 'Examens complémentaires' },
    { value: 'AUTRE', label: 'Autre' },
];

const MIN_NOTE_LENGTH = 10;

/** Clé de déduplication pour les noms patients (ordre des tokens insensible à la casse). */
const normName = s => s.toLowerCase().replace(/[_\s]+/g, ' ').trim()
    .split(' ').filter(Boolean).sort().join(' ');

const SOAP_TEMPLATE = `S:
  Motif de consultation :
  Symptômes :
  Antécédents pertinents :

O:
  TA :        FC :        Poids :        SpO2 :
  Biologie :
  Examens :

A:
  Diagnostic principal :
  Diagnostics associés :

P:
  Traitement :
  Suivi prévu :
  Recommandations : `;

function insertAtCursor(el, before, after = '', defaultText = '') {
    const start = el.selectionStart;
    const end = el.selectionEnd;
    const selected = el.value.substring(start, end) || defaultText;
    const newText = el.value.substring(0, start) + before + selected + after + el.value.substring(end);
    const newCursor = start + before.length + selected.length;
    return { text: newText, cursor: newCursor };
}

export default function NoteAtomique() {
    const [patientName, setPatientName] = useState('');
    const [category, setCategory] = useState('CONSULTATIONS');
    const [date, setDate] = useState(new Date().toISOString().split('T')[0]);
    const [text, setText] = useState('');
    const [noteId, setNoteId] = useState(null);
    const [isDirty, setIsDirty] = useState(false);
    const [saveStatus, setSaveStatus] = useState('idle'); // idle | saving | saved | error
    const [lastSaved, setLastSaved] = useState(null);
    const [error, setError] = useState(null);
    const [knownPatients, setKnownPatients] = useState([]);
    const [showSuggestions, setShowSuggestions] = useState(false);
    const [deleting, setDeleting] = useState(false);
    const textareaRef = useRef(null);

    useEffect(() => {
        // Fusionner patients avec notes + patients PDF (pour permettre de créer la 1ère note)
        const extractName = (filename) => {
            const base = (filename || '').replace(/\.(pdf|txt)$/i, '');
            const parts = base.split('_');
            if (parts.length >= 3) {
                return `${parts[parts.length - 1]} ${parts[parts.length - 2]}`;
            }
            return base;
        };

        Promise.allSettled([
            api.get('/notes/patients'),
            api.get('/documents'),
        ]).then(([notesRes, docsRes]) => {
            const noteNames = notesRes.status === 'fulfilled'
                ? (notesRes.value.data?.patients || [])
                : [];
            const docNames = docsRes.status === 'fulfilled'
                ? (docsRes.value.data?.items || []).map(d =>
                    extractName(d.title || ''))
                : [];

            // Fusionner + dédoublonner par clé normalisée, préférer le nom tel que saisi dans les notes
            const seen = new Map();
            [...noteNames, ...docNames].forEach(name => {
                if (!name?.trim()) return;
                const key = normName(name);
                if (!seen.has(key)) seen.set(key, name.trim());
            });
            setKnownPatients([...seen.values()].sort());
        });
    }, []);

    // Pré-remplir le patient si venu depuis le bouton "+ Note" d'un PDF
    useEffect(() => {
        const prefill = sessionStorage.getItem('prefill_patient');
        if (prefill) {
            sessionStorage.removeItem('prefill_patient');
            setPatientName(prefill);
            setIsDirty(false);
        }
    }, []);

    // Load note for editing from sessionStorage (set by KnowledgeBase edit button)
    useEffect(() => {
        const raw = sessionStorage.getItem('edit_note');
        if (!raw) return;
        sessionStorage.removeItem('edit_note');
        try {
            const note = JSON.parse(raw);
            setPatientName(note.patient || '');
            setCategory(note.category || 'CONSULTATIONS');
            setDate(note.date || new Date().toISOString().split('T')[0]);
            setText(note.text || '');
            setNoteId(note.note_id || null);
            setIsDirty(false);
            setSaveStatus('saved');
        } catch { /* ignore */ }
    }, []);

    const filtered = knownPatients.filter(p =>
        patientName.trim() && p.toLowerCase().includes(patientName.toLowerCase())
    );

    const markDirty = () => {
        setIsDirty(true);
        if (saveStatus === 'saved') setSaveStatus('idle');
    };

    const handleSave = async () => {
        const trimmed = text.trim();
        if (trimmed.length < MIN_NOTE_LENGTH) { setError(`Note trop courte (minimum ${MIN_NOTE_LENGTH} caractères)`); return; }
        if (!patientName.trim()) { setError('Le nom du patient est requis'); return; }
        setSaveStatus('saving');
        setError(null);
        try {
            const payload = { patient_name: patientName, category, date, text: trimmed };
            if (noteId) {
                await api.put(`/notes/${noteId}`, payload);
            } else {
                const res = await api.post('/notes', payload);
                setNoteId(res.data.note_id);
            }
            setSaveStatus('saved');
            setLastSaved(new Date());
            setIsDirty(false);
        } catch (e) {
            setSaveStatus('error');
            setError(e.response?.data?.detail || 'Erreur lors de la sauvegarde');
        }
    };

    const handleDelete = async () => {
        if (!noteId) return;
        if (!window.confirm('Supprimer cette note définitivement ?')) return;
        setDeleting(true);
        try {
            await api.delete(`/notes/${noteId}`);
            newNote();
        } catch (e) {
            setError(e.response?.data?.detail || 'Erreur lors de la suppression');
            setDeleting(false);
        }
    };

    const handleTextChange = (e) => {
        setText(e.target.value);
        markDirty();
    };

    const applyFormat = (before, after = '', defaultText = '') => {
        const el = textareaRef.current;
        if (!el) return;
        const { text: newText, cursor } = insertAtCursor(el, before, after, defaultText);
        setText(newText);
        markDirty();
        setTimeout(() => { el.focus(); el.setSelectionRange(cursor, cursor); }, 0);
    };

    const insertSOAP = () => {
        setText(prev => prev ? prev + '\n\n' + SOAP_TEMPLATE : SOAP_TEMPLATE);
        markDirty();
        setTimeout(() => textareaRef.current?.focus(), 0);
    };

    const insertOnNewLine = (prefix) => {
        const el = textareaRef.current;
        if (!el) return;
        const start = el.selectionStart;
        const lineStart = el.value.lastIndexOf('\n', start - 1) + 1;
        const newText = el.value.substring(0, lineStart) + prefix + el.value.substring(lineStart);
        const newCursor = lineStart + prefix.length;
        setText(newText);
        markDirty();
        setTimeout(() => { el.focus(); el.setSelectionRange(newCursor, newCursor); }, 0);
    };

    const newNote = () => {
        setPatientName('');
        setText('');
        setNoteId(null);
        setSaveStatus('idle');
        setLastSaved(null);
        setError(null);
        setIsDirty(false);
        setCategory('CONSULTATIONS');
        setDate(new Date().toISOString().split('T')[0]);
        setDeleting(false);
    };

    const canSave = text.trim().length >= MIN_NOTE_LENGTH && patientName.trim().length > 0
        && saveStatus !== 'saving' && !deleting;

    const statusConfig = {
        idle:   { icon: null, text: isDirty ? 'Non sauvegardé' : 'Nouvelle note', color: isDirty ? 'text-amber-500' : 'text-gray-400' },
        saving: { icon: <Loader2 size={11} className="animate-spin" />, text: 'Indexation...', color: 'text-amber-500' },
        saved:  { icon: <CheckCircle2 size={11} />, text: lastSaved ? `Sauvegardé à ${lastSaved.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}` : 'Sauvegardé', color: isDirty ? 'text-amber-500' : 'text-emerald-500' },
        error:  { icon: <AlertCircle size={11} />, text: 'Erreur', color: 'text-red-500' },
    };
    const status = statusConfig[saveStatus];

    return (
        <div className="h-full flex flex-col bg-[#F4F4F2]">

            {/* Toolbar */}
            <div className="flex-shrink-0 bg-white border-b border-[#141414]/8 px-4 md:px-6 py-2 flex items-center gap-1 flex-wrap">

                {/* Meta fields */}
                <div className="flex items-center gap-2 mr-3">
                    <User size={13} className="opacity-30 flex-shrink-0" />
                    <div className="relative">
                        <input
                            type="text"
                            value={patientName}
                            onChange={e => { setPatientName(e.target.value); setShowSuggestions(true); markDirty(); }}
                            onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
                            onFocus={() => setShowSuggestions(true)}
                            placeholder="Patient..."
                            className="text-xs border border-[#141414]/15 rounded-lg px-2.5 py-1.5 outline-none focus:ring-1 ring-[#141414]/20 w-36 bg-white"
                        />
                        {showSuggestions && filtered.length > 0 && (
                            <div className="absolute top-full left-0 mt-1 bg-white border border-[#141414]/10 rounded-xl shadow-lg z-30 min-w-44 overflow-hidden">
                                {filtered.slice(0, 5).map(p => (
                                    <button key={p} type="button"
                                        onClick={() => { setPatientName(p); setShowSuggestions(false); markDirty(); }}
                                        className="w-full text-left px-3 py-2 text-xs hover:bg-[#141414]/5"
                                    >{p}</button>
                                ))}
                            </div>
                        )}
                    </div>

                    <select value={category} onChange={e => { setCategory(e.target.value); markDirty(); }}
                        className="text-xs border border-[#141414]/15 rounded-lg px-2 py-1.5 outline-none focus:ring-1 ring-[#141414]/20 bg-white cursor-pointer">
                        {CATEGORIES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
                    </select>

                    <div className="flex items-center gap-1">
                        <Calendar size={12} className="opacity-30" />
                        <input type="date" value={date} onChange={e => { setDate(e.target.value); markDirty(); }}
                            className="text-xs border border-[#141414]/15 rounded-lg px-2 py-1.5 outline-none focus:ring-1 ring-[#141414]/20 bg-white" />
                    </div>
                </div>

                <div className="w-px h-6 bg-[#141414]/10 mx-1" />

                {/* Formatting buttons */}
                {[
                    { icon: <Bold size={13} />, title: 'Gras',       action: () => applyFormat('**', '**', 'texte') },
                    { icon: <Italic size={13} />, title: 'Italique', action: () => applyFormat('_', '_', 'texte') },
                    { icon: <Hash size={13} />, title: 'Titre',      action: () => insertOnNewLine('## ') },
                    { icon: <List size={13} />, title: 'Liste',      action: () => insertOnNewLine('- ') },
                    { icon: <Minus size={13} />, title: 'Séparateur', action: () => applyFormat('\n---\n', '') },
                ].map(({ icon, title, action }) => (
                    <button key={title} title={title} onClick={action}
                        className="p-1.5 rounded-lg hover:bg-[#141414]/8 transition-colors text-[#141414]/60 hover:text-[#141414]">
                        {icon}
                    </button>
                ))}

                <div className="w-px h-6 bg-[#141414]/10 mx-1" />

                <button onClick={insertSOAP} title="Insérer template SOAP"
                    className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg hover:bg-[#141414]/8 text-xs font-bold opacity-60 hover:opacity-100 transition-all">
                    <FileText size={12} /> SOAP
                </button>

                {/* Right side */}
                <div className="ml-auto flex items-center gap-2">
                    <div className={`flex items-center gap-1.5 text-[10px] font-semibold ${status.color}`}>
                        {status.icon}
                        <span className="hidden sm:inline">{status.text}</span>
                    </div>
                    {error && (
                        <span className="text-[10px] text-red-500 max-w-32 truncate" title={error}>{error}</span>
                    )}

                    {/* Delete — only for existing notes */}
                    {noteId && (
                        <button onClick={handleDelete} disabled={deleting}
                            title="Supprimer cette note"
                            className="flex items-center gap-1.5 px-3 py-1.5 bg-red-50 text-red-600 border border-red-200 rounded-lg text-xs font-bold hover:bg-red-100 transition-colors disabled:opacity-40">
                            {deleting ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
                            <span className="hidden sm:inline">Supprimer</span>
                        </button>
                    )}

                    {/* Save */}
                    <button onClick={handleSave} disabled={!canSave}
                        title={noteId ? 'Mettre à jour et ré-indexer' : 'Sauvegarder et indexer dans le RAG'}
                        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
                            isDirty ? 'bg-[#141414] text-white hover:bg-[#141414]/80' : 'bg-emerald-600 text-white hover:bg-emerald-700'
                        }`}>
                        {saveStatus === 'saving'
                            ? <Loader2 size={12} className="animate-spin" />
                            : <Save size={12} />}
                        <span className="hidden sm:inline">
                            {saveStatus === 'saving' ? 'Indexation...' : noteId ? 'Mettre à jour' : 'Sauvegarder'}
                        </span>
                    </button>

                    <button onClick={newNote}
                        className="flex items-center gap-1.5 px-3 py-1.5 bg-[#141414]/10 text-[#141414] rounded-lg text-xs font-bold hover:bg-[#141414]/20 transition-colors">
                        <FilePlus size={12} />
                        <span className="hidden md:inline">Nouvelle</span>
                    </button>
                </div>
            </div>

            {/* Editor */}
            <div className="flex-1 overflow-hidden flex flex-col p-4 md:p-6">
                <div className="flex-1 bg-white rounded-2xl border border-[#141414]/10 shadow-sm overflow-hidden flex flex-col">

                    {/* Doc header */}
                    <div className="px-6 md:px-10 pt-6 pb-2 border-b border-[#141414]/5 flex-shrink-0">
                        <div className="flex items-center gap-3">
                            <div className="bg-[#141414] p-2 rounded-xl text-white">
                                <FilePlus size={15} />
                            </div>
                            <div>
                                <p className="font-serif italic font-bold text-base">
                                    {patientName || <span className="opacity-25">Nom du patient</span>}
                                </p>
                                <p className="text-[10px] opacity-35 font-mono uppercase tracking-wider">
                                    {CATEGORIES.find(c => c.value === category)?.label} · {date}
                                    {text && ` · ${text.split(/\s+/).filter(Boolean).length} mots`}
                                </p>
                            </div>
                            {saveStatus === 'saved' && !isDirty && (
                                <div className="ml-auto flex items-center gap-1.5 text-[10px] font-bold text-emerald-600 bg-emerald-50 px-2.5 py-1 rounded-full">
                                    <Zap size={10} /> Indexé dans le RAG
                                </div>
                            )}
                            {isDirty && (
                                <div className="ml-auto flex items-center gap-1.5 text-[10px] font-bold text-amber-600 bg-amber-50 px-2.5 py-1 rounded-full">
                                    <AlertCircle size={10} /> Non sauvegardé
                                </div>
                            )}
                        </div>
                    </div>

                    {/* Textarea */}
                    <textarea
                        ref={textareaRef}
                        value={text}
                        onChange={handleTextChange}
                        placeholder={`Commencez à écrire votre note...\n\nUtilisez le bouton SOAP pour insérer un template structuré.\nCliquez sur « Sauvegarder » pour indexer dans le RAG.`}
                        className="flex-1 w-full resize-none outline-none px-6 md:px-10 py-6 text-sm leading-relaxed font-mono text-[#141414] placeholder:text-[#141414]/20 placeholder:font-sans"
                        style={{ fontFamily: "'JetBrains Mono', 'Fira Code', 'Consolas', monospace" }}
                        spellCheck={false}
                    />

                    {/* Footer */}
                    <div className="flex-shrink-0 border-t border-[#141414]/5 px-6 md:px-10 py-2 flex items-center gap-4 text-[10px] text-[#141414]/30 font-mono">
                        <span>{text.length} caractères</span>
                        <span>{text.split(/\s+/).filter(Boolean).length} mots</span>
                        <span>{text.split('\n').length} lignes</span>
                        {noteId && <span className="opacity-50">ID: {noteId.slice(-8)}</span>}
                        {lastSaved && !isDirty && (
                            <div className="ml-auto flex items-center gap-1 text-emerald-500">
                                <Clock size={9} /> Sauvegardé : {lastSaved.toLocaleTimeString('fr-FR')}
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}
