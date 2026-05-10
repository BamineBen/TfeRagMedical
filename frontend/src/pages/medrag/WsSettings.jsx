import WorkshopPage from '../../components/WorkshopPage';

export default function WsSettings() {
    return (
        <WorkshopPage
            title="Configuration système"
            realPath="/settings"
            objective="Gérer les paramètres LLM, les clés API cloud et les toggles d'activation des services."
            elements={[
                'Toggles Groq / Gemini / Mistral',
                'Affichage de la RAM et CPU en temps réel',
                'Indicateurs d\'état des services',
                'Formulaire de sauvegarde',
            ]}
            starterCode={`import { useQuery, useMutation } from '@tanstack/react-query';
import api from '@/api/client';

export default function SystemConfig() {
    const { data: config } = useQuery({
        queryKey: ['settings'],
        queryFn: () => api.get('/api/v1/admin/settings').then(r => r.data),
    });

    return (
        <div className="p-6 max-w-2xl mx-auto">
            <h1 className="text-2xl font-bold mb-6">Configuration</h1>
            {/* TODO: Toggles et paramètres */}
        </div>
    );
}`}
            tailwindHints={['flex items-center justify-between', 'rounded-full w-12 h-6', 'bg-blue-500']}
            apiEndpoints={[
                { method: 'GET', path: '/api/v1/admin/settings', desc: 'Récupérer config' },
                { method: 'PUT', path: '/api/v1/admin/settings', desc: 'Sauvegarder config' },
                { method: 'GET', path: '/api/v1/dashboard/metrics', desc: 'RAM / CPU' },
            ]}
            reactHooks={['useQuery', 'useMutation', 'useState']}
        />
    );
}
