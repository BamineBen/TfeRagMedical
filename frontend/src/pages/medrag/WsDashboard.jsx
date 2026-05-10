import WorkshopPage from '../../components/WorkshopPage';

export default function WsDashboard() {
    return (
        <WorkshopPage
            title="Tableau de bord"
            realPath="/dashboard"
            objective="Afficher les statistiques clés de la plateforme : nombre de patients, de documents, de conversations et l'état des services."
            elements={[
                'Cartes de statistiques (patients, documents, conversations)',
                'Graphique de conversations par mois',
                'Liste des dossiers récents',
                'État des services (base de données, FAISS, LLM)',
            ]}
            starterCode={`import { useQuery } from '@tanstack/react-query';
import api from '@/api/client';

export default function Dashboard() {
    // TODO: Appeler GET /api/v1/dashboard/stats
    const { data } = useQuery({
        queryKey: ['stats'],
        queryFn: () => api.get('/api/v1/dashboard/stats').then(r => r.data),
    });

    return (
        <div className="p-6">
            <h1 className="text-2xl font-bold mb-6">Tableau de bord</h1>
            {/* TODO: Afficher les statistiques */}
        </div>
    );
}`}
            tailwindHints={['grid grid-cols-4 gap-4', 'rounded-2xl shadow-sm', 'text-3xl font-bold']}
            apiEndpoints={[
                { method: 'GET', path: '/api/v1/dashboard/stats', desc: 'Statistiques globales' },
                { method: 'GET', path: '/api/v1/dashboard/health', desc: 'État des services' },
            ]}
            reactHooks={['useQuery', 'useState']}
        />
    );
}
