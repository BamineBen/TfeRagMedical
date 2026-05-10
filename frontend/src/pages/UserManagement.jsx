/**
 * UserManagement.jsx — Gestion des utilisateurs (admin)
 * ═══════════════════════════════════════════════════════
 *
 * RÔLE
 * ─────
 * Interface CRUD pour gérer les comptes médecins et admins.
 * Accessible uniquement depuis /admin/users (rôle admin requis).
 *
 * FONCTIONNALITÉS
 * ────────────────
 *   • Lister tous les utilisateurs (GET /users)
 *   • Créer un nouveau compte médecin (POST /users)
 *   • Modifier le rôle d'un utilisateur (PUT /users/{id})
 *   • Supprimer un compte (DELETE /users/{id})
 *
 * RÔLES DISPONIBLES
 * ──────────────────
 *   admin  → accès total (config, users, upload, RAG)
 *   doctor → accès RAG + upload + notes (pas de config)
 *   user   → accès RAG en lecture seule
 *
 * SÉCURITÉ
 * ─────────
 * Un admin ne peut pas supprimer son propre compte.
 * La validation des droits est faite côté backend (FastAPI deps).
 */
import { useState, useEffect } from 'react';
import { Check, Edit2, Plus, ShieldCheck, Trash2, User, Users, X } from 'lucide-react';
import api, { parseApiError } from '../api/client'; // parseApiError : DRY — même logique que Login.jsx

const ROLE_LABELS = { admin: 'Administrateur', user: 'Utilisateur', doctor: 'Médecin' };
const ROLE_COLORS = { admin: 'bg-purple-50 text-purple-700', user: 'bg-blue-50 text-blue-700', doctor: 'bg-teal-50 text-teal-700' };

function RoleBadge({ role }) {
    return (
        <span className={`text-[9px] font-bold px-2 py-0.5 rounded-full ${ROLE_COLORS[role] || 'bg-gray-100 text-gray-500'}`}>
            {ROLE_LABELS[role] || role || '—'}
        </span>
    );
}

