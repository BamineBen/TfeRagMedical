/**
 * SuggestionsPanel.jsx — Panel de questions médicales suggérées
 * ══════════════════════════════════════════════════════════════
 *
 * RÔLE
 * ─────
 * Affiche des questions médicales pré-définies classées par catégorie
 * (Identité, Antécédents, Consultations, Traitements, Biologie, etc.)
 * pour aider le médecin à interroger rapidement un dossier patient.
 *
 * FONCTIONNEMENT
 * ───────────────
 *   - Le médecin sélectionne un patient dans PatientSidebar
 *   - SuggestionsPanel affiche les questions avec {name} remplacé par
 *     le vrai nom du patient
 *   - Un clic → la question est injectée dans le champ de saisie
 *
 * PROPS
 * ──────
 *   patientName : string — nom du patient sélectionné (ex: "Sophie LECOMTE")
 *   onSelect    : function(question: string) — callback quand une suggestion est cliquée
 */
import { useState } from 'react';
import { Users } from 'lucide-react';

const CATEGORIES_FR = [
    {
        label: 'Identité',
        prompts: [
            "Quelle est l'identité complète de {name} ?",
            "Quel est le groupe sanguin de {name} ?",
            "Qui est le médecin traitant de {name} ?",
            "Quelle est la date de naissance de {name} ?",
        ],
    },
    {
        label: 'Antécédents',
        prompts: [
            "Quels sont les antécédents médicaux de {name} ?",
            "Antécédents chirurgicaux de {name} ?",
            "Antécédents familiaux de {name} ?",
            "Quelles sont les allergies de {name} ?",
            "{name} a-t-il des contre-indications médicamenteuses ?",
        ],
    },
    {
        label: 'Consultations',
        prompts: [
            "Dernière consultation de {name} ?",
            "Quels diagnostics ont été posés pour {name} ?",
            "Pathologies chroniques de {name} ?",
            "Évolution clinique de {name} depuis 6 mois ?",
            "Motifs de consultation de {name} ?",
        ],
    },
    {
        label: 'Traitements',
        prompts: [
            "Quels sont les traitements en cours de {name} ?",
            "Posologies et dosages de {name} ?",
            "Quand a été prescrit le traitement de {name} ?",
            "Y a-t-il des interactions médicamenteuses chez {name} ?",
        ],
    },
    {
        label: 'Biologie',
        prompts: [
            "Résultats du bilan biologique de {name} ?",
            "Glycémie et HbA1c de {name} ?",
            "Bilan lipidique de {name} ?",
            "Bilan rénal de {name} (créatinine, DFG) ?",
            "NFS de {name} — anémie ou anomalie ?",
            "TSH et bilan thyroïdien de {name} ?",
        ],
    },
    {
        label: 'Imagerie',
        prompts: [
            "Résultats ECG de {name} ?",
            "Résultats du scanner de {name} ?",
            "IRM de {name} — conclusions ?",
            "Radiographie thoracique de {name} ?",
            "Échographie de {name} ?",
            "Spirométrie de {name} ?",
        ],
    },
    {
        label: 'Hospitalisations',
        prompts: [
            "Hospitalisations de {name} ?",
            "Motifs et durées d'hospitalisation de {name} ?",
            "Comptes-rendus d'hospitalisation de {name} ?",
        ],
    },
    {
        label: 'Vaccinations',
        prompts: [
            "Vaccinations de {name} ?",
            "Rappels vaccinaux manquants pour {name} ?",
        ],
    },
    {
        label: 'Synthèse',
        prompts: [
            "Synthèse complète du dossier de {name}",
            "Résumé complet du dossier de {name}",
            "Points d'attention et valeurs anormales de {name} ?",
            "Plan de suivi recommandé pour {name} ?",
            "Quoi de nouveau pour {name} depuis la dernière consultation ?",
        ],
    },
    {
        label: 'Groupe',
        isGlobal: true,
        prompts: [
            "Quels patients ont eu une rupture du ligament croisé ?",
            "Patients avec diabète de type 2 — âge, traitements, évolution",
            "Historique des patients hypertendus — traitement utilisé et résultat",
            "Patients ayant eu une fracture — protocole et durée de rééducation",
            "Quels patients sont sous anticoagulants ? Molécule et indication",
            "Patients avec insuffisance rénale — stade, créatinine, traitement",
            "Patients asthmatiques — traitement de fond et crises documentées",
            "Comparaison des patients ayant eu une chirurgie orthopédique",
            "Patients avec fibrillation auriculaire — anticoagulation et suivi",
            "Liste des patients obèses — IMC, comorbidités, prise en charge",
        ],
    },
];

