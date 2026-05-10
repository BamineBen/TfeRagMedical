import WorkshopPage from '../../components/WorkshopPage';

export default function WsNotes() {
    return (
        <WorkshopPage
            title="Notes atomiques"
            realPath="/notes"
            objective="Éditeur de notes médicales avec auto-save, toolbar (Gras, Italique, SOAP) et indexation instantanée dans FAISS."
            elements={[
                'Sélecteur de patient',
                'Éditeur texte riche avec toolbar',
                'Auto-save avec debounce 2s',
                'Liste des notes existantes',
            ]}
            starterCode={`import { useState, useCallback } from 'react';
import api from '@/api/client';

export default function NoteAtomique() {
    const [content, setContent] = useState('');
    const [patientName, setPatientName] = useState('');

    // TODO: Auto-save avec debounce
    // TODO: POST /api/v1/notes

    return (
        <div className="p-6 max-w-4xl mx-auto">
            <h1 className="text-2xl font-bold mb-6">Notes atomiques</h1>
            {/* TODO: Toolbar + éditeur */}
        </div>
    );
}`}
            tailwindHints={['font-mono text-sm', 'min-h-[300px]', 'focus:outline-none']}
            apiEndpoints={[
                { method: 'POST', path: '/api/v1/notes', desc: 'Créer une note' },
                { method: 'PUT', path: '/api/v1/notes/{id}', desc: 'Modifier une note' },
                { method: 'GET', path: '/api/v1/notes', desc: 'Liste des notes' },
            ]}
            reactHooks={['useState', 'useCallback', 'useRef']}
        />
    );
}
