/**
 * ProtectedRoute.jsx — Garde de navigation pour les routes privées
 * ══════════════════════════════════════════════════════════════════
 *
 * RÔLE
 * ─────
 * Composant wrapper qui empêche un utilisateur NON connecté
 * d'accéder aux pages protégées (Dashboard, RAG Terminal, etc.).
 *
 * COMMENT ÇA MARCHE ?
 * ────────────────────
 * Si l'utilisateur N'EST PAS connecté → redirige vers /login
 * Si l'utilisateur EST connecté        → affiche la page demandée
 *
 * Il est utilisé dans router.jsx pour envelopper chaque route protégée :
 *
 *   <Route path="/dashboard" element={
 *     <ProtectedRoute>
 *       <Dashboard />
 *     </ProtectedRoute>
 *   } />
 *
 * ÉTAT "LOADING"
 * ───────────────
 * Au premier chargement, AuthContext vérifie localStorage pour
 * restaurer la session. Pendant ce court instant, `loading=true`
 * et on affiche un écran vide pour éviter un flash de /login.
 */
import { Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

/**
 * @param {Object}           props
 * @param {React.ReactNode}  props.children - La page à afficher si connecté
 */
const ProtectedRoute = ({ children }) => {
    const { user, loading } = useAuth();

    // Attendre que AuthContext finisse de lire localStorage
    if (loading) return null;

    // Non connecté → redirection transparente vers /login
    if (!user) {
        return <Navigate to="/login" replace />;
    }

    return children;
};

export default ProtectedRoute;
