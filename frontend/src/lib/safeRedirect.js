/**
 * safeRedirect.js : Redirection sécurisée (anti open-redirect CWE-601).
 * (DRY) : utilisé par Login.jsx
 */
export const DEFAULT_RETURN_URL = '/dashboard';

export function parseSafeReturnUrl(rawReturn, fallback = DEFAULT_RETURN_URL) {
    if (!rawReturn) return fallback;
    try {
        const decoded = decodeURIComponent(rawReturn);
        const url = new URL(decoded, window.location.origin);
        if (url.origin !== window.location.origin) return fallback;
        return url.pathname + url.search;
    } catch {
        return fallback;
    }
}