import WorkshopPage from '../../components/WorkshopPage';

export default function WsUsers() {
    return (
        <WorkshopPage
            title="Gestion des utilisateurs"
            realPath="/admin/users"
            objective="Interface d'administration CRUD pour gérer les médecins et admins de la plateforme."
            elements={[
                'Tableau des utilisateurs',
                'Formulaire de création',
                'Modification de rôle et statut',
                'Suppression avec confirmation',
            ]}
            starterCode={`import { useQuery } from '@tanstack/react-query';
import api from '@/api/client';

export default function UserManagement() {
    const { data } = useQuery({
        queryKey: ['users'],
        queryFn: () => api.get('/api/v1/users').then(r => r.data),
    });

    return (
        <div className="p-6">
            <h1 className="text-2xl font-bold mb-6">Utilisateurs</h1>
            {/* TODO: Tableau CRUD */}
        </div>
    );
}`}
            tailwindHints={['table-auto w-full', 'text-left text-sm', 'bg-green-100 text-green-700']}
            apiEndpoints={[
                { method: 'GET', path: '/api/v1/users', desc: 'Liste utilisateurs' },
                { method: 'POST', path: '/api/v1/users', desc: 'Créer utilisateur' },
                { method: 'DELETE', path: '/api/v1/users/{id}', desc: 'Supprimer' },
            ]}
            reactHooks={['useQuery', 'useMutation', 'useState']}
        />
    );
}
