import { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, useNavigate, Navigate, useParams } from 'react-router-dom';
import { Play, Square, Plus, ShieldAlert, Upload, Map as MapIcon, LogOut, Folder, FilePlus, Trash2, Users, UserPlus, CheckCircle, XCircle } from 'lucide-react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import './index.css';
import UserManagement from './UserManagement.jsx';

const API_BASE = '/api';

const authHeaders = (extra = {}) => ({
  'X-GISNAS-User': localStorage.getItem('gisnas_username') || '',
  'X-GISNAS-Role': localStorage.getItem('gisnas_role') || '',
  ...extra,
});

const renameDataset = async (datasetId, currentName) => {
  const newName = window.prompt('Nama layer baru:', currentName);
  if (!newName || !newName.trim()) return false;
  const res = await fetch(`${API_BASE}/datasets/rename`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ dataset_id: datasetId, name: newName.trim() }),
  });
  if (!res.ok) {
    alert('Gagal mengganti nama: ' + (await res.text()));
    return false;
  }
  return true;
};

const deleteDatasetById = async (datasetId, datasetName) => {
  if (!window.confirm(`Hapus layer "${datasetName}" dan semua data di PostGIS?`)) return false;
  const res = await fetch(`${API_BASE}/datasets/delete?dataset_id=${datasetId}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    alert('Gagal menghapus layer: ' + (await res.text()));
    return false;
  }
  return true;
};

// --- AUTH PAGES ---
function Login() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [registrationEnabled, setRegistrationEnabled] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    fetch(`${API_BASE}/config`)
      .then((r) => (r.ok ? r.json() : null))
      .then((cfg) => {
        if (cfg && typeof cfg.registration_enabled === 'boolean') {
          setRegistrationEnabled(cfg.registration_enabled);
        }
      })
      .catch(() => {});
  }, []);

  const handleLogin = async (e) => {
    e.preventDefault();
    const res = await fetch(`${API_BASE}/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password })
    });
    if (res.ok) {
      const data = await res.json();
      localStorage.setItem('gisnas_token', data.token);
      localStorage.setItem('gisnas_role', data.role);
      localStorage.setItem('gisnas_username', data.username || username);
      localStorage.setItem('gisnas_nama', data.nama || '');
      navigate('/workspaces');
    } else {
      let msg = 'Username atau password salah.';
      try {
        const err = await res.json();
        if (err.error) msg = err.error;
      } catch {
        const text = await res.text();
        if (text) msg = text;
      }
      alert(msg);
    }
  };

  return (
    <div className="auth-container">
      <div className="glass-panel login-box">
        <h2 style={{ marginBottom: '1rem', color: '#1f77b4' }}>Login GISNAS</h2>
        <form onSubmit={handleLogin}>
          <input className="input-field" placeholder="Username" value={username} onChange={e => setUsername(e.target.value)} required autoComplete="username" />
          <input className="input-field" type="password" placeholder="Password" value={password} onChange={e => setPassword(e.target.value)} required autoComplete="current-password" />
          <button className="btn btn-primary" type="submit" style={{ width: '100%', marginTop: '1rem' }}>Login</button>
        </form>
        {registrationEnabled && (
          <p style={{ marginTop: '1.25rem', fontSize: '0.9rem', textAlign: 'center', color: '#666' }}>
            Belum punya akun?{' '}
            <button
              type="button"
              className="btn"
              style={{ margin: 0, padding: '0.25rem 0.5rem', fontSize: '0.9rem' }}
              onClick={() => navigate('/register')}
            >
              Daftar di sini
            </button>
          </p>
        )}
        {!registrationEnabled && (
          <p style={{ marginTop: '1.25rem', fontSize: '0.85rem', textAlign: 'center', color: '#94a3b8' }}>
            Pendaftaran publik dinonaktifkan. Hubungi administrator untuk dibuatkan akun.
          </p>
        )}
      </div>
    </div>
  );
}

function Register() {
  const [username, setUsername] = useState('');
  const [nama, setNama] = useState('');
  const [password, setPassword] = useState('');
  const [password2, setPassword2] = useState('');
  const [loading, setLoading] = useState(false);
  const [registrationEnabled, setRegistrationEnabled] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    fetch(`${API_BASE}/config`)
      .then((r) => (r.ok ? r.json() : null))
      .then((cfg) => {
        if (cfg && typeof cfg.registration_enabled === 'boolean') {
          setRegistrationEnabled(cfg.registration_enabled);
        } else {
          setRegistrationEnabled(true);
        }
      })
      .catch(() => setRegistrationEnabled(true));
  }, []);

  const handleRegister = async (e) => {
    e.preventDefault();
    if (password !== password2) {
      alert('Konfirmasi password tidak sama.');
      return;
    }
    if (password.length < 6) {
      alert('Password minimal 6 karakter.');
      return;
    }
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: username.trim(), password, nama: nama.trim() }),
      });
      if (res.ok) {
        alert('Pendaftaran berhasil. Silakan login.');
        navigate('/');
        return;
      }
      let msg = 'Gagal mendaftar.';
      try {
        const err = await res.json();
        if (err.error) msg = err.error;
      } catch {
        const text = await res.text();
        if (text) msg = text;
      }
      alert(msg);
    } finally {
      setLoading(false);
    }
  };

  if (registrationEnabled === null) {
    return (
      <div className="auth-container">
        <div className="glass-panel login-box">
          <p style={{ textAlign: 'center', color: '#666' }}>Memuat…</p>
        </div>
      </div>
    );
  }

  if (!registrationEnabled) {
    return (
      <div className="auth-container">
        <div className="glass-panel login-box">
          <h2 style={{ marginBottom: '1rem', color: '#1f77b4' }}>Pendaftaran Ditutup</h2>
          <p style={{ color: '#666', marginBottom: '1rem' }}>
            Pendaftaran akun baru sedang dinonaktifkan. Silakan hubungi administrator.
          </p>
          <button type="button" className="btn btn-primary" style={{ width: '100%' }} onClick={() => navigate('/')}>
            Kembali ke Login
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-container">
      <div className="glass-panel login-box">
        <h2 style={{ marginBottom: '1rem', color: '#1f77b4' }}>Daftar Akun GISNAS</h2>
        <form onSubmit={handleRegister}>
          <input
            className="input-field"
            placeholder="Username (min. 3 karakter)"
            value={username}
            onChange={e => setUsername(e.target.value)}
            required
            minLength={3}
            autoComplete="username"
          />
          <input
            className="input-field"
            placeholder="Nama lengkap (opsional)"
            value={nama}
            onChange={e => setNama(e.target.value)}
            autoComplete="name"
          />
          <input
            className="input-field"
            type="password"
            placeholder="Password (min. 6 karakter)"
            value={password}
            onChange={e => setPassword(e.target.value)}
            required
            minLength={6}
            autoComplete="new-password"
          />
          <input
            className="input-field"
            type="password"
            placeholder="Ulangi password"
            value={password2}
            onChange={e => setPassword2(e.target.value)}
            required
            minLength={6}
            autoComplete="new-password"
          />
          <button
            className="btn btn-primary"
            type="submit"
            style={{ width: '100%', marginTop: '1rem' }}
            disabled={loading}
          >
            {loading ? 'Mendaftar...' : 'Daftar'}
          </button>
        </form>
        <p style={{ marginTop: '1.25rem', fontSize: '0.9rem', textAlign: 'center', color: '#666' }}>
          Sudah punya akun?{' '}
          <button
            type="button"
            className="btn"
            style={{ margin: 0, padding: '0.25rem 0.5rem', fontSize: '0.9rem' }}
            onClick={() => navigate('/')}
          >
            Kembali ke login
          </button>
        </p>
      </div>
    </div>
  );
}

