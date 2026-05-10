/**
 * KnowledgeBase.jsx — Base de connaissances médicale
 * ════════════════════════════════════════════════════
 *
 * RÔLE
 * ─────
 * Interface principale de gestion des dossiers patients :
 *   - Affiche les 171 patients indexés dans FAISS
 *   - Permet l'upload de nouveaux PDFs
 *   - Visualise le contenu du dossier (PDF inline ou sections texte)
 *   - Affiche les notes atomiques liées à chaque patient
 *
 * SOURCES DE DONNÉES
 * ───────────────────
 *   GET /patients?search=X   → liste paginée des patients (table `patients`)
 *   POST /documents/upload   → upload d'un nouveau PDF
 *   GET /patients/{id}/pdf   → PDF du patient pour affichage inline
 *   GET /patients/{id}/chunks → sections du dossier groupées par catégorie
 *
 * DEUX VUES DU DOSSIER
 * ─────────────────────
 *   Vue PDF    → affiche le PDF inline (si disponible dans medical_docs/)
 *   Vue texte  → affiche les chunks FAISS groupés par catégorie
 *                (BIOLOGIE, TRAITEMENTS, CONSULTATIONS, etc.)
 *
 * UPLOAD
 * ───────
 * Un médecin peut uploader un PDF via drag-and-drop ou sélection de fichier.
 * → POST /documents/upload → background task → FAISS rebuildé
 * → Le statut passe de PENDING → PROCESSING → COMPLETED
 */
import { useState, useEffect, useRef } from 'react';
import { Upload, FileText, Trash2, Search, Loader2, CheckCircle2, XCircle, Clock,
    Eye, AlertTriangle, FilePlus, Edit2, X, ChevronDown, ChevronUp, Printer } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import api from '../api/client';
import { extractPatientName } from '../utils/patient';

/* ─── Badge statut upload ────────────────────────────────────────────── */
function StatusBadge({ status }) {
    const map = {
        completed: { cls: 'bg-emerald-50 text-emerald-700', label: 'Traité',     icon: CheckCircle2 },
        processing: { cls: 'bg-amber-50 text-amber-700',   label: 'En cours',   icon: Loader2 },
        pending:    { cls: 'bg-blue-50 text-blue-700',      label: 'En attente', icon: Clock },
        failed:     { cls: 'bg-red-50 text-red-700',        label: 'Erreur',     icon: XCircle },
    };
    const cfg = map[status?.toLowerCase()] || { cls: 'bg-gray-50 text-gray-600', label: status, icon: Clock };
    const Icon = cfg.icon;
    return (
        <span className={`inline-flex items-center gap-1 text-[9px] font-bold px-2 py-0.5 rounded-full uppercase tracking-wider flex-shrink-0 ${cfg.cls}`}>
            <Icon size={10} className={status === 'processing' ? 'animate-spin' : ''} />
            {cfg.label}
        </span>
    );
}

/*  Labels catégories notes  */
const CATEGORY_LABELS = {
    IDENTITE: 'Identité', ANTECEDENTS: 'Antécédents', ALLERGIES: 'Allergies',
    CONSULTATIONS: 'Consultations', TRAITEMENTS: 'Traitements', BIOLOGIE: 'Biologie',
    IMAGERIE: 'Imagerie', ECG: 'ECG', CONSTANTES: 'Constantes', VACCINATIONS: 'Vaccinations',
    HOSPITALISATIONS: 'Hospitalisations', EXAMENS: 'Examens', SYNTHESE: 'Synthèse',
    MOTIF: 'Motif', PLAN: 'Plan', DIAGNOSTIC: 'Diagnostic',
    SUBJECTIF: 'S — Subjectif', OBJECTIF: 'O — Objectif', ASSESSMENT: 'A — Évaluation',
    AUTRE: 'Autre',
};

