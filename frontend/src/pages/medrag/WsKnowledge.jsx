import WorkshopPage from '../../components/WorkshopPage';

export default function WsKnowledge() {
    return (
        <WorkshopPage
            title="Base de connaissances"
            realPath="/knowledge"
            objective="Gérer les dossiers patients : upload de PDFs, liste des documents, visualisation et suppression."
            elements={[
                'Zone de drag & drop pour upload',
                'Liste des patients avec barre de recherche',
                'Visionneur PDF ou sections par catégorie',
                'Bouton de suppression de document',
            ]}
            starterCode={`import { useQuery } from '@tanstack/react-query';
import api from '@/api/client';

export default function KnowledgeBase() {
    // TODO: Charger la liste des patients
    const { data: patients } = useQuery({
        queryKey: ['patients'],
        queryFn: () => api.get('/api/v1/patients').then(r => r.data),
    });

    return (
        <div className="p-6">
            <h1 className="text-2xl font-bold mb-6">Base de connaissances</h1>
            {/* TODO: Upload + liste patients */}
        </div>
    );
}`}
            tailwindHints={['border-2 border-dashed', 'rounded-2xl p-8', 'hover:border-blue-400']}
            apiEndpoints={[
                { method: 'GET', path: '/api/v1/patients', desc: 'Liste patients' },
                { method: 'POST', path: '/api/v1/documents/upload', desc: 'Upload PDF' },
                { method: 'DELETE', path: '/api/v1/documents/{id}', desc: 'Supprimer' },
            ]}
            reactHooks={['useQuery', 'useMutation', 'useState']}
        />
    );
}
