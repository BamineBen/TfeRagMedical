import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

export default function MedragLogin() {
    const [token, setToken] = useState('');
    const navigate = useNavigate();

    const handleSubmit = (e) => {
        e.preventDefault();
        if (token.trim()) {
            localStorage.setItem('medrag_token', token.trim());
            navigate('/medrag/dashboard');
        }
    };

    return (
        <div className="flex items-center justify-center min-h-screen bg-violet-50">
            <div className="bg-white rounded-2xl shadow-lg p-8 w-full max-w-sm">
                <h1 className="text-2xl font-bold text-violet-700 mb-2">Sandbox MedRAG</h1>
                <p className="text-sm text-gray-500 mb-6">Entrez votre token d'accès sandbox.</p>
                <form onSubmit={handleSubmit} className="space-y-4">
                    <input
                        type="password"
                        value={token}
                        onChange={e => setToken(e.target.value)}
                        placeholder="Token sandbox"
                        className="w-full border rounded-xl px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-violet-400"
                    />
                    <button
                        type="submit"
                        className="w-full bg-violet-600 text-white rounded-xl py-3 font-semibold hover:bg-violet-700 transition-colors"
                    >
                        Accéder au sandbox
                    </button>
                </form>
            </div>
        </div>
    );
}