/*  Modale note atomique  */
function NoteViewModal({ note, onClose }) {
    if (!note) return null;
    return (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
            <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[80vh] flex flex-col"
                onClick={e => e.stopPropagation()}>
                <div className="flex items-center justify-between p-5 border-b border-[#141414]/8">
                    <div>
                        <p className="font-serif italic font-bold text-base">{note.patient}</p>
                        <p className="text-[10px] opacity-40 font-mono uppercase tracking-wider mt-0.5">
                            {CATEGORY_LABELS[note.category] || note.category} · {note.date}
                        </p>
                    </div>
                    <button onClick={onClose} className="p-2 hover:bg-[#141414]/8 rounded-xl transition-colors">
                        <X size={16} />
                    </button>
                </div>
                <div className="flex-1 overflow-y-auto p-5 md:p-8">
                    <pre className="text-sm font-mono leading-relaxed whitespace-pre-wrap text-[#141414]">{note.text}</pre>
                </div>
                <div className="border-t border-[#141414]/5 px-5 py-3 text-[10px] text-[#141414]/30 font-mono flex items-center gap-3">
                    <span>ID: {note.note_id?.slice(-8)}</span>
                    <span>{note.text?.length ?? 0} caractères</span>
                    {note.indexed_at && <span>Indexé le {new Date(note.indexed_at).toLocaleString('fr-FR')}</span>}
                </div>
            </div>
        </div>
    );
}

