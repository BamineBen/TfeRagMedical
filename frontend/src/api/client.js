/**
 * client.js : Instance Axios partagée + parseApiError (DRY).
 * Injecte automatiquement le JWT dans chaque requête.
 * Auto-refresh du token sur réponse 401.
 */
import axios from 'axios';

const api = axios.create({
    baseURL: '/api/v1',
    headers: { 'Content-Type': 'application/json' },
    timeout: 150000,
});

// Injecte le JWT avant chaque requête
api.interceptors.request.use(
    (config) => {
        const token = localStorage.getItem('access_token');
        if (token) config.headers.Authorization = `Bearer ${token}`;
        return config;
    },
    (error) => Promise.reject(error)
);

// Auto-refresh JWT sur 401
let _isRefreshing = false;
let _refreshSubscribers = [];
function _subscribeTokenRefresh(cb) { _refreshSubscribers.push(cb); }
function _onRefreshSuccess(newToken) {
    _refreshSubscribers.forEach(cb => cb(newToken));
    _refreshSubscribers = [];
}

api.interceptors.response.use(
    (response) => response,
    async (error) => {
        const originalRequest = error.config;
        if (!error.response || error.response.status !== 401) return Promise.reject(error);
        if (window.location.pathname.startsWith('/login')) return Promise.reject(error);
        if (originalRequest._isRetry || originalRequest.url?.includes('/auth/refresh')) {
            _isRefreshing = false; _refreshSubscribers = [];
            localStorage.clear(); window.location.href = '/login';
            return Promise.reject(error);
        }
        if (_isRefreshing) {
            return new Promise((resolve, reject) => {
                _subscribeTokenRefresh((newToken) => {
                    if (!newToken) return reject(error);
                    originalRequest.headers.Authorization = `Bearer ${newToken}`;
                    resolve(api(originalRequest));
                });
            });
        }
        _isRefreshing = true; originalRequest._isRetry = true;
        try {
            const refreshToken = localStorage.getItem('refresh_token');
            if (!refreshToken) throw new Error('Pas de refresh token');
            const { data } = await api.post('/auth/refresh', { refresh_token: refreshToken });
            localStorage.setItem('access_token', data.access_token);
            if (data.refresh_token) localStorage.setItem('refresh_token', data.refresh_token);
            api.defaults.headers.common.Authorization = `Bearer ${data.access_token}`;
            _onRefreshSuccess(data.access_token);
            originalRequest.headers.Authorization = `Bearer ${data.access_token}`;
            return api(originalRequest);
        } catch {
            _refreshSubscribers.forEach(cb => cb(null)); _refreshSubscribers = [];
            localStorage.clear(); window.location.href = '/login';
            return Promise.reject(error);
        } finally { _isRefreshing = false; }
    }
);

// parseApiError : (DRY) (utilisé par Login, UserManagement, etc.) 
// FastAPI peut retourner detail comme : string | [{type,loc,msg,...}] | objet
const PYDANTIC_MESSAGES_FR = {
    'String should have at least': 'Le champ est trop court',
    'String should have at most':  'Le champ est trop long',
    'field required':              'Ce champ est obligatoire',
    'value is not a valid email':  'Adresse e-mail invalide',
    'none is not an allowed value':'Ce champ ne peut pas être vide',
};
export function parseApiError(error, fallback = 'Une erreur est survenue') {
    const raw = error?.response?.data?.detail;
    if (typeof raw === 'string') return raw;
    if (Array.isArray(raw) && raw.length > 0) {
        const firstMsg = raw[0]?.msg ?? String(raw[0]);
        const translated = Object.entries(PYDANTIC_MESSAGES_FR).find(([key]) => firstMsg.includes(key));
        return translated ? translated[1] : 'Identifiants invalides';
    }
    if (raw) return fallback;
    if (!error?.response) return 'Impossible de contacter le serveur';
    return fallback;
}

export default api;