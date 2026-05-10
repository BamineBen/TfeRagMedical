/**
 * Login.jsx : Page de connexion (publique).
 * Gère le paramètre ? return = pour rediriger après login (ex: depuis Google Calendar).
 */
import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { ShieldCheck, User, Lock, Loader2 } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { parseSafeReturnUrl } from '../lib/safeRedirect';

export default function LoginPage() {
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [error,    setError]    = useState('');
    const [loading,  setLoading]  = useState(false);

    const { login }      = useAuth();
    const navigate       = useNavigate();
    const [searchParams] = useSearchParams();
    const returnUrl      = parseSafeReturnUrl(searchParams.get('return'));

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError(''); setLoading(true);
        const result = await login(username, password);
        if (result.success) {
            navigate(returnUrl, { replace: true });
            return;
        }
        setError(result.error);
        setLoading(false);
    };

    return (
        <div className="bg-[#F4F4F2] flex items-center justify-center p-4 overflow-y-auto" style={{ minHeight: '100dvh' }}>
            <div className="w-full max-w-sm">
                <div className="bg-white border border-[#141414]/10 rounded-3xl p-6 sm:p-10 shadow-xl">
                    <div className="text-center mb-8">
                        <div className="flex items-center justify-center gap-3 mb-3">
                            <div className="bg-[#141414] p-2.5 rounded-xl text-white"><ShieldCheck size={24}/></div>
                            <h1 className="font-serif italic text-3xl font-bold tracking-tight">RAG.Med</h1>
                        </div>
                        <p className="text-[9px] uppercase tracking-[0.25em] font-bold opacity-35">Enterprise Health v2.0</p>
                        <p className="text-xs opacity-40 mt-3">Connexion sécurisée</p>
                    </div>
                    {error && (
                        <div className="bg-red-50 border border-red-200 text-red-600 px-4 py-3 rounded-xl text-xs mb-5 font-medium">{error}</div>
                    )}
                    <form onSubmit={handleSubmit} className="space-y-4">
                        <div>
                            <label className="block text-[10px] font-bold uppercase tracking-widest opacity-50 mb-2">Identifiant</label>
                            <div className="relative">
                                <User size={15} className="absolute left-3.5 top-1/2 -translate-y-1/2 opacity-35"/>
                                <input type="text" value={username} onChange={e => setUsername(e.target.value)}
                                    placeholder="Nom d'utilisateur" required
                                    className="w-full pl-10 pr-4 py-3 border border-[#141414]/10 rounded-xl text-sm outline-none focus:ring-2 ring-[#141414]/10 transition-all"/>
                            </div>
                        </div>
                        <div>
                            <label className="block text-[10px] font-bold uppercase tracking-widest opacity-50 mb-2">Mot de passe</label>
                            <div className="relative">
                                <Lock size={15} className="absolute left-3.5 top-1/2 -translate-y-1/2 opacity-35"/>
                                <input type="password" value={password} onChange={e => setPassword(e.target.value)}
                                    placeholder="••••••••" required
                                    className="w-full pl-10 pr-4 py-3 border border-[#141414]/10 rounded-xl text-sm outline-none focus:ring-2 ring-[#141414]/10 transition-all"/>
                            </div>
                        </div>
                        <button type="submit" disabled={loading}
                            className="w-full bg-[#141414] text-white py-3.5 rounded-xl font-bold text-xs uppercase tracking-widest hover:bg-[#141414]/85 transition-all disabled:opacity-50 flex items-center justify-center gap-2 mt-2 shadow-lg">
                            {loading ? <><Loader2 size={16} className="animate-spin"/> Connexion...</> : 'Se connecter'}
                        </button>
                    </form>
                </div>
                <p className="text-center text-[10px] opacity-30 mt-6 uppercase tracking-widest">Accès restreint — Personnel autorisé uniquement</p>
            </div>
        </div>
    );
}