function Modal({ title, onClose, children }) {
    return (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
            <div className="bg-white rounded-2xl shadow-xl w-full max-w-md">
                <div className="flex items-center justify-between px-6 py-4 border-b border-[#141414]/8">
                    <h2 className="font-serif italic font-bold text-lg">{title}</h2>
                    <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-[#141414]/5 transition-colors">
                        <X size={16} />
                    </button>
                </div>
                <div className="p-6">{children}</div>
            </div>
        </div>
    );
}

export default function UserManagement() {
    const [users, setUsers] = useState([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(true);
    const [showCreate, setShowCreate] = useState(false);
    const [editUser, setEditUser] = useState(null);
    const [form, setForm] = useState({ username: '', email: '', full_name: '', password: '', role: 'user' });
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState('');

    const loadUsers = async () => {
        setLoading(true);
        try {
            const res = await api.get('/users');
            const data = res.data;
            setUsers(data.items || []);
            setTotal(data.total || 0);
        } catch (e) {
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { loadUsers(); }, []);

    const openCreate = () => {
        setForm({ username: '', email: '', full_name: '', password: '', role: 'user' });
        setError('');
        setShowCreate(true);
        setEditUser(null);
    };

    const openEdit = (user) => {
        setForm({ username: user.username, email: user.email, full_name: user.full_name || '', password: '', role: user.role || 'user' });
        setError('');
        setEditUser(user);
        setShowCreate(false);
    };

    const closeModal = () => { setShowCreate(false); setEditUser(null); setError(''); };

    const handleSave = async () => {
        setSaving(true);
        setError('');
        try {
            if (editUser) {
                const payload = { username: form.username, email: form.email, full_name: form.full_name, role: form.role };
                if (form.password) payload.password = form.password;
                await api.put(`/users/${editUser.id}`, payload);
            } else {
                if (!form.password) { setError('Mot de passe requis'); setSaving(false); return; }
                await api.post('/users', form);
            }
            closeModal();
            loadUsers();
        } catch (e) {
            // parseApiError gère les 3 formats FastAPI (string, tableau Pydantic, objet)
            setError(parseApiError(e, 'Erreur lors de la sauvegarde'));
        } finally {
            setSaving(false);
        }
    };

    const handleDelete = async (user) => {
        if (!confirm(`Supprimer l'utilisateur "${user.username}" ?`)) return;
        try {
            await api.delete(`/users/${user.id}`);
            loadUsers();
        } catch (e) {
            alert(e.response?.data?.detail || 'Erreur suppression');
        }
    };

    const modalOpen = showCreate || !!editUser;
    const modalTitle = editUser ? `Modifier — ${editUser.username}` : 'Nouvel utilisateur';

    return (
        <div className="p-4 md:p-8 max-w-5xl mx-auto space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <p className="text-[9px] font-mono uppercase tracking-[0.3em] opacity-30">Administration</p>
                    <p className="text-sm font-semibold opacity-60">
                        {total} utilisateur{total !== 1 ? 's' : ''}
                    </p>
                </div>
                <button
                    onClick={openCreate}
                    className="flex items-center gap-2 px-4 py-2.5 bg-[#141414] text-white text-xs font-bold rounded-xl hover:bg-[#141414]/80 transition-colors"
                >
                    <Plus size={14} /> Créer un utilisateur
                </button>
            </div>

            {/* Table */}
            <div className="bg-white border border-[#141414]/10 rounded-2xl shadow-sm overflow-hidden">
                {/* Header row */}
                <div className="grid grid-cols-[1fr_1fr_auto_auto_auto] gap-4 px-6 py-3 border-b border-[#141414]/5 bg-[#141414]/2">
                    {['Utilisateur', 'Email', 'Rôle', 'Statut', ''].map((h, i) => (
                        <span key={i} className="text-[9px] font-mono uppercase tracking-widest opacity-30">{h}</span>
                    ))}
                </div>

                {loading ? (
                    <div className="flex items-center justify-center py-16 opacity-30">
                        <div className="w-6 h-6 border-2 border-[#141414] border-t-transparent rounded-full animate-spin" />
                    </div>
                ) : users.length === 0 ? (
                    <div className="text-center py-16 opacity-30">
                        <Users size={36} className="mx-auto mb-3" />
                        <p className="text-sm font-semibold">Aucun utilisateur</p>
                    </div>
                ) : users.map((user) => (
                    <div
                        key={user.id}
                        className="grid grid-cols-[1fr_1fr_auto_auto_auto] gap-4 px-6 py-4 border-b border-[#141414]/5 last:border-0 items-center hover:bg-[#141414]/2 transition-colors"
                    >
                        <div className="flex items-center gap-3 min-w-0">
                            <div className="bg-[#141414]/5 p-2 rounded-lg flex-shrink-0">
                                {user.role === 'admin' ? <ShieldCheck size={14} className="opacity-60" /> : <User size={14} className="opacity-60" />}
                            </div>
                            <div className="min-w-0">
                                <p className="text-sm font-bold truncate">{user.full_name || user.username}</p>
                                <p className="text-[10px] font-mono opacity-40 truncate">@{user.username}</p>
                            </div>
                        </div>
                        <p className="text-xs opacity-60 truncate">{user.email}</p>
                        <RoleBadge role={user.role} />
                        <div className="flex items-center gap-1">
                            <div className={`w-1.5 h-1.5 rounded-full ${user.is_active ? 'bg-emerald-500' : 'bg-gray-300'}`} />
                            <span className="text-[9px] opacity-40">{user.is_active ? 'Actif' : 'Inactif'}</span>
                        </div>
                        <div className="flex items-center gap-1">
                            <button
                                onClick={() => openEdit(user)}
                                className="p-1.5 rounded-lg hover:bg-[#141414]/5 opacity-40 hover:opacity-100 transition-all"
                            >
                                <Edit2 size={13} />
                            </button>
                            <button
                                onClick={() => handleDelete(user)}
                                className="p-1.5 rounded-lg hover:bg-red-50 hover:text-red-500 opacity-30 hover:opacity-100 transition-all"
                            >
                                <Trash2 size={13} />
                            </button>
                        </div>
                    </div>
                ))}
            </div>

            {/* Create / Edit modal */}
            {modalOpen && (
                <Modal title={modalTitle} onClose={closeModal}>
                    <div className="space-y-4">
                        {[
                            { label: 'Nom complet', key: 'full_name', type: 'text', placeholder: 'Dr. Jean Dupont' },
                            { label: "Nom d'utilisateur", key: 'username', type: 'text', placeholder: 'j.dupont' },
                            { label: 'Email', key: 'email', type: 'email', placeholder: 'j.dupont@hopital.fr' },
                            { label: `Mot de passe${editUser ? ' (laisser vide = inchangé)' : ''}`, key: 'password', type: 'password', placeholder: '••••••••' },
                        ].map(({ label, key, type, placeholder }) => (
                            <div key={key}>
                                <label className="block text-[10px] font-mono uppercase tracking-widest opacity-50 mb-1.5">{label}</label>
                                <input
                                    type={type}
                                    value={form[key]}
                                    onChange={e => setForm(prev => ({ ...prev, [key]: e.target.value }))}
                                    placeholder={placeholder}
                                    className="w-full px-4 py-2.5 text-sm border border-[#141414]/15 rounded-xl focus:outline-none focus:ring-2 focus:ring-[#141414]/20"
                                />
                            </div>
                        ))}
                        <div>
                            <label className="block text-[10px] font-mono uppercase tracking-widest opacity-50 mb-1.5">Rôle</label>
                            <select
                                value={form.role}
                                onChange={e => setForm(prev => ({ ...prev, role: e.target.value }))}
                                className="w-full px-4 py-2.5 text-sm border border-[#141414]/15 rounded-xl focus:outline-none focus:ring-2 focus:ring-[#141414]/20 bg-white"
                            >
                                <option value="user">Utilisateur</option>
                                <option value="admin">Administrateur</option>
                            </select>
                        </div>

                        {error && (
                            <p className="text-xs text-red-500 bg-red-50 px-3 py-2 rounded-lg">{error}</p>
                        )}

                        <div className="flex gap-3 pt-2">
                            <button
                                onClick={closeModal}
                                className="flex-1 py-2.5 text-xs font-bold border border-[#141414]/15 rounded-xl hover:bg-[#141414]/5 transition-colors"
                            >
                                Annuler
                            </button>
                            <button
                                onClick={handleSave}
                                disabled={saving}
                                className="flex-1 py-2.5 text-xs font-bold bg-[#141414] text-white rounded-xl hover:bg-[#141414]/80 transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
                            >
                                {saving ? (
                                    <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                                ) : (
                                    <><Check size={13} /> {editUser ? 'Enregistrer' : 'Créer'}</>
                                )}
                            </button>
                        </div>
                    </div>
                </Modal>
            )}
        </div>
    );
}
