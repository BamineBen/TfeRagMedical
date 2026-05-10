/**
 * MedragProtectedRoute.jsx — Garde-porte du Sandbox
 *
 * Vérifie si le token "medrag_token" est présent dans localStorage.
 * Si non → redirige vers /medrag/login
 * Si oui → affiche le contenu protégé
 *
 * Différent de ProtectedRoute (qui utilise "access_token" pour l'app principale).
 */
import { Navigate } from 'react-router-dom';

export default function MedragProtectedRoute({ children }) {
    const token = localStorage.getItem('medrag_token');
    if (!token) {
        return <Navigate to="/medrag/login" replace />;
    }
    return children;
}
