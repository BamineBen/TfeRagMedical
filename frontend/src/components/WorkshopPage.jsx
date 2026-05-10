/**
 * WorkshopPage.jsx — Composant réutilisable pour chaque atelier
 *
 * Chaque page du sandbox utilise ce composant pour afficher :
 *   1. L'objectif de la page à construire
 *   2. La liste des éléments à créer
 *   3. Le code de départ (starter template)
 *   4. Les ressources utiles (classes Tailwind, endpoints API)
 *
 * Utilisation :
 *   <WorkshopPage
 *     title="Tableau de bord"
 *     objective="Afficher les statistiques de l'application"
 *     elements={['Carte statistiques', 'Graphique', 'Liste patients']}
 *     starterCode={`export default function Dashboard() { ... }`}
 *     resources={{ tailwind: ['...'], api: ['...'] }}
 *   />
 */
import { useState } from 'react';
import {
    Target, Code2, Lightbulb, ChevronDown, ChevronRight,
    CheckCircle2, ExternalLink, Copy, Check,
} from 'lucide-react';

/** Copie du texte dans le presse-papier */
function CopyButton({ text }) {
    const [copied, setCopied] = useState(false);
    const copy = () => {
        navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
    };
    return (
        <button
            onClick={copy}
            className="flex items-center gap-1.5 text-[10px] font-bold uppercase
                       tracking-wider px-2.5 py-1 rounded-lg transition-colors
                       bg-white/10 hover:bg-white/20 text-white/70"
        >
            {copied ? <Check size={11} /> : <Copy size={11} />}
            {copied ? 'Copié !' : 'Copier'}
        </button>
    );
}

/** Section dépliable */
function Section({ icon: Icon, title, color, defaultOpen = false, children }) {
    const [open, setOpen] = useState(defaultOpen);
    return (
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
            <button
                onClick={() => setOpen(v => !v)}
                className="w-full flex items-center gap-3 px-5 py-4 hover:bg-gray-50 transition-colors"
            >
                <div className="w-8 h-8 rounded-xl flex items-center justify-center flex-shrink-0"
                     style={{ backgroundColor: color + '20' }}>
                    <Icon size={16} style={{ color }} />
                </div>
                <span className="font-bold text-sm text-[#141414] flex-1 text-left">{title}</span>
                {open ? <ChevronDown size={16} className="text-gray-400" /> : <ChevronRight size={16} className="text-gray-400" />}
            </button>
            {open && <div className="border-t border-gray-100">{children}</div>}
        </div>
    );
}