const CATEGORIES_EN = [
    {
        label: 'Identity',
        prompts: [
            "What is the full identity of {name}?",
            "What is the blood type of {name}?",
            "Who is the primary care physician of {name}?",
            "What is the date of birth of {name}?",
        ],
    },
    {
        label: 'History',
        prompts: [
            "What are the medical history entries of {name}?",
            "Surgical history of {name}?",
            "Family medical history of {name}?",
            "What are the allergies of {name}?",
            "Does {name} have any drug contraindications?",
        ],
    },
    {
        label: 'Consultations',
        prompts: [
            "Last consultation of {name}?",
            "What diagnoses have been made for {name}?",
            "Chronic conditions of {name}?",
            "Clinical evolution of {name} over the past 6 months?",
            "Reasons for consultation of {name}?",
        ],
    },
    {
        label: 'Treatments',
        prompts: [
            "What are the current treatments for {name}?",
            "Dosages and regimens for {name}?",
            "When was the treatment of {name} prescribed?",
            "Are there any drug interactions for {name}?",
        ],
    },
    {
        label: 'Biology',
        prompts: [
            "Lab results for {name}?",
            "Blood glucose and HbA1c of {name}?",
            "Lipid panel of {name}?",
            "Renal function of {name} (creatinine, GFR)?",
            "CBC of {name} — anemia or abnormality?",
            "TSH and thyroid panel of {name}?",
        ],
    },
    {
        label: 'Imaging',
        prompts: [
            "ECG results for {name}?",
            "CT scan results for {name}?",
            "MRI of {name} — conclusions?",
            "Chest X-ray of {name}?",
            "Ultrasound of {name}?",
            "Spirometry of {name}?",
        ],
    },
    {
        label: 'Admissions',
        prompts: [
            "Hospital admissions of {name}?",
            "Reasons and lengths of hospital stays for {name}?",
            "Discharge summaries of {name}?",
        ],
    },
    {
        label: 'Vaccines',
        prompts: [
            "Vaccination records of {name}?",
            "Missing vaccine boosters for {name}?",
        ],
    },
    {
        label: 'Summary',
        prompts: [
            "Full medical summary of {name}",
            "Complete patient record summary of {name}",
            "Key findings and abnormal values for {name}?",
            "Recommended follow-up plan for {name}?",
            "What is new for {name} since the last consultation?",
        ],
    },
    {
        label: 'Group',
        isGlobal: true,
        prompts: [
            "Which patients had an ACL tear?",
            "Patients with type 2 diabetes — age, treatments, progression",
            "Hypertensive patients — treatment used and outcome",
            "Patients with a fracture — protocol and rehabilitation duration",
            "Which patients are on anticoagulants? Drug and indication",
            "Patients with renal insufficiency — stage, creatinine, treatment",
            "Asthmatic patients — maintenance therapy and documented exacerbations",
            "Comparison of patients who had orthopedic surgery",
            "Patients with atrial fibrillation — anticoagulation and follow-up",
            "List of obese patients — BMI, comorbidities, management",
        ],
    },
];

const UI = {
    fr: { hint: '⚡ Mode groupe — recherche sur tous les dossiers indexés' },
    en: { hint: '⚡ Group mode — search across all indexed records' },
};

export default function SuggestionsPanel({ patientName, lang = 'fr', onSelect }) {
    const [activeTab, setActiveTab] = useState(null);
    const categories = lang === 'en' ? CATEGORIES_EN : CATEGORIES_FR;
    const fallback = lang === 'en' ? 'the patient' : 'le patient';
    const fill = (text) => text.replace(/\{name\}/g, patientName || fallback);
    const activeCat = activeTab !== null ? categories[activeTab] : null;

    return (
        <div className="border-t border-[#141414]/8 bg-white/70">
            {/* Tabs */}
            <div className="flex gap-1 px-4 pt-2 overflow-x-auto scrollbar-hide">
                {categories.map((cat, i) => (
                    <button
                        key={cat.label}
                        onClick={() => setActiveTab(activeTab === i ? null : i)}
                        className={`flex-shrink-0 text-[10px] font-bold px-3 py-1.5 rounded-lg uppercase tracking-wide transition-all flex items-center gap-1 ${
                            cat.isGlobal
                                ? activeTab === i
                                    ? 'bg-indigo-600 text-white'
                                    : 'text-indigo-600 border border-indigo-200 hover:bg-indigo-50 opacity-80 hover:opacity-100'
                                : activeTab === i
                                    ? 'bg-[#141414] text-white'
                                    : 'hover:bg-[#141414]/8 opacity-55 hover:opacity-100'
                        }`}
                    >
                        {cat.isGlobal && <Users size={10} />}
                        {cat.label}
                    </button>
                ))}
            </div>

            {/* Group hint */}
            {activeCat?.isGlobal && (
                <p className="px-4 pt-1.5 text-[10px] text-indigo-500 font-medium">
                    {UI[lang]?.hint ?? UI.fr.hint}
                </p>
            )}

            {/* Prompts */}
            {activeTab !== null && (
                <div className="flex gap-2 px-4 py-2 overflow-x-auto scrollbar-hide">
                    {categories[activeTab].prompts.map((p, j) => (
                        <button
                            key={j}
                            onClick={() => {
                                const isGlobal = categories[activeTab].isGlobal;
                                onSelect(fill(p), { global: isGlobal });
                                setActiveTab(null);
                            }}
                            className={`flex-shrink-0 text-xs px-3 py-2 rounded-lg transition-all font-medium whitespace-nowrap ${
                                categories[activeTab].isGlobal
                                    ? 'bg-indigo-50 hover:bg-indigo-600 hover:text-white text-indigo-700'
                                    : 'bg-[#141414]/5 hover:bg-[#141414] hover:text-white'
                            }`}
                        >
                            {fill(p)}
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
}
