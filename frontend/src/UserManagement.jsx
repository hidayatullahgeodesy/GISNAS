import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Users, UserPlus, CheckCircle, XCircle } from 'lucide-react';

const API = '/api';
const hdr = (x = {}) => ({
  'X-GISNAS-User': localStorage.getItem('gisnas_username') || '',
  'X-GISNAS-Role': localStorage.getItem('gisnas_role') || '',
  ...x,
});

export default function UserManagement() {
  const [users, setUsers] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ username: '', password: '', nama: '', role: 'user' });
  const nav = useNavigate();
  const role = localStorage.getItem('gisnas_role');
  const me = localStorage.getItem('gisnas_username');

  useEffect(() => {
    if (role !== 'superadmin') nav('/workspaces');
    else load();
  }, []);

  const load = async () => {
    const r = await fetch(API + '/admin/users', { headers: hdr() });
    if (r.ok) setUsers((await r.json()) || []);
  };

  const block = async (u) => {
    if (!confirm('Blokir @' + u + '?')) return;
    await fetch(API + '/admin/users/block', {
      method: 'POST',
      headers: hdr({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ username: u }),
    });
    load();
  };

  const unblock = async (u) => {
    if (!confirm('Buka blokir @' + u + '?')) return;
    await fetch(API + '/admin/users/unblock', {
      method: 'POST',
      headers: hdr({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ username: u }),
    });
    load();
  };

  const create = async () => {
    if (!form.username || !form.password) return alert('Username & password wajib');
    if (form.password.length < 6) return alert('Password minimal 6 karakter');
    const r = await fetch(API + '/admin/users/create', {
      method: 'POST',
      headers: hdr({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(form),
    });
    if (r.ok) {
      alert('User dibuat');
      setForm({ username: '', password: '', nama: '', role: 'user' });
      setShowForm(false);
      load();
    } else {
      const e = await r.json().catch(() => ({}));
      alert(e.error || 'Gagal');
    }
  };

  if (!localStorage.getItem('gisnas_token')) return null;

  return (
    <div className="dashboard-layout" style={{ display: 'block', padding: '2rem 5%' }}>
      <header
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '2rem',
          borderBottom: '1px solid rgba(0,0,0,0.1)',
          paddingBottom: '1rem',
        }}
      >
        <div>
          <h1 style={{ fontSize: '2rem', color: '#ef4444', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Users size={28} /> User Management
          </h1>
          <p style={{ color: '#666' }}>Kelola pengguna, blokir & buat user baru (register publik bisa dimatikan lewat REGISTRATION_ENABLED di .env)</p>
        </div>
        <div style={{ display: 'flex', gap: '1rem' }}>
          <button className="btn btn-primary" onClick={() => setShowForm(!showForm)}>
            <UserPlus size={18} /> {showForm ? 'Tutup' : 'Buat User'}
          </button>
          <button className="btn-logout" onClick={() => nav('/workspaces')} style={{ padding: '0.75rem 1.5rem', width: 'auto' }}>
            Kembali
          </button>
        </div>
      </header>

      {showForm && (
        <div className="glass-panel" style={{ padding: '1.5rem', marginBottom: '2rem', maxWidth: '480px' }}>
          <h3 style={{ marginBottom: '1rem' }}>Buat user baru</h3>
          <input
            className="input-field"
            placeholder="Username"
            value={form.username}
            onChange={(e) => setForm({ ...form, username: e.target.value })}
          />
          <input
            className="input-field"
            type="password"
            placeholder="Password"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
          />
          <input
            className="input-field"
            placeholder="Nama lengkap (opsional)"
            value={form.nama}
            onChange={(e) => setForm({ ...form, nama: e.target.value })}
          />
          <select
            className="input-field"
            value={form.role}
            onChange={(e) => setForm({ ...form, role: e.target.value })}
          >
            <option value="user">user</option>
            <option value="superadmin">superadmin</option>
          </select>
          <button className="btn btn-primary" type="button" onClick={create} style={{ marginTop: '0.5rem' }}>
            Simpan
          </button>
        </div>
      )}

      <div className="glass-panel" style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.95rem' }}>
          <thead>
            <tr style={{ borderBottom: '2px solid #e2e8f0', textAlign: 'left' }}>
              <th style={{ padding: '0.75rem' }}>ID</th>
              <th style={{ padding: '0.75rem' }}>Username</th>
              <th style={{ padding: '0.75rem' }}>Nama</th>
              <th style={{ padding: '0.75rem' }}>Role</th>
              <th style={{ padding: '0.75rem' }}>Status</th>
              <th style={{ padding: '0.75rem' }}>Dibuat</th>
              <th style={{ padding: '0.75rem' }}>Aksi</th>
            </tr>
          </thead>
          <tbody>
            {users.length === 0 && (
              <tr>
                <td colSpan={7} style={{ padding: '1.5rem', color: '#94a3b8', textAlign: 'center' }}>
                  Belum ada user atau gagal memuat data.
                </td>
              </tr>
            )}
            {users.map((u) => (
              <tr key={u.id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                <td style={{ padding: '0.75rem' }}>{u.id}</td>
                <td style={{ padding: '0.75rem' }}>
                  <strong>@{u.username}</strong>
                  {u.username === me && (
                    <span style={{ marginLeft: '0.5rem', fontSize: '0.75rem', color: '#0078d7' }}>(Anda)</span>
                  )}
                </td>
                <td style={{ padding: '0.75rem' }}>{u.nama || '—'}</td>
                <td style={{ padding: '0.75rem' }}>{u.role}</td>
                <td style={{ padding: '0.75rem' }}>
                  {u.is_blocked ? (
                    <span style={{ color: '#ef4444', display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                      <XCircle size={16} /> Diblokir
                    </span>
                  ) : (
                    <span style={{ color: '#22c55e', display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                      <CheckCircle size={16} /> Aktif
                    </span>
                  )}
                </td>
                <td style={{ padding: '0.75rem', fontSize: '0.85rem', color: '#64748b' }}>
                  {u.created_at ? u.created_at.slice(0, 19) : '—'}
                </td>
                <td style={{ padding: '0.75rem' }}>
                  {u.role !== 'superadmin' && u.username !== me && (
                    u.is_blocked ? (
                      <button className="btn" type="button" onClick={() => unblock(u.username)}>
                        Buka blokir
                      </button>
                    ) : (
                      <button
                        className="btn"
                        type="button"
                        style={{ borderColor: '#ef4444', color: '#ef4444' }}
                        onClick={() => block(u.username)}
                      >
                        Blokir
                      </button>
                    )
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