/*  Visionneur dossier Medilogiciel  */
function DocumentViewerModal({ patientId, onClose }) {
    const [data,    setData]    = useState(null);
    const [loading, setLoading] = useState(true);
    const [error,   setError]   = useState(null);
    const printRef = useRef(null);

    useEffect(() => {
        api.get(`/patients/${patientId}/document`)
            .then(r  => setData(r.data))
            .catch(() => setError('Document introuvable sur le serveur.'))
            .finally(() => setLoading(false));
    }, [patientId]);

    const handlePrint = () => {
        const win = window.open('', '_blank');
        win.document.write(`<html><head><title>${data?.full_name}</title>
            <style>body{font-family:monospace;font-size:12px;white-space:pre-wrap;padding:20px}</style></head>
            <body>${data?.content?.replace(/</g, '&lt;')}</body></html>`);
        win.document.close();
        win.print();
    };

    return (
        <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-2 md:p-6"
            onClick={onClose}>
            <div className="bg-white rounded-2xl shadow-2xl w-full max-w-4xl max-h-[92vh] flex flex-col"
                onClick={e => e.stopPropagation()}>

                {/* En-tête style dossier médical */}
                <div className="bg-[#141414] text-white rounded-t-2xl px-5 py-4 flex items-center justify-between flex-shrink-0">
                    <div>
                        <p className="font-bold text-sm tracking-wide">
                            {loading ? 'Chargement…' : (data?.full_name ?? 'Dossier patient')}
                        </p>
                        <p className="text-[10px] opacity-40 font-mono uppercase tracking-widest mt-0.5">
                            Medispring · Dossier Médical Électronique
                        </p>
                    </div>
                    <div className="flex items-center gap-2">
                        {data && (
                            <button onClick={handlePrint}
                                className="flex items-center gap-1.5 text-[10px] font-bold px-3 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 transition-colors"
                                title="Imprimer">
                                <Printer size={12} /> Imprimer
                            </button>
                        )}
                        <button onClick={onClose}
                            className="p-2 hover:bg-white/10 rounded-xl transition-colors">
                            <X size={16} />
                        </button>
                    </div>
                </div>

                {/* Corps */}
                <div className="flex-1 overflow-y-auto bg-[#fafaf9]" ref={printRef}>
                    {loading ? (
                        <div className="flex items-center justify-center h-64 opacity-30">
                            <Loader2 size={32} className="animate-spin" />
                        </div>
                    ) : error ? (
                        <div className="flex flex-col items-center justify-center h-64 gap-3 opacity-40">
                            <XCircle size={32} />
                            <p className="text-sm italic">{error}</p>
                        </div>
                    ) : (
                        <pre className="p-6 md:p-10 text-[11.5px] md:text-xs font-mono leading-relaxed
                                        whitespace-pre-wrap text-[#1a1a1a] break-words">
                            {data?.content}
                        </pre>
                    )}
                </div>

                {/* Pied de page */}
                {data && (
                    <div className="border-t border-[#141414]/8 px-5 py-2.5 flex items-center justify-between
                                    text-[9px] text-[#141414]/30 font-mono flex-shrink-0">
                        <span>{data.filename}</span>
                        <span>{data.content?.length?.toLocaleString('fr-FR')} caractères</span>
                    </div>
                )}
            </div>
        </div>
    );
}

/* ═══════════════════════════════════════════════════════════════════════ */
export default function KnowledgeBase() {
    const navigate = useNavigate();

    const [patients,  setPatients]  = useState([]);
    const [documents, setDocuments] = useState([]);
    const [loading,   setLoading]   = useState(true);
    const [uploading, setUploading] = useState(false);
    const [uploadMsg, setUploadMsg] = useState('');
    const [searchQuery, setSearchQuery] = useState('');
    const [dragging,  setDragging]  = useState(false);
    const fileInputRef = useRef(null);

    // Notes atomiques
    const [notes,         setNotes]         = useState([]);
    const [notesLoading,  setNotesLoading]  = useState(true);
    const [notesExpanded, setNotesExpanded] = useState(true);
    const [noteSearchQuery, setNoteSearchQuery] = useState('');
    const [viewNote,      setViewNote]      = useState(null);
    const [deletingNoteId, setDeletingNoteId] = useState(null);
    const [expandedDoc,   setExpandedDoc]   = useState(null);

    // Visionneur document Medilogiciel (fallback si PDF absent)
    const [docViewer, setDocViewer] = useState(null);

    /*  Chargement  */
    const fetchData = async () => {
        try {
            const [patientsRes, docsRes, notesRes] = await Promise.all([
                api.get('/patients?page_size=200'),
                api.get('/documents'),
                api.get('/notes'),
            ]);
            setPatients(patientsRes.data?.items || []);
            setDocuments(docsRes.data?.items || docsRes.data?.documents || (Array.isArray(docsRes.data) ? docsRes.data : []));
            setNotes(notesRes.data?.notes || []);
        } catch {
            try {
                const res = await api.get('/documents');
                setDocuments(res.data?.items || []);
            } catch (_) {}
        } finally {
            setLoading(false);
            setNotesLoading(false);
        }
    };

    useEffect(() => {
        fetchData();
        const iv = setInterval(fetchData, 15000);
        return () => clearInterval(iv);
    }, []);

    /*  Upload  */
    const uploadFiles = async (fileList) => {
        const files = Array.from(fileList).filter(f => /\.(pdf|txt)$/i.test(f.name));
        if (files.length === 0) return;
        setUploading(true);
        setUploadMsg(`Envoi de ${files.length} fichier(s)…`);
        try {
            for (const file of files) {
                setUploadMsg(`Indexation : ${file.name}`);
                const fd = new FormData();
                fd.append('file', file);
                await api.post('/documents/upload', fd, { headers: { 'Content-Type': 'multipart/form-data' } });
            }
            setUploadMsg('');
            fetchData();
        } catch {
            setUploadMsg('Erreur lors de l\'upload');
        } finally {
            setUploading(false);
            if (fileInputRef.current) fileInputRef.current.value = '';
        }
    };

    const deleteDocument = async (id) => {
        if (!window.confirm('Supprimer ce document ?')) return;
        try { await api.delete(`/documents/${id}`); fetchData(); } catch {}
    };

    const [deleteAllConfirm, setDeleteAllConfirm] = useState(false);
    const [deletingAll,      setDeletingAll]      = useState(false);

    const deleteAllDocuments = async () => {
        if (!deleteAllConfirm) {
            setDeleteAllConfirm(true);
            setTimeout(() => setDeleteAllConfirm(false), 4000);
            return;
        }
        setDeletingAll(true);
        setDeleteAllConfirm(false);
        try { await api.delete('/documents/bulk/delete-all'); await fetchData(); }
        catch {} finally { setDeletingAll(false); }
    };

    const deleteNote = async (note_id) => {
        if (!window.confirm('Supprimer cette note ?')) return;
        setDeletingNoteId(note_id);
        try {
            await api.delete(`/notes/${note_id}`);
            setNotes(prev => prev.filter(n => n.note_id !== note_id));
        } catch {} finally { setDeletingNoteId(null); }
    };

    const editNote = (note) => {
        sessionStorage.setItem('edit_note', JSON.stringify(note));
        navigate('/notes');
    };

    /*  Listes  */
    const patientList = patients.length > 0 ? patients : documents.map(doc => ({
        id: doc.id,
        nom: extractPatientName(doc.filename || doc.title || '').split(' ').pop() || '',
        prenom: extractPatientName(doc.filename || doc.title || '').split(' ').slice(0, -1).join(' ') || '',
        full_name: extractPatientName(doc.title || doc.filename || ''),
        source_filename: doc.filename || '',
        chunk_count: doc.chunk_count ?? 0,
        in_faiss: (doc.chunk_count ?? 0) > 0,
        doc_id: doc.id,
        doc_status: doc.status,
        note_count: 0,
    }));

    const filtered = patientList.filter(p => {
        if (!searchQuery.trim()) return true;
        const q = searchQuery.toLowerCase();
        return p.full_name?.toLowerCase().includes(q) || p.nom?.toLowerCase().includes(q)
            || p.prenom?.toLowerCase().includes(q) || p.source_filename?.toLowerCase().includes(q);
    });

    const filteredNotes = notes.filter(note => {
        if (!noteSearchQuery.trim()) return true;
        const q = noteSearchQuery.toLowerCase();
        return note.patient?.toLowerCase().includes(q) || note.category?.toLowerCase().includes(q)
            || note.text?.toLowerCase().includes(q);
    });

    /*  Rendu  */
    return (
        <div className="p-4 md:p-10 max-w-6xl mx-auto space-y-6 md:space-y-8">

            {/* Modales */}
            {viewNote  && <NoteViewModal note={viewNote} onClose={() => setViewNote(null)} />}
            {docViewer && <DocumentViewerModal patientId={docViewer} onClose={() => setDocViewer(null)} />}

            {/* Upload */}
            <div className="bg-white border border-[#141414]/10 rounded-2xl p-4 md:p-8 shadow-sm">
                <h3 className="text-base md:text-lg font-serif italic font-bold mb-4 md:mb-6">Ajouter des dossiers patients</h3>
                <div
                    onClick={() => !uploading && fileInputRef.current?.click()}
                    onDragOver={e => { e.preventDefault(); setDragging(true); }}
                    onDragLeave={() => setDragging(false)}
                    onDrop={e => { e.preventDefault(); setDragging(false); uploadFiles(e.dataTransfer.files); }}
                    className={`border-2 border-dashed rounded-xl p-6 md:p-10 text-center transition-all cursor-pointer
                        ${dragging ? 'border-[#141414]/40 bg-[#141414]/3' : 'border-[#141414]/15 hover:border-[#141414]/35 hover:bg-[#141414]/2'}
                        ${uploading ? 'opacity-60 cursor-wait' : ''}`}
                >
                    <input ref={fileInputRef} type="file" accept=".pdf,.txt" multiple className="hidden"
                        onChange={e => uploadFiles(e.target.files)} />
                    {uploading ? (
                        <div className="flex flex-col items-center gap-3">
                            <Loader2 size={24} className="animate-spin opacity-40" />
                            <p className="text-sm font-semibold opacity-50 break-all px-2">{uploadMsg}</p>
                        </div>
                    ) : (
                        <div className="flex flex-col items-center gap-2">
                            <Upload size={24} className="opacity-25" />
                            <p className="text-sm font-bold opacity-55">Glisser-déposer ou appuyer pour sélectionner</p>
                            <p className="text-[10px] uppercase tracking-widest opacity-30">PDF ou TXT · Multi-fichiers</p>
                        </div>
                    )}
                </div>
            </div>

            {/* Liste patients */}
            <div className="bg-white border border-[#141414]/10 rounded-2xl overflow-hidden shadow-sm">

                <div className="p-3 md:p-6 border-b border-[#141414]/5 bg-[#141414]/3">
                    <div className="flex items-center justify-between gap-3 mb-2 md:mb-0">
                        <h3 className="text-[10px] font-mono uppercase tracking-widest opacity-40">Base de connaissances</h3>
                        <div className="flex items-center gap-2">
                            <span className="text-[10px] font-bold bg-[#141414] text-white px-2.5 py-1 rounded-lg whitespace-nowrap">
                                {patientList.length} dossier{patientList.length !== 1 ? 's' : ''}
                            </span>
                            {documents.length > 0 && (
                                <button onClick={deleteAllDocuments} disabled={deletingAll}
                                    className={`inline-flex items-center gap-1.5 text-[10px] font-bold px-2.5 py-1 rounded-lg transition-all whitespace-nowrap
                                        ${deleteAllConfirm ? 'bg-red-600 text-white animate-pulse' : 'bg-red-50 text-red-600 hover:bg-red-100'}
                                        ${deletingAll ? 'opacity-50 cursor-wait' : ''}`}
                                    title="Supprimer tous les dossiers">
                                    {deletingAll ? <Loader2 size={10} className="animate-spin" /> : <AlertTriangle size={10} />}
                                    {deletingAll ? 'Suppression…' : deleteAllConfirm ? 'Confirmer ?' : 'Tout supprimer'}
                                </button>
                            )}
                        </div>
                    </div>
                    {patientList.length > 0 && (
                        <div className="relative mt-2">
                            <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 opacity-35" />
                            <input type="text" placeholder="Rechercher un patient…"
                                value={searchQuery} onChange={e => setSearchQuery(e.target.value)}
                                className="w-full md:w-64 pl-8 pr-4 py-2 text-xs border border-[#141414]/10 rounded-lg outline-none focus:ring-1 ring-[#141414]/10 bg-white" />
                        </div>
                    )}
                </div>

                {loading ? (
                    <div className="p-12 flex justify-center opacity-30">
                        <div className="flex gap-1.5">
                            <span className="loading-dot" /><span className="loading-dot" /><span className="loading-dot" />
                        </div>
                    </div>
                ) : filtered.length > 0 ? (
                    <div className="divide-y divide-[#141414]/5">
                        {filtered.map(pat => {
                            const name = pat.full_name || extractPatientName(pat.source_filename || '');
                            const patNotes = notes.filter(n =>
                                n.source === pat.source_filename ||
                                n.patient?.toLowerCase() === name.toLowerCase()
                            );
                            const isExpanded = expandedDoc === pat.id;
                            const hasDoc = pat.in_faiss || !!pat.doc_id;

                            return (
                                <div key={pat.id} className="divide-y divide-[#141414]/5">

                                    {/* Ligne patient */}
                                    <div className="p-3 md:p-5 flex items-center gap-3 group hover:bg-[#141414]/2 transition-colors">
                                        <div className="bg-[#141414]/5 p-2 md:p-3 rounded-xl text-[#141414]/40 group-hover:bg-[#141414] group-hover:text-white transition-all flex-shrink-0">
                                            <FileText size={16} />
                                        </div>
                                        <div className="flex-1 min-w-0">
                                            <h4 className="text-sm font-bold truncate">{name}</h4>
                                            <div className="flex items-center gap-2 flex-wrap mt-0.5">
                                                <span className="text-[10px] opacity-40 uppercase tracking-widest">
                                                    {pat.chunk_count ?? 0} extraits indexés
                                                    {pat.patient_code ? ` · ${pat.patient_code}` : ''}
                                                </span>
                                                {pat.doc_status && <StatusBadge status={pat.doc_status} />}
                                                {!pat.doc_status && pat.in_faiss && (
                                                    <span className="inline-flex items-center gap-1 text-[9px] font-bold px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 uppercase tracking-wider">
                                                        <CheckCircle2 size={9} /> Indexé
                                                    </span>
                                                )}
                                                {(patNotes.length > 0 || pat.note_count > 0) && (
                                                    <button onClick={() => setExpandedDoc(isExpanded ? null : pat.id)}
                                                        className="inline-flex items-center gap-1 text-[9px] font-bold px-1.5 py-0.5 rounded-full bg-amber-50 text-amber-700 hover:bg-amber-100 transition-colors">
                                                        <FilePlus size={9} />
                                                        {patNotes.length || pat.note_count} note{(patNotes.length || pat.note_count) > 1 ? 's' : ''}
                                                        {isExpanded ? <ChevronUp size={9} /> : <ChevronDown size={9} />}
                                                    </button>
                                                )}
                                            </div>
                                        </div>

                                        <div className="flex items-center gap-1 flex-shrink-0">
                                            {/* + Note */}
                                            <button
                                                onClick={() => { sessionStorage.setItem('prefill_patient', name); navigate('/notes'); }}
                                                className="flex items-center gap-1 px-2 py-1.5 hover:bg-amber-50 hover:text-amber-600 rounded-lg transition-all md:opacity-0 md:group-hover:opacity-100 text-[10px] font-bold"
                                                title="Ajouter une note">
                                                <FilePlus size={12} />
                                                <span className="hidden lg:inline">+ Note</span>
                                            </button>

                                            {/* Voir le dossier Medilogiciel — PDF dans nouvel onglet */}
                                            {hasDoc && (
                                                <button
                                                    onClick={() => {
                                                        // URL directe avec token — pas de blob, pas d'erreur Chrome
                                                        const token = localStorage.getItem('access_token');
                                                        window.open(
                                                            `/api/v1/patients/${pat.id}/pdf?token=${encodeURIComponent(token)}`,
                                                            '_blank', 'noopener,noreferrer'
                                                        );
                                                    }}
                                                    className="p-2 hover:bg-blue-50 hover:text-blue-600 rounded-lg transition-all opacity-40 hover:opacity-100"
                                                    title="Ouvrir le dossier PDF Medilogiciel">
                                                    <Eye size={15} />
                                                </button>
                                            )}

                                            {/* Supprimer */}
                                            {!!pat.doc_id && (
                                                <button onClick={() => deleteDocument(pat.doc_id)}
                                                    className="p-2 hover:bg-red-50 hover:text-red-500 rounded-lg transition-all md:opacity-0 md:group-hover:opacity-100"
                                                    title="Supprimer">
                                                    <Trash2 size={15} />
                                                </button>
                                            )}
                                        </div>
                                    </div>

                                    {/* Notes inline */}
                                    {isExpanded && patNotes.length > 0 && (
                                        <div className="bg-amber-50/40 border-t border-amber-100 px-4 md:px-8 py-3 space-y-2">
                                            {patNotes.map(note => (
                                                <div key={note.note_id} className="flex items-start gap-3 p-2.5 bg-white rounded-xl border border-amber-100 group/note">
                                                    <div className="flex-1 min-w-0">
                                                        <div className="flex items-center gap-2 flex-wrap">
                                                            <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-full bg-[#141414]/8 uppercase tracking-wider">
                                                                {CATEGORY_LABELS[note.category] || note.category}
                                                            </span>
                                                            {note.date && <span className="text-[9px] opacity-40 font-mono">{note.date}</span>}
                                                        </div>
                                                        <p className="text-xs opacity-60 mt-1 line-clamp-2 leading-relaxed">{note.preview || note.text}</p>
                                                    </div>
                                                    <div className="flex items-center gap-1 flex-shrink-0 opacity-0 group-hover/note:opacity-100 transition-opacity">
                                                        <button onClick={() => setViewNote(note)} className="p-1.5 hover:bg-blue-50 hover:text-blue-500 rounded-lg" title="Voir"><Eye size={13} /></button>
                                                        <button onClick={() => editNote(note)} className="p-1.5 hover:bg-amber-100 hover:text-amber-600 rounded-lg" title="Modifier"><Edit2 size={13} /></button>
                                                        <button onClick={() => deleteNote(note.note_id)} disabled={deletingNoteId === note.note_id}
                                                            className="p-1.5 hover:bg-red-50 hover:text-red-500 rounded-lg disabled:opacity-40" title="Supprimer">
                                                            {deletingNoteId === note.note_id ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
                                                        </button>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                ) : (
                    <div className="p-12 text-center opacity-25 italic text-sm">
                        {searchQuery ? 'Aucun résultat' : 'Aucun document indexé'}
                    </div>
                )}
            </div>

            {/* Notes atomiques */}
            <div className="bg-white border border-[#141414]/10 rounded-2xl overflow-hidden shadow-sm">
                <div className="p-3 md:p-6 border-b border-[#141414]/5 bg-[#141414]/3">
                    <div className="flex items-center justify-between gap-3">
                        <div className="flex items-center gap-2">
                            <h3 className="text-[10px] font-mono uppercase tracking-widest opacity-40">Notes Atomiques</h3>
                            <span className="text-[10px] font-bold bg-[#141414] text-white px-2.5 py-1 rounded-lg">
                                {notes.length} note{notes.length !== 1 ? 's' : ''}
                            </span>
                        </div>
                        <div className="flex items-center gap-2">
                            <button onClick={() => navigate('/notes')}
                                className="inline-flex items-center gap-1.5 text-[10px] font-bold px-2.5 py-1 rounded-lg bg-[#141414]/8 hover:bg-[#141414]/15 transition-colors">
                                <FilePlus size={10} /> Nouvelle note
                            </button>
                            <button onClick={() => setNotesExpanded(p => !p)} className="p-1.5 hover:bg-[#141414]/8 rounded-lg transition-colors">
                                {notesExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                            </button>
                        </div>
                    </div>
                    {notesExpanded && notes.length > 3 && (
                        <div className="relative mt-2">
                            <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 opacity-35" />
                            <input type="text" placeholder="Rechercher dans les notes…"
                                value={noteSearchQuery} onChange={e => setNoteSearchQuery(e.target.value)}
                                className="w-full md:w-64 pl-8 pr-4 py-2 text-xs border border-[#141414]/10 rounded-lg outline-none focus:ring-1 ring-[#141414]/10 bg-white" />
                        </div>
                    )}
                </div>

                {notesExpanded && (
                    notesLoading ? (
                        <div className="p-12 flex justify-center opacity-30">
                            <div className="flex gap-1.5">
                                <span className="loading-dot" /><span className="loading-dot" /><span className="loading-dot" />
                            </div>
                        </div>
                    ) : filteredNotes.length > 0 ? (
                        <div className="divide-y divide-[#141414]/5">
                            {filteredNotes.map(note => (
                                <div key={note.note_id} className="p-3 md:p-5 flex items-start gap-3 group hover:bg-[#141414]/2 transition-colors">
                                    <div className="bg-[#141414]/5 p-2 rounded-xl text-[#141414]/40 group-hover:bg-[#141414] group-hover:text-white transition-all flex-shrink-0 mt-0.5">
                                        <FilePlus size={14} />
                                    </div>
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2 flex-wrap">
                                            <h4 className="text-sm font-bold">{note.patient}</h4>
                                            <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-full bg-[#141414]/8 uppercase tracking-wider">
                                                {CATEGORY_LABELS[note.category] || note.category}
                                            </span>
                                            {note.date && <span className="text-[9px] opacity-40 font-mono">{note.date}</span>}
                                        </div>
                                        <p className="text-xs opacity-50 mt-1 line-clamp-2 leading-relaxed">{note.preview || note.text}</p>
                                        <p className="text-[9px] opacity-25 font-mono mt-1">
                                            ID: {note.note_id?.slice(-8)}
                                            {note.indexed_at && ` · ${new Date(note.indexed_at).toLocaleDateString('fr-FR')}`}
                                        </p>
                                    </div>
                                    <div className="flex items-center gap-1 flex-shrink-0">
                                        <button onClick={() => setViewNote(note)}
                                            className="p-2 hover:bg-blue-50 hover:text-blue-500 rounded-lg transition-all md:opacity-0 md:group-hover:opacity-100" title="Voir">
                                            <Eye size={14} />
                                        </button>
                                        <button onClick={() => editNote(note)}
                                            className="p-2 hover:bg-amber-50 hover:text-amber-500 rounded-lg transition-all md:opacity-0 md:group-hover:opacity-100" title="Modifier">
                                            <Edit2 size={14} />
                                        </button>
                                        <button onClick={() => deleteNote(note.note_id)} disabled={deletingNoteId === note.note_id}
                                            className="p-2 hover:bg-red-50 hover:text-red-500 rounded-lg transition-all md:opacity-0 md:group-hover:opacity-100 disabled:opacity-40" title="Supprimer">
                                            {deletingNoteId === note.note_id ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                                        </button>
                                    </div>
                                </div>
                            ))}
                        </div>
                    ) : (
                        <div className="p-12 text-center opacity-25 italic text-sm">
                            {noteSearchQuery ? 'Aucun résultat' : 'Aucune note atomique'}
                        </div>
                    )
                )}
            </div>
        </div>
    );
}
