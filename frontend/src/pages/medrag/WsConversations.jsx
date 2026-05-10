import WorkshopPage from '../../components/WorkshopPage';

export default function WsConversations() {
    return (
        <WorkshopPage
            title="Historique des conversations"
            realPath="/conversations"
            objective="Afficher et gérer l'historique des sessions de chat RAG avec leurs messages."
            elements={[
                'Liste paginée des conversations',
                'Filtres par statut et canal',
                'Vue détail avec messages',
                'Suppression individuelle et en lot',
            ]}
            starterCode={`import { useQuery } from '@tanstack/react-query';
import api from '@/api/client';

export default function Conversations() {
    const { data } = useQuery({
        queryKey: ['conversations'],
        queryFn: () => api.get('/api/v1/conversations').then(r => r.data),
    });

    return (
        <div className="p-6">
            <h1 className="text-2xl font-bold mb-6">Historique</h1>
            {/* TODO: Liste des conversations */}
        </div>
    );
}`}
            tailwindHints={['divide-y divide-gray-100', 'hover:bg-gray-50', 'truncate']}
            apiEndpoints={[
                { method: 'GET', path: '/api/v1/conversations', desc: 'Liste paginée' },
                { method: 'GET', path: '/api/v1/conversations/{id}', desc: 'Détail + messages' },
                { method: 'DELETE', path: '/api/v1/conversations/{id}', desc: 'Supprimer' },
            ]}
            reactHooks={['useQuery', 'useMutation', 'useState']}
        />
    );
}
