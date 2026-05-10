/**
 * ChatMessages.jsx — Affichage des messages du chat RAG
 * ════════════════════════════════════════════════════════
 *
 * RÔLE
 * ─────
 * Composant qui rend la liste des messages échangés entre le médecin
 * et le LLM RAG. Gère le Markdown, les citations et les sources.
 *
 * FONCTIONNALITÉS
 * ────────────────
 *   • Bulles de chat (user à droite, assistant à gauche)
 *   • ReactMarkdown : rend le Markdown du LLM (gras, listes, tableaux)
 *   • Citations [N] cliquables → ouvre un modal avec l'extrait source
 *   • Badge LLM (Mistral / Gemini / Local) sur chaque réponse
 *   • Catégories médicales colorées (BIOLOGIE, TRAITEMENTS, etc.)
 *   • Tables mobiles : scroll horizontal sur petits écrans
 *
 * PROPS
 * ──────
 *   messages     : tableau de { role, content, sources, citations, llm_mode }
 *   loading      : boolean — affiche les 3 points animés si true
 *   citationMap  : tableau de sources numérotées [{ source, text, score, category }]
 */
import React, { useState, useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ShieldCheck, X, FileText, ChevronDown, ChevronRight, BookOpen } from 'lucide-react';

/* ══════════════════════════════════════════════════════════════════
   CATÉGORIES MÉDICALES
   ══════════════════════════════════════════════════════════════════ */
const CAT_LABEL = {
    BIOLOGIE:'Biologie', TRAITEMENTS:'Traitement', CONSULTATIONS:'Consultation',
    DIAGNOSTIC:'Diagnostic', ALLERGIES:'Allergie', ANTECEDENTS:'Antécédent',
    IDENTITE:'Identité', IMAGERIE:'Imagerie', ECG:'ECG', CONSTANTES:'Constantes',
    VACCINATIONS:'Vaccin', HOSPITALISATIONS:'Hospitalisation', EXAMENS:'Examen',
    SYNTHESE:'Synthèse', MOTIF:'Motif', PLAN:'Plan thérapeutique',
    SUBJECTIF:'Subjectif', OBJECTIF:'Objectif', ASSESSMENT:'Évaluation', AUTRE:'Note',
};
const CAT_COLOR = {
    BIOLOGIE:         'bg-purple-100 text-purple-700 border-purple-200',
    TRAITEMENTS:      'bg-green-100 text-green-700 border-green-200',
    CONSULTATIONS:    'bg-blue-100 text-blue-700 border-blue-200',
    DIAGNOSTIC:       'bg-fuchsia-100 text-fuchsia-700 border-fuchsia-200',
    ALLERGIES:        'bg-rose-100 text-rose-700 border-rose-200',
    ANTECEDENTS:      'bg-amber-100 text-amber-700 border-amber-200',
    IDENTITE:         'bg-slate-100 text-slate-700 border-slate-200',
    IMAGERIE:         'bg-cyan-100 text-cyan-700 border-cyan-200',
    ECG:              'bg-red-100 text-red-700 border-red-200',
    CONSTANTES:       'bg-orange-100 text-orange-700 border-orange-200',
    VACCINATIONS:     'bg-teal-100 text-teal-700 border-teal-200',
    HOSPITALISATIONS: 'bg-indigo-100 text-indigo-700 border-indigo-200',
    EXAMENS:          'bg-sky-100 text-sky-700 border-sky-200',
    SYNTHESE:         'bg-violet-100 text-violet-700 border-violet-200',
    MOTIF:            'bg-lime-100 text-lime-700 border-lime-200',
    PLAN:             'bg-emerald-100 text-emerald-700 border-emerald-200',
    AUTRE:            'bg-gray-100 text-gray-600 border-gray-200',
};
const catColor = (c) => CAT_COLOR[c] || CAT_COLOR.AUTRE;
const catLabel = (c) => CAT_LABEL[c] || c || 'Note';

/* ══════════════════════════════════════════════════════════════════
   NETTOYAGE — supprime TOUS les marqueurs de citation du texte
   (cf.[1]), [1][2], __C1__, etc. → texte médical propre
   ══════════════════════════════════════════════════════════════════ */