export default function WorkshopPage({
    title,           // Nom de la page à construire
    realPath,        // Lien vers la vraie page dans l'app (ex: /dashboard)
    objective,       // Description de ce que la page fait
    elements,        // Liste des éléments UI à créer
    starterCode,     // Code de départ avec TODOs
    tailwindHints,   // Classes Tailwind utiles
    apiEndpoints,    // Endpoints API à utiliser
    reactHooks,      // Hooks React à utiliser
}) {
    return (
        <div className="max-w-4xl mx-auto px-4 py-6 space-y-4">

            {/* En-tête de l'atelier */}
            <div className="bg-gradient-to-r from-violet-600 to-violet-700
                            rounded-2xl p-6 text-white shadow-lg">
                <div className="flex items-start justify-between gap-4">
                    <div>
                        <p className="text-[10px] font-bold uppercase tracking-widest
                                      text-violet-200 mb-1">
                            Atelier · À reconstruire
                        </p>
                        <h1 className="text-2xl font-serif italic font-bold mb-2">{title}</h1>
                        <p className="text-sm text-violet-100 leading-relaxed">{objective}</p>
                    </div>
                    {realPath && (
                        <a
                            href={realPath}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="flex-shrink-0 flex items-center gap-1.5 bg-white/15
                                       hover:bg-white/25 px-3 py-2 rounded-xl text-xs
                                       font-bold transition-colors whitespace-nowrap"
                        >
                            <ExternalLink size={12} />
                            Voir l'original
                        </a>
                    )}
                </div>
            </div>

            {/* Section 1 : Ce que tu dois construire */}
            <Section icon={Target} title="Ce que tu dois construire" color="#7c3aed" defaultOpen>
                <div className="p-5">
                    <p className="text-xs font-bold uppercase tracking-wider text-gray-400 mb-3">
                        Éléments à créer
                    </p>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        {elements.map((el, i) => (
                            <div key={i}
                                 className="flex items-start gap-2 bg-violet-50 rounded-xl p-3">
                                <div className="w-5 h-5 rounded-full bg-violet-200 flex items-center
                                                justify-center flex-shrink-0 mt-0.5">
                                    <span className="text-[10px] font-black text-violet-700">
                                        {i + 1}
                                    </span>
                                </div>
                                <span className="text-sm text-violet-900 font-medium">{el}</span>
                            </div>
                        ))}
                    </div>
                </div>
            </Section>

            {/* Section 2 : Code de départ */}
            <Section icon={Code2} title="Code de départ — remplis les TODO" color="#0284c7" defaultOpen>
                <div className="relative">
                    <div className="flex items-center justify-between px-4 py-2
                                    bg-[#1e1e2e] border-b border-white/10">
                        <span className="text-[10px] font-mono text-white/50">
                            src/pages/{title.replace(/\s/g, '')}.jsx
                        </span>
                        <CopyButton text={starterCode} />
                    </div>
                    <pre className="bg-[#1e1e2e] p-5 overflow-x-auto text-sm
                                    font-mono text-green-300 leading-relaxed">
                        <code>{starterCode}</code>
                    </pre>
                </div>
            </Section>

            {/* Section 3 : Ressources & Hints */}
            <Section icon={Lightbulb} title="Ressources & Astuces" color="#059669">
                <div className="p-5 space-y-4">
                    {/* Classes Tailwind */}
                    {tailwindHints?.length > 0 && (
                        <div>
                            <p className="text-xs font-bold uppercase tracking-wider
                                          text-gray-400 mb-2">
                                Classes Tailwind utiles
                            </p>
                            <div className="flex flex-wrap gap-2">
                                {tailwindHints.map((cls, i) => (
                                    <code key={i}
                                          className="bg-sky-50 border border-sky-200 text-sky-800
                                                     px-2.5 py-1 rounded-lg text-[11px] font-mono">
                                        {cls}
                                    </code>
                                ))}
                            </div>
                        </div>
                    )}

                    {/* Hooks React */}
                    {reactHooks?.length > 0 && (
                        <div>
                            <p className="text-xs font-bold uppercase tracking-wider
                                          text-gray-400 mb-2">
                                Hooks React à utiliser
                            </p>
                            <div className="flex flex-wrap gap-2">
                                {reactHooks.map((hook, i) => (
                                    <code key={i}
                                          className="bg-violet-50 border border-violet-200
                                                     text-violet-800 px-2.5 py-1 rounded-lg
                                                     text-[11px] font-mono">
                                        {hook}
                                    </code>
                                ))}
                            </div>
                        </div>
                    )}

                    {/* Endpoints API */}
                    {apiEndpoints?.length > 0 && (
                        <div>
                            <p className="text-xs font-bold uppercase tracking-wider
                                          text-gray-400 mb-2">
                                Endpoints API à appeler
                            </p>
                            <div className="space-y-1.5">
                                {apiEndpoints.map(({ method, path, desc }, i) => (
                                    <div key={i}
                                         className="flex items-center gap-3 bg-gray-50
                                                    rounded-xl px-3 py-2">
                                        <span className={`text-[10px] font-black px-2 py-0.5
                                            rounded-md flex-shrink-0 ${
                                            method === 'GET'    ? 'bg-emerald-100 text-emerald-700' :
                                            method === 'POST'   ? 'bg-sky-100 text-sky-700' :
                                            method === 'DELETE' ? 'bg-rose-100 text-rose-700' :
                                            'bg-amber-100 text-amber-700'
                                        }`}>
                                            {method}
                                        </span>
                                        <code className="text-[11px] font-mono text-gray-600 flex-1">
                                            {path}
                                        </code>
                                        <span className="text-[11px] text-gray-400 hidden sm:inline">
                                            {desc}
                                        </span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            </Section>

            {/* Pied de page */}
            <div className="text-center py-2">
                <p className="text-[11px] text-gray-400">
                    💡 Consulte <code className="font-mono bg-gray-100 px-1 rounded">
                        GUIDE_RECREATION_COMPLETE.md
                    </code> pour plus de détails.
                </p>
            </div>
        </div>
    );
}
