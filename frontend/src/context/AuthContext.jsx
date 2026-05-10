/**
 * AuthContext.jsx : État d'authentification global (React Context).
 * Fournit { user, login, logout } à toute l'application.
 */
import { createContext, useContext, useState, useEffect } from 'react';
import api, { parseApiError } from '../api/client';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
    const [user, setUser]       = useState(null);
    const [loading, setLoading] = useState(true);

    // Restaure la session depuis localStorage
    useEffect(() => {
        const token     = localStorage.getItem('access_token');
        const savedUser = localStorage.getItem('user');
        if (token && savedUser) {
            try { setUser(JSON.parse(savedUser)); } catch { localStorage.removeItem('user'); }
        }
        setLoading(false);
    }, []);

    const login = async (username, password) => {
        try {
            const { data: tokens } = await api.post('/auth/login', { username, password });
            localStorage.setItem('access_token',  tokens.access_token);
            localStorage.setItem('refresh_token', tokens.refresh_token);
            const { data: userData } = await api.get('/auth/me');
            localStorage.setItem('user', JSON.stringify(userData));
            setUser(userData);
            return { success: true };
        } catch (error) {
            return { success: false, error: parseApiError(error, 'Erreur de connexion') };
        }
    };

    const logout = async () => {
        try { await api.post('/auth/logout'); } catch { /* réseau coupé → on continue */ }
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        localStorage.removeItem('user');
        setUser(null);
        window.location.href = '/login';
    };

    return (
        <AuthContext.Provider value={{ user, login, logout, loading }}>
            {!loading && children}
        </AuthContext.Provider>
    );
};

export const useAuth = () => {
    const ctx = useContext(AuthContext);
    if (!ctx) throw new Error('useAuth doit être dans un <AuthProvider>');
    return ctx;
};