function cleanText(text) {
    if (!text) return text;
    return text
        .replace(/\s*\(cf\.\s*\[[\d,\s\[\]]*\]\)\s*/g, ' ')  // (cf.[1, 2])
        .replace(/\s*\[[\d]+(?:,\s*\d+)*\]\s*/g, ' ')         // [1] [1,2]
        .replace(/`__C\d+__`/g, '')                            // `__C1__`
        .replace(/__C\d+__/g, '')                              // __C1__
        .replace(/\s{2,}/g, ' ')
        .replace(/\(\s*\)/g, '')
        .trim();
}

/* ══════════════════════════════════════════════════════════════════
   EXTRACTION TEXTE HAST (tables mobiles)
   ══════════════════════════════════════════════════════════════════ */
function extractHastText(nodes) {
    if (!nodes) return '';
    return nodes.reduce((acc, n) => {
        if (n.type === 'text') return acc + n.value;
        if (n.children) return acc + extractHastText(n.children);
        return acc;
    }, '').trim();
}

/* ══════════════════════════════════════════════════════════════════
   MODAL EXTRAIT — s'ouvre au clic sur une source
   ══════════════════════════════════════════════════════════════════ */
function SourceModal({ cite, onClose }) {
    if (!cite) return null;
    const cat = cite.category || 'AUTRE';
    return (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-end sm:items-center
                        justify-center p-0 sm:p-4" onClick={onClose}>
            <div className="bg-white rounded-t-2xl sm:rounded-2xl shadow-2xl w-full
                            sm:max-w-lg flex flex-col max-h-[80vh]"
                 onClick={e => e.stopPropagation()}>

                {/* En-tête */}
                <div className={`flex items-center gap-3 px-5 pt-5 pb-4
                                 border-b border-[#141414]/8 rounded-t-2xl`}>
                    <span className={`text-[11px] font-bold px-3 py-1 rounded-lg border ${catColor(cat)}`}>
                        {catLabel(cat)}
                    </span>
                    <div className="flex-1 min-w-0">
                        <p className="text-sm font-bold truncate">{cite.patient}</p>
                        <p className="text-[9px] opacity-40 font-mono mt-0.5">
                            Source · Medispring
                        </p>
                    </div>
                    <button onClick={onClose}
                        className="p-2 hover:bg-[#141414]/6 rounded-xl transition-colors flex-shrink-0">
                        <X size={15} />
                    </button>
                </div>

                {/* Extrait */}
                <div className="px-5 py-5 flex-1 overflow-y-auto">
                    <p className="text-[10px] font-bold uppercase tracking-widest
                                  text-[#141414]/30 mb-3">
                        Extrait du dossier utilisé pour générer cette réponse
                    </p>
                    <div className={`rounded-2xl p-4 border ${catColor(cat)}`}>
                        <p className="text-[13px] leading-relaxed text-[#141414]/80
                                      whitespace-pre-wrap font-mono">
                            {cite.preview || '—'}
                        </p>
                    </div>
                </div>

                {/* Pied */}
                <div className="px-5 pb-4 border-t border-[#141414]/6 pt-3
                                flex items-center gap-3 text-[9px]">
                    <FileText size={11} className="opacity-25 flex-shrink-0" />
                    <span className="opacity-30 truncate">{cite.source}</span>
                    {cite.score_pct && (
                        <span className="ml-auto opacity-30 flex-shrink-0 font-mono">
                            Pertinence {cite.score_pct}
                        </span>
                    )}
                </div>
            </div>
        </div>
    );
}

/* ══════════════════════════════════════════════════════════════════
   PANNEAU SOURCES — bien visible, boutons clairs et cliquables
   ══════════════════════════════════════════════════════════════════ */
function SourcesHeader({ citations, sources, onCiteClick }) {
    const hasCite = citations && citations.length > 0;
    const hasSrc  = sources   && sources.length   > 0;
    if (!hasCite && !hasSrc) return null;

    // Patients uniques
    const patients = hasCite
        ? [...new Set(citations.map(c => c.patient).filter(Boolean))]
        : [...new Set(sources.map(s => s.patient || s.document_title).filter(Boolean))];

    // Sections uniques avec leur première citation
    const bySection = {};
    if (hasCite) {
        citations.forEach(c => {
            const cat = c.category || 'AUTRE';
            if (!bySection[cat]) bySection[cat] = c;
        });
    }
    const sections = Object.keys(bySection);

    // Couleurs fixes pour les boutons (Tailwind statique)
    const BADGE_CLASSES = {
        BIOLOGIE:         'bg-purple-100 text-purple-800 border-purple-300 hover:bg-purple-200',
        TRAITEMENTS:      'bg-green-100 text-green-800 border-green-300 hover:bg-green-200',
        CONSULTATIONS:    'bg-blue-100 text-blue-800 border-blue-300 hover:bg-blue-200',
        DIAGNOSTIC:       'bg-pink-100 text-pink-800 border-pink-300 hover:bg-pink-200',
        ALLERGIES:        'bg-red-100 text-red-800 border-red-300 hover:bg-red-200',
        ANTECEDENTS:      'bg-yellow-100 text-yellow-800 border-yellow-300 hover:bg-yellow-200',
        IDENTITE:         'bg-gray-100 text-gray-800 border-gray-300 hover:bg-gray-200',
        IMAGERIE:         'bg-cyan-100 text-cyan-800 border-cyan-300 hover:bg-cyan-200',
        ECG:              'bg-red-100 text-red-800 border-red-300 hover:bg-red-200',
        CONSTANTES:       'bg-orange-100 text-orange-800 border-orange-300 hover:bg-orange-200',
        VACCINATIONS:     'bg-teal-100 text-teal-800 border-teal-300 hover:bg-teal-200',
        HOSPITALISATIONS: 'bg-indigo-100 text-indigo-800 border-indigo-300 hover:bg-indigo-200',
        EXAMENS:          'bg-sky-100 text-sky-800 border-sky-300 hover:bg-sky-200',
        SYNTHESE:         'bg-violet-100 text-violet-800 border-violet-300 hover:bg-violet-200',
        MOTIF:            'bg-lime-100 text-lime-800 border-lime-300 hover:bg-lime-200',
        PLAN:             'bg-emerald-100 text-emerald-800 border-emerald-300 hover:bg-emerald-200',
        AUTRE:            'bg-gray-100 text-gray-700 border-gray-300 hover:bg-gray-200',
    };
    const badgeClass = (cat) => BADGE_CLASSES[cat] || BADGE_CLASSES.AUTRE;

    return (
        <div className="mb-4 rounded-xl border border-[#141414]/10 bg-[#141414]/3 p-3">
            {/* Ligne titre + patient */}
            <div className="flex items-center gap-2 mb-2">
                <FileText size={13} className="text-[#141414]/40 flex-shrink-0" />
                <span className="text-[10px] font-bold uppercase tracking-wider text-[#141414]/40">
                    Sources du dossier
                </span>
                {patients.map(p => (
                    <span key={p}
                        className="text-[11px] font-bold text-[#141414] bg-white
                                   border border-[#141414]/10 px-2.5 py-0.5 rounded-lg">
                        {p}
                    </span>
                ))}
                {hasCite && (
                    <span className="ml-auto text-[9px] text-[#141414]/30 font-mono">
                        {citations.length} extrait{citations.length > 1 ? 's' : ''}
                    </span>
                )}
            </div>

            {/* Boutons sections — gros, colorés, cliquables */}
            {sections.length > 0 ? (
                <div className="flex flex-wrap gap-1.5">
                    {sections.map(cat => (
                        <button
                            key={cat}
                            onClick={() => onCiteClick(bySection[cat])}
                            className={`text-[11px] font-semibold px-3 py-1.5 rounded-lg
                                        border transition-colors cursor-pointer
                                        ${badgeClass(cat)}`}
                        >
                            {catLabel(cat)}
                        </button>
                    ))}
                    <span className="text-[9px] text-[#141414]/30 self-center ml-1">
                        ← cliquer pour voir l'extrait
                    </span>
                </div>
            ) : (
                /* Fallback si pas de sections : montrer les sources brutes */
                <div className="flex flex-wrap gap-1.5">
                    {sources.slice(0, 4).map((src, i) => (
                        <span key={i}
                            className="text-[10px] text-[#141414]/50 bg-white
                                       border border-[#141414]/10 px-2 py-1 rounded-lg">
                            {src.patient || src.document_title}
                        </span>
                    ))}
                </div>
            )}
        </div>
    );
}

/* ══════════════════════════════════════════════════════════════════
   LISTE EXTRAITS (dépliable en bas)
   ══════════════════════════════════════════════════════════════════ */
function SourcesList({ citations, onCiteClick }) {
    const [open, setOpen] = useState(false);
    if (!citations || citations.length === 0) return null;

    // Grouper par section pour l'affichage
    const bySection = {};
    citations.forEach(c => {
        const cat = c.category || 'AUTRE';
        if (!bySection[cat]) bySection[cat] = [];
        bySection[cat].push(c);
    });

    return (
        <div className="mt-4 pt-3 border-t border-[#141414]/6">
            <button
                onClick={() => setOpen(!open)}
                className="flex items-center gap-2 text-[10px] font-bold
                           opacity-35 hover:opacity-70 transition-opacity w-full"
            >
                {open ? <ChevronDown size={12}/> : <ChevronRight size={12}/>}
                {open ? 'Masquer les extraits' : `Consulter les ${citations.length} extraits du dossier`}
            </button>

            {open && (
                <div className="mt-3 space-y-2">
                    {Object.entries(bySection).map(([cat, cites]) => (
                        <div key={cat}>
                            <p className={`text-[9px] font-bold uppercase tracking-wider
                                           px-2 py-0.5 rounded-lg inline-block mb-1.5
                                           ${catColor(cat)}`}>
                                {catLabel(cat)}
                            </p>
                            {cites.map(cite => (
                                <button
                                    key={cite.id}
                                    onClick={() => onCiteClick(cite)}
                                    className="w-full text-left flex items-start gap-2.5
                                               p-3 mb-1 rounded-xl bg-[#141414]/3
                                               hover:bg-[#141414]/7 transition-colors group"
                                >
                                    <div className="flex-1 min-w-0">
                                        <p className="text-[10px] leading-relaxed
                                                      text-[#141414]/60 line-clamp-3
                                                      font-mono">
                                            {cite.preview || '—'}
                                        </p>
                                    </div>
                                    <span className="text-[8px] opacity-0 group-hover:opacity-40
                                                     transition-opacity flex-shrink-0 mt-0.5">
                                        Voir →
                                    </span>
                                </button>
                            ))}
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}

/* ══════════════════════════════════════════════════════════════════
   MESSAGE
   ══════════════════════════════════════════════════════════════════ */
function Message({ message }) {
    const isUser    = message.role === 'user';
    const citations = message.citations || [];
    const [activeCite, setActiveCite] = useState(null);

    const mdComponents = {
        table: ({ node, children, ...props }) => {
            const headers = [], bodyRows = [];
            if (node?.children) {
                const thead = node.children.find(n => n.tagName === 'thead');
                const tbody = node.children.find(n => n.tagName === 'tbody');
                thead?.children?.find(n => n.tagName === 'tr')
                    ?.children?.filter(n => n.tagName === 'th')
                    ?.forEach(th => headers.push(extractHastText(th.children)));
                tbody?.children?.filter(n => n.tagName === 'tr')?.forEach(tr =>
                    bodyRows.push(
                        (tr.children?.filter(n => n.tagName === 'td') || [])
                            .map(td => extractHastText(td.children))
                    )
                );
            }
            return (
                <div className="table-responsive">
                    <table {...props} className="chat-table-desktop">{children}</table>
                    <div className="chat-table-mobile">
                        {bodyRows.map((row, i) => (
                            <div key={i} className="mobile-patient-card">
                                {row.map((cell, j) => cell && (
                                    <div key={j} className={`mobile-card-cell${j===0?' mobile-card-header':''}`}>
                                        {j>0 && headers[j] && <span className="mobile-cell-label">{headers[j]}</span>}
                                        <span className="mobile-cell-value">{cell}</span>
                                    </div>
                                ))}
                            </div>
                        ))}
                    </div>
                </div>
            );
        },
    };

    return (
        <>
            {activeCite && <SourceModal cite={activeCite} onClose={() => setActiveCite(null)} />}

            <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-5`}>
                {!isUser && (
                    <div className="bg-[#141414] p-1.5 rounded-lg text-white
                                    flex-shrink-0 h-fit mt-0.5 mr-3">
                        <ShieldCheck size={14} />
                    </div>
                )}

                <div className={`${isUser ? 'max-w-[70%]' : 'max-w-[82%]'}`}>
                    {isUser ? (
                        <div className="bg-[#141414] text-white p-4 rounded-2xl
                                        rounded-tr-sm shadow-lg">
                            <p className="text-sm leading-relaxed">{message.content}</p>
                            {message.detectedPatient && (
                                <p className="text-[9px] opacity-50 mt-1.5">
                                    Dossier : {message.detectedPatient}
                                </p>
                            )}
                        </div>
                    ) : (
                        <div className="bg-white border border-[#141414]/10 p-5
                                        rounded-2xl rounded-tl-sm shadow-sm">
                            {/* En-tête réponse */}
                            <div className="flex items-center gap-2 mb-4">
                                <span className="text-[9px] font-bold uppercase
                                                 tracking-widest opacity-35">
                                    Assistant Médical
                                </span>
                                {message.llmMode && (
                                    <span className={`text-[8px] font-bold px-2 py-0.5
                                                      rounded-full uppercase
                                        ${message.llmMode === 'gemini'  ? 'bg-blue-50 text-blue-500'    :
                                          message.llmMode === 'mistral' ? 'bg-orange-50 text-orange-500' :
                                                                           'bg-gray-100 text-gray-500'}`}>
                                        {message.llmMode}
                                    </span>
                                )}
                                {message.responseTime != null && (
                                    <span className={`ml-auto text-[9px] font-mono font-bold
                                                      px-2 py-0.5 rounded-full
                                        ${message.responseTime < 5000  ? 'bg-emerald-50 text-emerald-600' :
                                          message.responseTime < 30000 ? 'bg-amber-50 text-amber-600'    :
                                                                          'bg-red-50 text-red-500'}`}>
                                        ⏱ {message.responseTime < 1000
                                            ? `${message.responseTime}ms`
                                            : `${(message.responseTime/1000).toFixed(1)}s`}
                                    </span>
                                )}
                            </div>

                            {/* ▲ SOURCES EN HAUT — boutons sections cliquables */}
                            <SourcesHeader
                                citations={citations}
                                sources={message.sources}
                                onCiteClick={setActiveCite}
                            />

                            {/* Texte propre sans marqueurs */}
                            <div className="chat-markdown">
                                <ReactMarkdown
                                    remarkPlugins={[remarkGfm]}
                                    components={mdComponents}
                                >
                                    {cleanText(message.content)}
                                </ReactMarkdown>
                            </div>

                            {/* ▼ EXTRAITS DÉPLIABLES EN BAS */}
                            <SourcesList
                                citations={citations}
                                onCiteClick={setActiveCite}
                            />
                        </div>
                    )}
                </div>
            </div>
        </>
    );
}

/* ══════════════════════════════════════════════════════════════════
   LISTE MESSAGES
   ══════════════════════════════════════════════════════════════════ */
export default function ChatMessages({ messages, loading, messagesEndRef }) {
    return (
        <div className="flex-1 overflow-y-auto p-6 bg-[#F8F8F6]">
            {messages.length === 0 && !loading && (
                <div className="h-full flex flex-col items-center justify-center
                                opacity-10 space-y-4">
                    <ShieldCheck size={64} />
                    <div className="text-center">
                        <p className="text-base font-serif italic font-bold">
                            Secure RAG Terminal Ready
                        </p>
                        <p className="text-[10px] font-mono uppercase tracking-[0.4em] mt-1.5">
                            Sélectionnez un patient et posez votre question
                        </p>
                    </div>
                </div>
            )}

            {messages.map((msg, i) => (
                <Message key={msg.id ?? i} message={msg} />
            ))}

            {loading && (
                <div className="flex justify-start mb-5">
                    <div className="bg-[#141414] p-1.5 rounded-lg text-white
                                    flex-shrink-0 h-fit mt-0.5 mr-3">
                        <ShieldCheck size={14} />
                    </div>
                    <div className="bg-white border border-[#141414]/10 p-4
                                    rounded-2xl rounded-tl-sm shadow-sm">
                        <div className="flex gap-1.5 items-center h-5">
                            <span className="loading-dot" />
                            <span className="loading-dot" />
                            <span className="loading-dot" />
                        </div>
                    </div>
                </div>
            )}
            <div ref={messagesEndRef} />
        </div>
    );
}