// --- WORKSPACES ---
function Workspaces() {
  const [workspaces, setWorkspaces] = useState([]);
  const [collabWsId, setCollabWsId] = useState(null);
  const [inviteUser, setInviteUser] = useState('');
  const [showMembersWsId, setShowMembersWsId] = useState(null);
  const navigate = useNavigate();
  const currentUser = localStorage.getItem('gisnas_username') || '';
  const displayName = localStorage.getItem('gisnas_nama') || '';

  const loadWorkspaces = async () => {
    const res = await fetch(`${API_BASE}/workspaces`, { headers: authHeaders() });
    const data = await res.json();
    setWorkspaces(data || []);
  };

  useEffect(() => {
    loadWorkspaces();
  }, []);

  const createWorkspace = async () => {
    const name = prompt('Nama workspace / proyek peta:');
    if (!name) return;
    await fetch(`${API_BASE}/workspaces`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ name, owner_username: currentUser }),
    });
    loadWorkspaces();
  };

  const deleteWorkspace = async (e, ws) => {
    e.stopPropagation();
    if (!ws.can_delete) {
      alert(`Hanya @${ws.owner_username || 'pemilik'} atau superadmin yang bisa menghapus workspace ini.`);
      return;
    }
    if (!window.confirm(`Hapus workspace "${ws.name}" dan semua data di dalamnya?`)) return;
    const res = await fetch(`${API_BASE}/workspaces?id=${ws.id}`, {
      method: 'DELETE',
      headers: authHeaders(),
    });
    if (!res.ok) {
      alert('Gagal menghapus: ' + (await res.text()));
      return;
    }
    loadWorkspaces();
  };

  const inviteMember = async (e, ws) => {
    e.stopPropagation();
    const raw = inviteUser.trim().replace(/^@/, '');
    if (!raw) return alert('Masukkan username (contoh: budi atau @budi)');
    const res = await fetch(`${API_BASE}/workspaces/members`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ workspace_id: ws.id, username: raw }),
    });
    if (res.ok) {
      setInviteUser('');
      loadWorkspaces();
      alert(`Undangan dikirim ke @${raw}. Tunggu dia menekan "Betulkan Ajakan".`);
    } else {
      let msg = await res.text();
      try {
        const j = JSON.parse(msg);
        if (j.error) msg = j.error;
      } catch {}
      alert(msg);
    }
  };

  const removeMember = async (e, ws, username) => {
    e.stopPropagation();
    if (!window.confirm(`Keluarkan @${username} dari proyek ini?`)) return;
    const res = await fetch(
      `${API_BASE}/workspaces/members?workspace_id=${ws.id}&username=${encodeURIComponent(username)}`,
      { method: 'DELETE', headers: authHeaders() }
    );
    if (res.ok) loadWorkspaces();
    else alert(await res.text());
  };

  const updateMemberPermission = async (ws, username, can_invite, can_open) => {
    await fetch(`${API_BASE}/workspaces/members`, {
      method: 'PATCH',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ workspace_id: ws.id, username, can_invite, can_open }),
    });
    loadWorkspaces();
  };

  const respondInvitation = async (e, ws, action) => {
    e.stopPropagation();
    const res = await fetch(`${API_BASE}/workspaces/invitations/respond`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ workspace_id: ws.id, action }),
    });
    if (res.ok) {
      loadWorkspaces();
      alert(action === 'accept' ? 'Ajakan diterima. Ini sekarang kerjaan bersama.' : 'Ajakan ditolak.');
      return;
    }
    let msg = await res.text();
    try {
      const j = JSON.parse(msg);
      if (j.error) msg = j.error;
    } catch {}
    alert(msg);
  };

  const handleLogout = () => {
    localStorage.removeItem('gisnas_token');
    localStorage.removeItem('gisnas_role');
    localStorage.removeItem('gisnas_username');
    localStorage.removeItem('gisnas_nama');
    navigate('/');
  };

  if (!localStorage.getItem('gisnas_token')) return <Navigate to="/" />;

  return (
    <div className="dashboard-layout" style={{ display: 'block', padding: '2rem 5%' }}>
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '3rem', borderBottom: '1px solid rgba(0,0,0,0.1)', paddingBottom: '1rem' }}>
        <div>
          <h1 style={{ fontSize: '2.5rem', color: '#0078d7' }}>Workspaces</h1>
          <p style={{ color: '#666666', fontSize: '1.1rem' }}>
            Login sebagai{' '}
            <strong>{displayName ? `${displayName} (@${currentUser})` : `@${currentUser}`}</strong>
            {' '}— undang kolaborator dengan @username di setiap proyek
          </p>
        </div>
        <div style={{ display: 'flex', gap: '1rem' }}>
          <button className="btn btn-primary" onClick={createWorkspace}>
            <Plus size={18} /> Create New Workspace
          </button>
          {localStorage.getItem('gisnas_role') === 'superadmin' && (
            <button className="btn" style={{ borderColor: '#ef4444', color: '#ef4444' }} onClick={() => navigate('/admin/users')}>
              <Users size={18} /> User Management
            </button>
          )}
          <button className="btn-logout" onClick={handleLogout} style={{ padding: '0.75rem 1.5rem', width: 'auto' }}>
            <LogOut size={18} /> Logout
          </button>
        </div>
      </header>

      <div style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '2rem'}}>
        {workspaces.map(ws => (
          <div
            key={ws.id}
            className="workspace-card glass-panel"
            onClick={() => {
              if (ws.my_status === 'pending') return;
              if (ws.can_open === false) {
                alert('Kamu tidak punya izin membuka workspace ini.');
                return;
              }
              if (ws.can_open === false) {
                alert('Kamu tidak punya izin membuka workspace ini.');
                return;
              }
              if (ws.can_open === false) {
                alert('Kamu tidak punya izin membuka workspace ini.');
                return;
              }
              navigate(`/workspace/${ws.id}`);
            }}
            style={ws.my_status === 'pending' ? { cursor: 'default', border: '1px solid #f59e0b' } : {}}
          >
            <div style={{display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between'}}>
              <div style={{display: 'flex', alignItems: 'center', gap: '1rem', flex: 1, minWidth: 0}}>
                <div style={{ background: ws.is_collab ? '#ecfdf5' : '#e5f1fb', padding: '1rem', borderRadius: '4px' }}>
                  <Folder size={36} color={ws.is_collab ? '#059669' : '#0078d7'} />
                </div>
                <div style={{ minWidth: 0 }}>
                  <h3 style={{fontSize: '1.3rem', color: '#333333', marginBottom: '0.35rem'}}>{ws.name}</h3>
                  {ws.is_collab && (
                    <a
                      href={`/workspace/${ws.id}`}
                      onClick={(e) => { e.preventDefault(); e.stopPropagation(); navigate(`/workspace/${ws.id}`); }}
                      style={{
                        fontSize: '0.8rem',
                        color: '#0078d7',
                        textDecoration: 'underline',
                        fontWeight: 600,
                        display: 'inline-block',
                        marginBottom: '0.25rem',
                      }}
                    >
                      🔗 Proyek peta bersama
                    </a>
                  )}
                  <p style={{fontSize: '0.85rem', color: '#555555', margin: 0}}>
                    Admin:{' '}
                    <span style={{ color: '#0078d7', fontWeight: 600 }}>@{ws.owner_username || '—'}</span>
                    {' · '}ID #{ws.id}
                  </p>
                  {ws.my_status === 'pending' && (
                    <p style={{ fontSize: '0.8rem', color: '#b45309', marginTop: '0.35rem', fontWeight: 600 }}>
                      @{ws.my_invited_by || ws.owner_username || 'seseorang'} mengajak kamu ke kerjaan bersama ini.
                    </p>
                  )}
                  {ws.members && ws.members.length > 0 && (
                    <p style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '0.35rem' }}>
                      Tim: {ws.members.map((m) => `@${m.username}`).join(', ')}
                    </p>
                  )}
                </div>
              </div>
              {ws.can_delete && (
                <button className="btn-icon-danger" onClick={(e) => deleteWorkspace(e, ws)} title="Hapus workspace (pemilik)">
                  <Trash2 size={18} />
                </button>
              )}
            </div>

            {ws.my_status === 'pending' && (
              <div
                style={{
                  marginTop: '1rem',
                  paddingTop: '1rem',
                  borderTop: '1px solid #fde68a',
                  display: 'flex',
                  gap: '0.5rem',
                  flexWrap: 'wrap',
                }}
                onClick={(e) => e.stopPropagation()}
              >
                <button
                  type="button"
                  className="btn btn-primary"
                  style={{ margin: 0, padding: '0.45rem 0.75rem', fontSize: '0.85rem' }}
                  onClick={(e) => respondInvitation(e, ws, 'accept')}
                >
                  Betulkan Ajakan
                </button>
                <button
                  type="button"
                  className="btn-logout"
                  style={{ margin: 0, padding: '0.45rem 0.75rem', fontSize: '0.85rem', width: 'auto' }}
                  onClick={(e) => respondInvitation(e, ws, 'reject')}
                >
                  Tolak
                </button>
              </div>
            )}

            {ws.can_manage_collab && ws.my_status !== 'pending' && (
              <div
                style={{
                  marginTop: '0.5rem',
                  display: 'flex',
                  gap: '0.35rem',
                }}
                onClick={(e) => e.stopPropagation()}
              >
                <button
                  type="button"
                  className="btn btn-primary"
                  style={{ margin: 0, padding: '0.35rem 0.65rem', fontSize: '0.8rem', flex: 1 }}
                  onClick={(e) => { e.stopPropagation(); setShowMembersWsId(ws.id); }}
                >
                  <Folder size={14} /> User
                </button>
              </div>
            )}
            {ws.can_invite && ws.can_manage_collab && ws.my_status !== 'pending' && (
              <div
                style={{
                  marginTop: '1rem',
                  paddingTop: '1rem',
                  borderTop: '1px solid #e6e6e6',
                }}
                onClick={(e) => e.stopPropagation()}
              >
                <p style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.5rem', color: '#334155' }}>
                  Undang kolaborator (@username):
                </p>
                <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                  <input
                    className="input-field"
                    style={{ margin: 0, flex: 1, minWidth: '120px', padding: '0.4rem 0.6rem', fontSize: '0.85rem' }}
                    placeholder="@username"
                    value={collabWsId === ws.id ? inviteUser : ''}
                    onChange={(e) => { setCollabWsId(ws.id); setInviteUser(e.target.value); }}
                  />
                  <button
                    type="button"
                    className="btn btn-primary"
                    style={{ margin: 0, padding: '0.4rem 0.75rem', fontSize: '0.85rem' }}
                    onClick={(e) => inviteMember(e, ws)}
                  >
                    + Undang
                  </button>
                </div>
                {ws.members && ws.members.filter((m) => m.role !== 'owner').length > 0 && (
                  <div style={{ marginTop: '0.75rem', display: 'flex', flexWrap: 'wrap', gap: '0.35rem' }}>
                    {ws.members.filter((m) => m.role !== 'owner').map((m) => (
                      <span
                        key={m.username}
                        style={{
                          fontSize: '0.75rem',
                          background: '#f1f5f9',
                          padding: '0.2rem 0.5rem',
                          borderRadius: '4px',
                          border: '1px solid #e2e8f0',
                        }}
                      >
                        @{m.username}
                        <button
                          type="button"
                          onClick={(e) => removeMember(e, ws, m.username)}
                          style={{
                            marginLeft: '0.35rem',
                            border: 'none',
                            background: 'transparent',
                            color: '#c92a2a',
                            cursor: 'pointer',
                            fontSize: '0.7rem',
                          }}
                          title="Keluarkan"
                        >
                          ✕
                        </button>
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      {showMembersWsId && (
        <div
          style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            background: 'rgba(0,0,0,0.4)', zIndex: 999,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
          onClick={() => setShowMembersWsId(null)}
        >
          {(() => {
            const ws = workspaces.find(w => w.id === showMembersWsId);
            if (!ws) return null;
            const allMembers = [
              { username: ws.owner_username || '', role: 'owner', can_invite: true, can_open: true },
              ...(ws.members || []),
            ];
            return (
              <div
                style={{ background: 'white', borderRadius: '8px', padding: '1.5rem', maxWidth: '500px', width: '90%', maxHeight: '70vh', overflowY: 'auto' }}
                onClick={(e) => e.stopPropagation()}
              >
                <h3 style={{ margin: '0 0 1rem', color: '#1e293b' }}>User di {ws.name}</h3>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid #e2e8f0' }}>
                      <th style={{ textAlign: 'left', padding: '0.4rem', fontSize: '0.8rem', color: '#64748b' }}>Username</th>
                      <th style={{ textAlign: 'center', padding: '0.4rem', fontSize: '0.75rem', color: '#64748b' }}>Undang</th>
                      <th style={{ textAlign: 'center', padding: '0.4rem', fontSize: '0.75rem', color: '#64748b' }}>Buka</th>
                      <th style={{ textAlign: 'center', padding: '0.4rem', fontSize: '0.75rem', color: '#64748b' }}></th>
                    </tr>
                  </thead>
                  <tbody>
                    {allMembers.map((m, idx) => (
                      <tr key={m.username || idx} style={{ borderBottom: '1px solid #f1f5f9' }}>
                        <td style={{ padding: '0.4rem', fontSize: '0.85rem' }}>
                          <strong>@{m.username}</strong>
                          {m.role === 'owner' && <span style={{ fontSize: '0.65rem', color: '#0078d7', marginLeft: '0.3rem'}}>owner</span>}
                        </td>
                        <td style={{ textAlign: 'center', padding: '0.4rem' }}>
                          {ws.can_delete && m.role !== 'owner' ? (
                            <input type="checkbox" checked={m.can_invite} onChange={() => updateMemberPermission(ws, m.username, !m.can_invite, m.can_open)} />
                          ) : (
                            <span>{m.can_invite ? 'Boleh' : 'Tidak'}</span>
                          )}
                        </td>
                        <td style={{ textAlign: 'center', padding: '0.4rem' }}>
                          {ws.can_delete && m.role !== 'owner' ? (
                            <input type="checkbox" checked={m.can_open} onChange={() => updateMemberPermission(ws, m.username, m.can_invite, !m.can_open)} />
                          ) : (
                            <span>{m.can_open ? 'Boleh' : 'Tidak'}</span>
                          )}
                        </td>
                        <td style={{ textAlign: 'center', padding: '0.4rem' }}>
                          {ws.can_delete && m.role !== 'owner' && (
                            <button type="button" style={{ border: 'none', background: 'transparent', color: '#c92a2a', cursor: 'pointer', fontSize: '0.8rem' }}
                              onClick={(e) => { e.stopPropagation(); removeMember(e, ws, m.username); setShowMembersWsId(null); }} title="Keluarkan user">&#x2715;</button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <button type="button" className="btn" style={{ marginTop: '1rem', width: '100%' }} onClick={() => setShowMembersWsId(null)}>Tutup</button>
              </div>
            );
          })()}
        </div>
      )}
    </div>
  );
}



// --- DASHBOARD COMPONENTS ---
function Sidebar({ setView, workspaceId }) {
  const navigate = useNavigate();
  const role = localStorage.getItem('gisnas_role');
  const [wsInfo, setWsInfo] = useState(null);

  useEffect(() => {
    fetch(`${API_BASE}/workspaces`, { headers: authHeaders() })
      .then((r) => r.json())
      .then((list) => {
        const w = (list || []).find((x) => String(x.id) === String(workspaceId));
        setWsInfo(w || null);
      })
      .catch(() => setWsInfo(null));
  }, [workspaceId]);

  const logout = () => {
    localStorage.removeItem('gisnas_token');
    localStorage.removeItem('gisnas_role');
    localStorage.removeItem('gisnas_username');
    localStorage.removeItem('gisnas_nama');
    navigate('/');
  };

  return (
    <div className="sidebar">
      <div style={{display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem', marginBottom: '0.5rem'}}>
        <h2 className="logo" style={{margin: 0}}>GISNAS</h2>
        {role === 'superadmin' && (
          <span style={{background: '#ef4444', color: 'white', padding: '0.1rem 0.4rem', borderRadius: '4px', fontSize: '0.6rem', fontWeight: 'bold'}}>ADMIN</span>
        )}
      </div>
      <p style={{textAlign: 'center', color: '#94a3b8', fontSize: '0.8rem', marginBottom: '0.5rem'}}>Workspace #{workspaceId}</p>
      {wsInfo?.is_collab && (
        <p style={{ textAlign: 'center', fontSize: '0.75rem', marginBottom: '1rem' }}>
          <a href={`/workspace/${workspaceId}`} style={{ color: '#60a5fa', textDecoration: 'underline' }}>
            🔗 Proyek bersama
          </a>
          <br />
          <span style={{ color: '#94a3b8' }}>@{wsInfo.owner_username}</span>
        </p>
      )}
      
      <nav className="nav-menu">
        <button onClick={() => setView('map')}><MapIcon size={18} /> Map Preview</button>
        <button onClick={() => setView('upload')}><Upload size={18} /> Upload SHP</button>
        <button onClick={() => setView('blank')}><FilePlus size={18} /> Create Document</button>
        <button onClick={() => setView('styling')}><Play size={18} /> Map Styling</button>
        <button onClick={() => setView('api')}><ShieldAlert size={18} /> QGIS Streamlink</button>
      </nav>
      <button className="btn-logout" onClick={() => navigate('/workspaces')} style={{marginTop: 'auto'}}><LogOut size={18} /> Exit Workspace</button>
      <button className="btn-logout" onClick={logout} style={{marginTop: '0.5rem'}}>Logout Account</button>
    </div>
  );
}

function MapPreview() {
  const { id: workspaceId } = useParams();
  const [datasets, setDatasets] = useState([]);
  const [visibleLayers, setVisibleLayers] = useState({});
  const [basemap, setBasemap] = useState('dark');
  const [editingLayer, setEditingLayer] = useState(null);
  const [fillColor, setFillColor] = useState('#3b82f6');
  const [strokeColor, setStrokeColor] = useState('#ffffff');
  const [mapInstance, setMapInstance] = useState(null);
  const [hasFitBounds, setHasFitBounds] = useState(false);

  useEffect(() => {
    setHasFitBounds(false);
  }, [workspaceId]);

  const basemaps = {
    dark: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
    light: 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json'
  };

  const loadDatasets = async () => {
    try {
      const res = await fetch(`${API_BASE}/datasets?workspace_id=${workspaceId}`);
      if (res.ok) {
        const data = await res.json();
        setDatasets(data || []);
        const vis = {};
        data.forEach(d => {
          vis[d.table_name] = true;
        });
        setVisibleLayers(vis);
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleRenameLayer = async (ds) => {
    if (await renameDataset(ds.id, ds.name)) {
      loadDatasets();
    }
  };

  const handleDeleteLayer = async (ds) => {
    if (await deleteDatasetById(ds.id, ds.name)) {
      setEditingLayer(null);
      loadDatasets();
    }
  };

  useEffect(() => {
    loadDatasets();
  }, [workspaceId]);

  useEffect(() => {
    const map = new maplibregl.Map({
      container: 'map',
      style: basemaps[basemap],
      center: [118.0, -2.5],
      zoom: 4,
      transformRequest: (url, resourceType) => {
        if (resourceType === 'Tile' && url.includes('/api/tiles/')) {
          const token = localStorage.getItem('gisnas_token');
          return {
            url,
            headers: {
              ...authHeaders(),
              ...(token ? { Authorization: `Bearer ${token}` } : {}),
            },
          };
        }
        return { url };
      },
    });
    map.addControl(new maplibregl.NavigationControl(), 'top-left');
    
    map.on('load', () => {
      setMapInstance(map);
    });

    return () => {
      map.remove();
    };
  }, [basemap]);

  const getLayerType = (geomType) => {
    const t = (geomType || '').toUpperCase();
    if (t.includes('POINT')) return 'circle';
    if (t.includes('LINE')) return 'line';
    if (t.includes('POLYGON')) return 'fill';
    return 'circle';
  };

  const setupLayerInteraction = (map, ds) => {
    const layerType = getLayerType(ds.geom_type);
    const targetLayer = layerType === 'fill' ? `${ds.table_name}-fill` : ds.table_name;

    map.on('click', targetLayer, (e) => {
      if (e.features.length === 0) return;
      const feature = e.features[0];
      const fid = feature.id ?? feature.properties?.id;

      const html = `<div style="padding: 0.5rem; font-family: sans-serif; color: #1e293b;">
        <div style="font-size: 0.95rem; font-weight: bold; color: #0078d7;">${ds.name}</div>
        <div style="font-size: 0.85rem; color: #64748b; margin-top: 0.25rem;">Feature ID: ${fid ?? '—'}</div>
      </div>`;

      new maplibregl.Popup()
        .setLngLat(e.lngLat)
        .setHTML(html)
        .addTo(map);
    });

    map.on('mouseenter', targetLayer, () => {
      map.getCanvas().style.cursor = 'pointer';
    });
    map.on('mouseleave', targetLayer, () => {
      map.getCanvas().style.cursor = '';
    });
  };

  useEffect(() => {
    if (!mapInstance) return;

    const addAllLayers = () => {
      if (!mapInstance.isStyleLoaded()) return;

      datasets.forEach(ds => {
        if (mapInstance.getSource(ds.table_name)) return;

        mapInstance.addSource(ds.table_name, {
          type: 'vector',
          tiles: [`${window.location.origin}/api/tiles/${ds.table_name}/{z}/{x}/{y}.pbf`],
          maxzoom: 18
        });

        const layerType = getLayerType(ds.geom_type);
        const visibility = visibleLayers[ds.table_name] !== false ? 'visible' : 'none';

        if (layerType === 'fill') {
          mapInstance.addLayer({
            id: `${ds.table_name}-fill`,
            type: 'fill',
            source: ds.table_name,
            'source-layer': ds.table_name,
            paint: {
              'fill-color': ds.fill_color || '#3b82f6',
              'fill-opacity': 0.6
            },
            layout: {
              visibility: visibility
            }
          });
          mapInstance.addLayer({
            id: `${ds.table_name}-outline`,
            type: 'line',
            source: ds.table_name,
            'source-layer': ds.table_name,
            paint: {
              'line-color': ds.stroke_color || '#ffffff',
              'line-width': 1.5
            },
            layout: {
              visibility: visibility
            }
          });
        } else if (layerType === 'line') {
          mapInstance.addLayer({
            id: ds.table_name,
            type: 'line',
            source: ds.table_name,
            'source-layer': ds.table_name,
            paint: {
              'line-color': ds.fill_color || '#3b82f6',
              'line-width': 2.5
            },
            layout: {
              visibility: visibility
            }
          });
        } else if (layerType === 'circle') {
          mapInstance.addLayer({
            id: ds.table_name,
            type: 'circle',
            source: ds.table_name,
            'source-layer': ds.table_name,
            paint: {
              'circle-radius': 6,
              'circle-color': ds.fill_color || '#3b82f6',
              'circle-stroke-width': 1.5,
              'circle-stroke-color': ds.stroke_color || '#ffffff'
            },
            layout: {
              visibility: visibility
            }
          });
        }

        setupLayerInteraction(mapInstance, ds);
      });

      // Fit bounds once when datasets are loaded
      if (datasets.length > 0 && !hasFitBounds) {
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        let hasValidCoords = false;

        datasets.forEach(ds => {
          if (ds.bbox && ds.bbox.length === 4) {
            const isPlaceholder = ds.bbox[0] === 118.0 && ds.bbox[1] === -2.5 && ds.bbox[2] === 118.0 && ds.bbox[3] === -2.5;
            if (!isPlaceholder || datasets.length === 1) {
              minX = Math.min(minX, ds.bbox[0]);
              minY = Math.min(minY, ds.bbox[1]);
              maxX = Math.max(maxX, ds.bbox[2]);
              maxY = Math.max(maxY, ds.bbox[3]);
              hasValidCoords = true;
            }
          }
        });

        if (hasValidCoords && minX !== Infinity) {
          if (minX === maxX && minY === maxY) {
            mapInstance.easeTo({
              center: [minX, minY],
              zoom: 12
            });
          } else {
            mapInstance.fitBounds([[minX, minY], [maxX, maxY]], {
              padding: 80,
              maxZoom: 15,
              duration: 1500
            });
          }
          setHasFitBounds(true);
        }
      }
    };

    mapInstance.on('styledata', addAllLayers);
    addAllLayers();

    return () => {
      if (mapInstance) {
        mapInstance.off('styledata', addAllLayers);
      }
    };

  }, [mapInstance, datasets, hasFitBounds]);

  const toggleVisibility = (tableName, geomType) => {
    const isVisible = !visibleLayers[tableName];
    setVisibleLayers(prev => ({ ...prev, [tableName]: isVisible }));

    if (!mapInstance) return;
    const layerType = getLayerType(geomType);
    const visibilityValue = isVisible ? 'visible' : 'none';

    if (layerType === 'fill') {
      if (mapInstance.getLayer(`${tableName}-fill`)) {
        mapInstance.setLayoutProperty(`${tableName}-fill`, 'visibility', visibilityValue);
      }
      if (mapInstance.getLayer(`${tableName}-outline`)) {
        mapInstance.setLayoutProperty(`${tableName}-outline`, 'visibility', visibilityValue);
      }
    } else {
      if (mapInstance.getLayer(tableName)) {
        mapInstance.setLayoutProperty(tableName, 'visibility', visibilityValue);
      }
    }
  };

  const openStyling = (ds) => {
    setEditingLayer(ds);
    setFillColor(ds.fill_color || '#3b82f6');
    setStrokeColor(ds.stroke_color || '#ffffff');
  };

  const saveLayerStyling = async () => {
    if (!editingLayer) return;
    const res = await fetch(`${API_BASE}/styling`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        dataset_id: editingLayer.id,
        fill_color: fillColor,
        stroke_color: strokeColor
      })
    });
    if (res.ok) {
      setDatasets(prev => prev.map(d => {
        if (d.id === editingLayer.id) {
          return { ...d, fill_color: fillColor, stroke_color: strokeColor };
        }
        return d;
      }));

      if (mapInstance) {
        const layerType = getLayerType(editingLayer.geom_type);
        if (layerType === 'fill') {
          if (mapInstance.getLayer(`${editingLayer.table_name}-fill`)) {
            mapInstance.setPaintProperty(`${editingLayer.table_name}-fill`, 'fill-color', fillColor);
          }
          if (mapInstance.getLayer(`${editingLayer.table_name}-outline`)) {
            mapInstance.setPaintProperty(`${editingLayer.table_name}-outline`, 'line-color', strokeColor);
          }
        } else if (layerType === 'line') {
          if (mapInstance.getLayer(editingLayer.table_name)) {
            mapInstance.setPaintProperty(editingLayer.table_name, 'line-color', fillColor);
          }
        } else if (layerType === 'circle') {
          if (mapInstance.getLayer(editingLayer.table_name)) {
            mapInstance.setPaintProperty(editingLayer.table_name, 'circle-color', fillColor);
            mapInstance.setPaintProperty(editingLayer.table_name, 'circle-stroke-color', strokeColor);
          }
        }
      }

      setEditingLayer(null);
    } else {
      alert("Failed to save styling");
    }
  };

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div id="map" style={{ width: '100%', height: '100%', position: 'absolute', top: 0, left: 0, zIndex: 1 }}></div>

      <div style={{
        position: 'absolute',
        top: '1rem',
        left: '4rem',
        zIndex: 10,
        background: 'rgba(255, 255, 255, 0.85)',
        backdropFilter: 'blur(10px)',
        padding: '0.5rem 1rem',
        borderRadius: '6px',
        boxShadow: '0 4px 20px rgba(0,0,0,0.15)',
        border: '1px solid rgba(255, 255, 255, 0.3)',
        display: 'flex',
        alignItems: 'center',
        gap: '0.75rem',
        pointerEvents: 'auto'
      }}>
        <div>
          <h2 style={{ margin: 0, fontSize: '1rem', fontWeight: 'bold', color: '#1e293b' }}>GISNAS Map</h2>
          <p style={{ margin: 0, fontSize: '0.7rem', color: '#64748b' }}>Workspace #{workspaceId}</p>
        </div>
        <div style={{ display: 'flex', gap: '0.25rem', borderLeft: '1px solid #e2e8f0', paddingLeft: '0.75rem' }}>
          <button 
            className={`btn ${basemap === 'dark' ? 'btn-primary' : ''}`} 
            style={{ padding: '0.2rem 0.4rem', fontSize: '0.7rem', marginTop: 0 }}
            onClick={() => setBasemap('dark')}
          >
            Dark
          </button>
          <button 
            className={`btn ${basemap === 'light' ? 'btn-primary' : ''}`} 
            style={{ padding: '0.2rem 0.4rem', fontSize: '0.7rem', marginTop: 0 }}
            onClick={() => setBasemap('light')}
          >
            Light
          </button>
        </div>
      </div>

      <div style={{
        position: 'absolute',
        top: '1rem',
        right: '1rem',
        zIndex: 10,
        width: '280px',
        maxHeight: 'calc(100vh - 2rem)',
        background: 'rgba(255, 255, 255, 0.85)',
        backdropFilter: 'blur(10px)',
        padding: '1rem',
        borderRadius: '6px',
        boxShadow: '0 4px 20px rgba(0,0,0,0.15)',
        border: '1px solid rgba(255, 255, 255, 0.3)',
        display: 'flex',
        flexDirection: 'column',
        pointerEvents: 'auto',
        overflowY: 'auto'
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', margin: '0 0 0.75rem' }}>
          <h3 style={{ margin: 0, fontSize: '0.9rem', fontWeight: 'bold', color: '#1e293b', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <MapIcon size={16} color="#0078d7" /> Workspace Layers
          </h3>
          {datasets.length > 0 && (
            <button 
              className="btn btn-primary" 
              style={{ margin: 0, padding: '0.25rem 0.5rem', fontSize: '0.65rem' }}
              onClick={() => {
                let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
                let hasValidCoords = false;
                datasets.forEach(ds => {
                  if (ds.bbox && ds.bbox.length === 4) {
                    const isPlaceholder = ds.bbox[0] === 118.0 && ds.bbox[1] === -2.5 && ds.bbox[2] === 118.0 && ds.bbox[3] === -2.5;
                    if (!isPlaceholder || datasets.length === 1) {
                      minX = Math.min(minX, ds.bbox[0]);
                      minY = Math.min(minY, ds.bbox[1]);
                      maxX = Math.max(maxX, ds.bbox[2]);
                      maxY = Math.max(maxY, ds.bbox[3]);
                      hasValidCoords = true;
                    }
                  }
                });
                if (hasValidCoords && minX !== Infinity) {
                  if (minX === maxX && minY === maxY) {
                    mapInstance?.easeTo({ center: [minX, minY], zoom: 12 });
                  } else {
                    mapInstance?.fitBounds([[minX, minY], [maxX, maxY]], { padding: 80, maxZoom: 15 });
                  }
                }
              }}
            >
              Zoom to Data
            </button>
          )}
        </div>

        {datasets.length === 0 ? (
          <p style={{ fontSize: '0.8rem', color: '#64748b', margin: 0, textAlign: 'center', padding: '1rem 0' }}>
            No layers in this workspace. Please upload SHP or create a new document.
          </p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            {datasets.map(ds => {
              const layerType = getLayerType(ds.geom_type);
              const isVisible = visibleLayers[ds.table_name] !== false;
              return (
                <div key={ds.id} style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '0.4rem',
                  borderRadius: '4px',
                  background: 'rgba(255,255,255,0.5)',
                  border: '1px solid rgba(0,0,0,0.05)'
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', flex: 1, minWidth: 0 }}>
                    <input 
                      type="checkbox" 
                      checked={isVisible}
                      onChange={() => toggleVisibility(ds.table_name, ds.geom_type)}
                      style={{ cursor: 'pointer' }}
                    />
                    <div style={{
                      width: '10px',
                      height: '10px',
                      borderRadius: layerType === 'circle' ? '50%' : '2px',
                      background: ds.fill_color || '#3b82f6',
                      border: `1px solid ${ds.stroke_color || '#ffffff'}`,
                      flexShrink: 0
                    }} />
                    <span style={{ fontSize: '0.8rem', color: '#334155', fontWeight: '500', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={ds.name}>
                      {ds.name}
                    </span>
                  </div>
                  <div style={{ display: 'flex', gap: '0.2rem', flexShrink: 0 }}>
                    <button
                      className="btn"
                      style={{ padding: '0.15rem 0.3rem', fontSize: '0.65rem', marginTop: 0 }}
                      onClick={() => openStyling(ds)}
                      title="Warna layer"
                    >
                      Style
                    </button>
                    <button
                      className="btn"
                      style={{ padding: '0.15rem 0.3rem', fontSize: '0.65rem', marginTop: 0 }}
                      onClick={() => handleRenameLayer(ds)}
                      title="Ganti nama"
                    >
                      Rename
                    </button>
                    <button
                      className="btn-logout"
                      style={{ padding: '0.15rem 0.3rem', fontSize: '0.65rem', marginTop: 0 }}
                      onClick={() => handleDeleteLayer(ds)}
                      title="Hapus layer"
                    >
                      Hapus
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {editingLayer && (
          <div style={{
            marginTop: '0.75rem',
            paddingTop: '0.75rem',
            borderTop: '1px solid rgba(0,0,0,0.1)',
            display: 'flex',
            flexDirection: 'column',
            gap: '0.5rem'
          }}>
            <h4 style={{ margin: 0, fontSize: '0.8rem', fontWeight: 'bold', color: '#1e293b' }}>
              Styling: {editingLayer.name}
            </h4>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <div style={{ flex: 1 }}>
                <label style={{ fontSize: '0.7rem', color: '#64748b', display: 'block', marginBottom: '0.15rem' }}>Color</label>
                <input 
                  type="color" 
                  value={fillColor} 
                  onChange={e => setFillColor(e.target.value)} 
                  style={{ width: '100%', height: '24px', border: '1px solid #cbd5e1', borderRadius: '4px', cursor: 'pointer', padding: 0 }} 
                />
              </div>
              {getLayerType(editingLayer.geom_type) !== 'line' && (
                <div style={{ flex: 1 }}>
                  <label style={{ fontSize: '0.7rem', color: '#64748b', display: 'block', marginBottom: '0.15rem' }}>Line</label>
                  <input 
                    type="color" 
                    value={strokeColor} 
                    onChange={e => setStrokeColor(e.target.value)} 
                    style={{ width: '100%', height: '24px', border: '1px solid #cbd5e1', borderRadius: '4px', cursor: 'pointer', padding: 0 }} 
                  />
                </div>
              )}
            </div>
            <div style={{ display: 'flex', gap: '0.25rem', marginTop: '0.15rem' }}>
              <button 
                className="btn btn-primary" 
                style={{ flex: 1, padding: '0.25rem', fontSize: '0.75rem', marginTop: 0 }}
                onClick={saveLayerStyling}
              >
                Save
              </button>
              <button 
                className="btn-logout" 
                style={{ flex: 1, padding: '0.25rem', fontSize: '0.75rem', marginTop: 0 }}
                onClick={() => setEditingLayer(null)}
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function UploadSHP({ workspaceId }) {
  const [file, setFile] = useState(null);
  const handleUpload = async () => {
    if (!file) return alert("Please select a ZIP SHP file first");
    const formData = new FormData();
    formData.append('file', file);
    formData.append('workspace_id', workspaceId);
    
    const res = await fetch(`${API_BASE}/upload`, { method: 'POST', body: formData });
    if (res.ok) {
      alert("Successfully uploaded to Workspace!");
      setFile(null);
    }
  };
  return (
    <div className="content-panel glass-panel">
      <h2>Upload Spatial Data (SHP)</h2>
      <div className="upload-box" style={{ border: '1px dashed var(--border-color)', padding: '3rem', textAlign: 'center', marginTop: '1rem', borderRadius: '4px', background: '#f8f8f8' }}>
        <Upload size={48} color="#0078d7" style={{ marginBottom: '1rem' }} />
        <p>Drag & Drop .zip file (contains .shp, .shx, .dbf)</p>
        <input type="file" onChange={e => setFile(e.target.files[0])} style={{ marginTop: '1rem' }} />
        <br />
        <button className="btn btn-primary" onClick={handleUpload} style={{ marginTop: '1rem' }}>Upload to Database</button>
      </div>
    </div>
  );
}

function CreateBlankDocument({ workspaceId }) {
  const [name, setName] = useState('');
  const [geomType, setGeomType] = useState('POINT');
  const [srid, setSrid] = useState(4326);
  const [columns, setColumns] = useState([]); // [{ name: '', type: 'text' }]

  const handleAddColumn = () => {
    setColumns([...columns, { name: '', type: 'text' }]);
  };

  const handleRemoveColumn = (index) => {
    setColumns(columns.filter((_, i) => i !== index));
  };

  const handleColumnChange = (index, key, value) => {
    const updated = [...columns];
    updated[index][key] = value;
    setColumns(updated);
  };

  const handleCreate = async () => {
    if(!name) return alert("Fill in table name");
    
    for (let col of columns) {
      if (!col.name) return alert("All columns must have a name!");
    }

    const res = await fetch(`${API_BASE}/datasets/create_blank`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ 
        workspace_id: parseInt(workspaceId), 
        name, 
        geom_type: geomType, 
        srid: parseInt(srid),
        columns
      })
    });
    if(res.ok) {
      alert("Spatial document successfully created with custom attributes!");
      setName('');
      setColumns([]);
    } else {
      alert("Failed to create document");
    }
  };

  return (
    <div className="content-panel glass-panel">
      <h2>Create Document & Struktur Kolom Baru</h2>
      <p style={{color: '#555555', marginTop: '1rem'}}>Create new PostGIS table manually with custom geometry type and attributes.</p>
      
      <div style={{marginTop: '2rem', display: 'flex', flexDirection: 'column', gap: '1rem'}}>
        <div>
          <label style={{fontWeight: 'bold'}}>Document / Table Name</label>
          <input className="input-field" value={name} onChange={e=>setName(e.target.value)} placeholder="Example: Point_Road" style={{marginTop: '0.5rem'}}/>
        </div>
        
        <div style={{display: 'flex', gap: '1rem'}}>
          <div style={{flex: 1}}>
            <label style={{fontWeight: 'bold'}}>Geometry Type</label>
            <select className="input-field" value={geomType} onChange={e=>setGeomType(e.target.value)} style={{marginTop: '0.5rem'}}>
              <option value="POINT">POINT (Point)</option>
              <option value="LINESTRING">LINESTRING (Line)</option>
              <option value="POLYGON">POLYGON (Area)</option>
            </select>
          </div>
          <div style={{flex: 1}}>
            <label style={{fontWeight: 'bold'}}>EPSG (Coordinate System)</label>
            <input className="input-field" type="number" value={srid} onChange={e=>setSrid(e.target.value)} style={{marginTop: '0.5rem'}}/>
          </div>
        </div>

        {/* Dynamic Columns Specification */}
        <div style={{background: '#f8f9fa', padding: '1.5rem', borderRadius: '6px', border: '1px solid #e6e6e6', marginTop: '1rem'}}>
          <h4 style={{marginBottom: '1rem', fontWeight: '600'}}>Custom Attribute Column Structure (Non-Spatial)</h4>
          <p style={{fontSize: '0.8rem', color: '#666', marginBottom: '1rem'}}>By default, columns <code>id</code> and <code>geom</code> will be created automatically.</p>
          
          <div style={{display: 'flex', flexDirection: 'column', gap: '0.75rem'}}>
            {columns.map((col, index) => (
              <div key={index} style={{display: 'flex', gap: '1rem', alignItems: 'center'}}>
                <input 
                  className="input-field" 
                  style={{marginBottom: 0, flex: 2}}
                  placeholder="Column Name, e.g. NAMOBJ" 
                  value={col.name}
                  onChange={e => handleColumnChange(index, 'name', e.target.value)}
                />
                <select 
                  className="input-field" 
                  style={{marginBottom: 0, flex: 1}}
                  value={col.type}
                  onChange={e => handleColumnChange(index, 'type', e.target.value)}
                >
                  <option value="text">TEXT (Text)</option>
                  <option value="integer">INTEGER (Long Integer)</option>
                  <option value="smallint">SMALLINT (Short Integer)</option>
                  <option value="double">DOUBLE PRECISION (Double)</option>
                  <option value="date">DATE (Tanggal)</option>
                  <option value="timestamp">TIMESTAMP (Tanggal & Waktu)</option>
                  <option value="boolean">BOOLEAN (Y/N)</option>
                </select>
                <button 
                  className="btn-logout" 
                  style={{marginTop: 0, borderTop: 'none', padding: '0.5rem', display: 'flex', alignItems: 'center', width: 'auto'}}
                  onClick={() => handleRemoveColumn(index)}
                >
                  Delete
                </button>
              </div>
            ))}
          </div>

          <button className="btn" style={{marginTop: '1rem'}} onClick={handleAddColumn}>
            + Add Attribute Column
          </button>
        </div>

        <button className="btn btn-primary" onClick={handleCreate} style={{width: 'fit-content', marginTop: '1rem'}}>Save Dokumen</button>
      </div>
    </div>
  );
}

function OGCAPI({ workspaceId }) {
  const [tokens, setTokens] = useState([]);
  const [datasets, setDatasets] = useState([]);
  const [selectedDataset, setSelectedDataset] = useState(null);

  const fetchTokens = async () => {
    const res = await fetch(`${API_BASE}/tokens?workspace_id=${workspaceId}`);
    setTokens(await res.json() || []);
  };

  const fetchDatasets = async () => {
    const res = await fetch(`${API_BASE}/datasets?workspace_id=${workspaceId}`);
    const data = await res.json();
    setDatasets(data || []);
    if (data && data.length > 0) {
      setSelectedDataset(data[0]);
    }
  };

  useEffect(() => {
    fetchTokens();
    fetchDatasets();
  }, [workspaceId]);

  const toggleToken = async (tokenStr) => {
    await fetch(`${API_BASE}/tokens/toggle?token=${tokenStr}`, { method: 'POST' });
    fetchTokens();
  };

  const deleteToken = async (tokenStr) => {
    if(window.confirm("Are you sure you want to permanently delete this token?")) {
      await fetch(`${API_BASE}/tokens/delete?token=${tokenStr}`, { method: 'DELETE' });
      fetchTokens();
    }
  };

  const generateToken = async () => {
    await fetch(`${API_BASE}/tokens/generate?workspace_id=${workspaceId}`, { method: 'POST' });
    fetchTokens();
  };

  const getOGCApiUrl = (tokenStr) => {
    const host = window.location.hostname;
    const tokenPart = tokenStr ? `/token/${tokenStr}` : '';
    return `http://${host}${tokenPart}/api/ogc/features`;
  };

  return (
    <div className="content-panel glass-panel">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2>QGIS Streamlink (OGC API Features)</h2>
        <button className="btn btn-primary" onClick={generateToken}><Plus size={18} /> Generate Token</button>
      </div>

      <div style={{ marginTop: '1rem', marginBottom: '1.5rem', background: '#f8f8f8', border: '1px solid #e0e0e0', padding: '1rem', borderRadius: '4px' }}>
        <p style={{ color: '#333333', fontSize: '0.85rem', marginBottom: '0.5rem', fontWeight: 'bold' }}>Gunakan URL Utama ini di QGIS (Menu WFS / OGC API Features):</p>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
          <code style={{ color: '#0078d7', fontSize: '0.95rem', fontWeight: 'bold', wordBreak: 'break-all', background: '#fff', padding: '0.5rem', borderRadius: '4px', border: '1px solid #e0e0e0', flex: 1 }}>
            {tokens.length > 0 ? getOGCApiUrl(tokens[0].token_string) : getOGCApiUrl('TOKEN_ANDA')}
          </code>
          <button 
            className="btn btn-primary" 
            style={{ padding: '0.5rem 1rem', whiteSpace: 'nowrap', marginTop: 0 }}
            onClick={() => {
              const url = tokens.length > 0 ? getOGCApiUrl(tokens[0].token_string) : getOGCApiUrl('TOKEN_ANDA');
              navigator.clipboard.writeText(url);
              alert("Main OGC API URL successfully copied to clipboard!");
            }}
          >
            Salin URL
          </button>
        </div>
      </div>

      {/* Direct GeoJSON Link display */}
      {datasets.length > 0 && selectedDataset && tokens.length > 0 && (
        <div style={{ marginTop: '1.5rem', marginBottom: '2rem', background: '#f0f7ff', border: '1px solid #cce3ff', padding: '1rem', borderRadius: '4px' }}>
          <p style={{ color: '#004085', fontSize: '0.85rem', marginBottom: '0.5rem', fontWeight: 'bold' }}>
            🔗 Link Direct GeoJSON (Daftar Fitur Tabel Spasial):
          </p>
          <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem', alignItems: 'center' }}>
            <label style={{ fontSize: '0.85rem', color: '#004085', fontWeight: 'bold' }}>Pilih Dokumen:</label>
            <select 
              className="input-field" 
              style={{ margin: 0, padding: '0.25rem 0.5rem', fontSize: '0.85rem', width: 'auto', background: '#fff' }} 
              value={selectedDataset.id} 
              onChange={(e) => {
                const ds = datasets.find(d => d.id === parseInt(e.target.value));
                setSelectedDataset(ds);
              }}
            >
              {datasets.map(ds => (
                <option key={ds.id} value={ds.id}>{ds.name} ({ds.geom_type})</option>
              ))}
            </select>
          </div>
          <p style={{ color: '#333', fontSize: '0.8rem', marginBottom: '0.5rem' }}>
            Salin link ini untuk melihat isi GeoJSON tabel/fitur secara langsung (di Browser atau di QGIS Add Vector Layer by Protocol):
          </p>
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
            <code style={{ color: '#2ca02c', fontSize: '0.9rem', fontWeight: 'bold', wordBreak: 'break-all', background: '#fff', padding: '0.5rem', borderRadius: '4px', border: '1px solid #cce3ff', flex: 1 }}>
              {`${getOGCApiUrl(tokens[0].token_string)}/collections/${selectedDataset.table_name}/items`}
            </code>
            <button 
              className="btn btn-primary" 
              style={{ padding: '0.5rem 1rem', whiteSpace: 'nowrap', marginTop: 0 }}
              onClick={() => {
                const url = `${getOGCApiUrl(tokens[0].token_string)}/collections/${selectedDataset.table_name}/items`;
                navigator.clipboard.writeText(url);
                alert("Link GeoJSON Success disalin ke clipboard!");
              }}
            >
              Salin Link
            </button>
          </div>
        </div>
      )}

      <table style={{ width: '100%', marginTop: '1rem' }}>
        <thead><tr><th>Token</th><th>Status</th><th>Action</th></tr></thead>
        <tbody>
          {tokens.map(t => (
            <tr key={t.id}>
              <td className="token-string">{t.token_string}</td>
              <td><span className={`status-badge ${t.status === 'RUNNING' ? 'status-running' : 'status-stopped'}`}>{t.status}</span></td>
              <td>
                <div style={{display: 'flex', gap: '0.5rem'}}>
                  <button className="toggle-btn" onClick={() => toggleToken(t.token_string)} title="Pause/Play Token">
                    {t.status === 'RUNNING' ? <Square size={16} fill="#c92a2a" color="#c92a2a" /> : <Play size={16} fill="#2b8a3e" color="#2b8a3e" />}
                  </button>
                  <button className="toggle-btn" onClick={() => deleteToken(t.token_string)} title="Delete Token">
                    <Trash2 size={16} color="#495057" />
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MapStyling({ workspaceId }) {
  const [datasets, setDatasets] = useState([]);
  const [selectedDataset, setSelectedDataset] = useState(null);
  const [fillColor, setFillColor] = useState('#3b82f6');
  const [strokeColor, setStrokeColor] = useState('#ffffff');

  const loadDatasets = async () => {
    const res = await fetch(`${API_BASE}/datasets?workspace_id=${workspaceId}`);
    const data = await res.json();
    setDatasets(data || []);
    if (data && data.length > 0) {
      setSelectedDataset(data[0]);
      setFillColor(data[0].fill_color || '#3b82f6');
      setStrokeColor(data[0].stroke_color || '#ffffff');
    }
  };

  useEffect(() => {
    loadDatasets();
  }, [workspaceId]);

  const handleDatasetChange = (e) => {
    const ds = datasets.find(d => d.id === parseInt(e.target.value));
    setSelectedDataset(ds);
    if (ds) {
      setFillColor(ds.fill_color || '#3b82f6');
      setStrokeColor(ds.stroke_color || '#ffffff');
    }
  };

  const handleSave = async () => {
    if (!selectedDataset) return alert("Pilih dataset terlebih dahulu");
    const res = await fetch(`${API_BASE}/styling`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        dataset_id: selectedDataset.id,
        fill_color: fillColor,
        stroke_color: strokeColor
      })
    });
    if (res.ok) {
      alert("Styling Success disimpan secara permanen di PostGIS!");
      loadDatasets();
    }
  };

  return (
    <div className="content-panel glass-panel">
      <h2>Map Styling Editor</h2>
      <p style={{ color: '#555555', marginTop: '1rem' }}>Sesuaikan warna, tebal garis, dan simbol layer di sini.</p>
      
      {datasets.length > 0 ? (
        <div style={{ marginTop: '1.5rem' }}>
          <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 'bold' }}>Pilih Dokumen / Dataset:</label>
          <select 
            className="input-field" 
            style={{ width: '100%', maxWidth: '400px' }}
            value={selectedDataset?.id || ''} 
            onChange={handleDatasetChange}
          >
            {datasets.map(ds => (
              <option key={ds.id} value={ds.id}>{ds.name} ({ds.geom_type})</option>
            ))}
          </select>

          <div style={{ display: 'flex', gap: '1rem', marginTop: '2rem' }}>
            <div style={{ flex: 1, background: '#f8f8f8', border: '1px solid var(--border-color)', padding: '1rem', borderRadius: '4px' }}>
              <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 'bold' }}>
                {selectedDataset?.geom_type?.toUpperCase()?.includes('LINE') ? 'Color Line' : 'Color Isi (Fill)'}
              </label>
              <input type="color" value={fillColor} onChange={e => setFillColor(e.target.value)} style={{ width: '100%', height: '40px', border: '1px solid var(--border-color)' }} />
            </div>
            {!selectedDataset?.geom_type?.toUpperCase()?.includes('LINE') && (
              <div style={{ flex: 1, background: '#f8f8f8', border: '1px solid var(--border-color)', padding: '1rem', borderRadius: '4px' }}>
                <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 'bold' }}>Color Line (Stroke)</label>
                <input type="color" value={strokeColor} onChange={e => setStrokeColor(e.target.value)} style={{ width: '100%', height: '40px', border: '1px solid var(--border-color)' }} />
              </div>
            )}
          </div>
          <button className="btn btn-primary" onClick={handleSave} style={{ marginTop: '2rem' }}>Save Styling ke Database</button>
        </div>
      ) : (
        <p style={{ color: '#999', marginTop: '2rem' }}>Belum ada dokumen/dataset spasial yang dibuat di Workspace ini.</p>
      )}
    </div>
  );
}

function WorkspaceDashboard() {
  const { id } = useParams();
  const [view, setView] = useState('map');
  
  if (!localStorage.getItem('gisnas_token')) return <Navigate to="/" />;

  return (
    <div className="dashboard-layout">
      <Sidebar setView={setView} workspaceId={id} />
      <div className="main-content" style={view === 'map' ? { padding: 0, overflow: 'hidden', height: '100%', position: 'relative' } : {}}>
        {view === 'map' && <MapPreview />}
        {view === 'upload' && <UploadSHP workspaceId={id} />}
        {view === 'blank' && <CreateBlankDocument workspaceId={id} />}
        {view === 'api' && <OGCAPI workspaceId={id} />}
        {view === 'styling' && <MapStyling workspaceId={id} />}
      </div>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/workspaces" element={<Workspaces />} />
        <Route path="/workspace/:id" element={<WorkspaceDashboard />} />
        <Route path="/admin/users" element={<UserManagement />} />
      </Routes>
    </BrowserRouter>
  );
}
