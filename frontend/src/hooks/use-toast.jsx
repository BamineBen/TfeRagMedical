import { createContext, useContext, useState, useCallback } from 'react';

const ToastContext = createContext(null);

export function ToastProvider({ children }) {
    const [toasts, setToasts] = useState([]);
    const toast = useCallback(({ title, description, variant = 'default' }) => {
        const id = Date.now();
        setToasts(prev => [...prev, { id, title, description, variant }]);
        setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 4000);
    }, []);
    return (
        <ToastContext.Provider value={{ toast }}>
            {children}
            <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
                {toasts.map(t => (
                    <div key={t.id} className={`px-4 py-3 rounded-xl shadow-lg text-sm font-medium max-w-xs
                        ${t.variant === 'destructive' ? 'bg-red-600 text-white' : 'bg-[#141414] text-white'}`}>
                        {t.title && <p className="font-bold">{t.title}</p>}
                        {t.description && <p className="opacity-80 text-xs mt-0.5">{t.description}</p>}
                    </div>
                ))}
            </div>
        </ToastContext.Provider>
    );
}

export function useToast() {
    const ctx = useContext(ToastContext);
    if (!ctx) throw new Error('useToast doit être dans un <ToastProvider>');
    return ctx;
}