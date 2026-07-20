import { Outlet, Link, useNavigate, useLocation } from 'react-router-dom';
import { Toaster } from 'react-hot-toast';
import { useAuth } from '../context/AuthContext';
import { useState, useEffect, useRef } from 'react';
import toast from 'react-hot-toast';
import { apiFetch } from '../utils/api';
import { ThemeProvider, CssBaseline } from '@mui/material';
import { getAppTheme } from '../theme';
import { Sidebar } from './Sidebar';

export const AppLayout = () => {
  const { user, logout, setUser } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  
  // Theme state
  const [theme, setTheme] = useState(() => {
    return localStorage.getItem('bl-theme') || 'dark';
  });

  // UI state
  const [notifOpen, setNotifOpen] = useState(false);
  const [notifs, setNotifs] = useState<any[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  
  // Upgrade Modal state
  const [upgradeOpen, setUpgradeOpen] = useState(false);
  const [upgradeMessage, setUpgradeMessage] = useState('');
  const [upgradeCta, setUpgradeCta] = useState('/pricing');

  const notifRef = useRef<HTMLDivElement>(null);

  // Apply theme to HTML tag
  useEffect(() => {
    const root = document.documentElement;
    root.setAttribute('data-theme', theme);
    localStorage.setItem('bl-theme', theme);
  }, [theme]);

  // Sync theme with user preferences
  useEffect(() => {
    if (user?.theme_preference) {
      setTheme(user.theme_preference);
    }
  }, [user?.theme_preference]);

  // Handle outside clicks to close notification panel
  useEffect(() => {
    const handleOutsideClick = (e: MouseEvent) => {
      if (notifRef.current && !notifRef.current.contains(e.target as Node)) {
        setNotifOpen(false);
      }
    };
    document.addEventListener('click', handleOutsideClick);
    return () => document.removeEventListener('click', handleOutsideClick);
  }, []);

  // Fetch notifications
  const fetchNotifications = async () => {
    if (!user) return;
    try {
      const data = await apiFetch('/api/notifications');
      if (data.ok) {
        setNotifs(data.notifications || []);
        setUnreadCount(data.unread || 0);
      }
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    fetchNotifications();
    const interval = setInterval(fetchNotifications, 60000);
    return () => clearInterval(interval);
  }, [user]);

  // Hook global handler for upgrade prompt (Flask compat)
  useEffect(() => {
    (window as any).blHandleUpgrade = (data: any) => {
      if (data && data.error === 'upgrade_required') {
        setUpgradeMessage(data.message || 'This feature requires a Pro plan.');
        setUpgradeCta(data.cta || '/pricing');
        setUpgradeOpen(true);
        return true;
      }
      return false;
    };
    return () => {
      delete (window as any).blHandleUpgrade;
    };
  }, []);

  const toggleTheme = async () => {
    const nextTheme = theme === 'dark' ? 'light' : 'dark';
    setTheme(nextTheme);
    localStorage.setItem('bl-theme', nextTheme);
    
    if (user) {
      setUser(prev => prev ? { ...prev, theme_preference: nextTheme } : null);
      try {
        await apiFetch('/api/settings', {
          method: 'POST',
          body: { theme_preference: nextTheme }
        });
      } catch (err) {
        console.error('Failed to sync theme preference with backend', err);
      }
    }
  };

  const handleLogout = async () => {
    await logout();
    toast.success('Logged out successfully');
    navigate('/login');
  };

  const markRead = async (id: number, link: string | null) => {
    try {
      const res = await apiFetch('/api/notifications/read', {
        method: 'POST',
        body: { id }
      });
      if (res.ok) {
        if (link) {
          navigate(link);
        } else {
          fetchNotifications();
        }
      }
    } catch (err) {
      console.error(err);
    }
  };

  const clearAllNotifs = async () => {
    try {
      const res = await apiFetch('/api/notifications/clear', { method: 'POST' });
      if (res.ok) {
        fetchNotifications();
      }
    } catch (err) {
      console.error(err);
    }
  };

  // Active workspace state is controlled by active sub-views

  return (
    <ThemeProvider theme={getAppTheme(theme as 'light' | 'dark')}>
      <CssBaseline />
      <div className="min-h-screen bg-[var(--bg)] text-[var(--text)] flex flex-col font-sans">
        <Toaster position="top-right" toastOptions={{
          style: {
            background: 'var(--surface)',
            color: 'var(--text)',
            border: '1px solid var(--border)',
          }
        }} />

      <style>{`
        .bl-nav {
          position: sticky; top: 0; z-index: 200;
          background: rgba(var(--surface-rgb), 0.75);
          backdrop-filter: blur(16px);
          -webkit-backdrop-filter: blur(16px);
          border-bottom: 1px solid var(--border);
          height: 54px;
        }
        .bl-nav-inner {
          display: flex; align-items: center; gap: 8px;
          max-width: 1600px; margin: 0 auto; padding: 0 20px; height: 100%;
        }
        .bl-logo {
          font-size: 14pt; font-weight: 700; color: var(--white);
          text-decoration: none; white-space: nowrap;
        }
        .bl-logo span { color: var(--accent); }

        .bl-nav-tabs { display: flex; list-style: none; gap: 2px; flex: 1; justify-content: center; }
        .bl-tab { position: relative; }
        .bl-tab-btn {
          background: none; border: none; color: var(--muted);
          font-size: 0.95rem; font-weight: 500; padding: 0 14px; height: 54px;
          cursor: pointer; white-space: nowrap; transition: all 0.2s ease;
          font-family: inherit; display: flex; align-items: center; gap: 4px;
        }
        .bl-tab-btn:hover { color: var(--white); }
        .bl-tab.active .bl-tab-btn { color: var(--accent); border-bottom: 2px solid var(--accent); }
        .bl-caret { font-size: 8pt; }

        .bl-dropdown {
          display: none; position: absolute; top: 54px; left: 0;
          background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
          padding: 8px 0; min-width: 200px; box-shadow: 0 8px 32px rgba(0,0,0,0.3); z-index: 300;
        }
        .bl-dropdown-right { left: auto; right: 0; }
        .bl-tab:hover .bl-dropdown, .bl-tab.open .bl-dropdown { display: block; }
        .bl-dropdown a, .bl-dropdown button {
          display: block; width: 100%; text-align: left; padding: 10px 20px; color: var(--muted); text-decoration: none;
          font-size: 0.9rem; white-space: nowrap; transition: all 0.2s ease; background: none; border: none; cursor: pointer;
        }
        .bl-dropdown a:hover, .bl-dropdown button:hover { background: var(--surface2); color: var(--white); padding-left: 24px; }
        .bl-dropdown-divider { border: none; border-top: 1px solid var(--border); margin: 6px 0; }
        .bl-admin-link { color: var(--accent) !important; }

        .bl-nav-right { display: flex; align-items: center; gap: 6px; }
        .bl-icon-btn {
          background: none; border: none; color: var(--muted); font-size: 14pt;
          cursor: pointer; padding: 4px 8px; border-radius: 4px; position: relative;
          transition: color 0.15s; line-height: 1;
        }
        .bl-icon-btn:hover { color: var(--white); }
        .bl-badge {
          position: absolute; top: 0; right: 0; background: var(--accent); color: #fff;
          font-size: 7pt; font-weight: 700; border-radius: 50%; min-width: 14px; height: 14px;
          display: flex; align-items: center; justify-content: center; padding: 0 2px;
        }

        .bl-user-btn {
          display: flex; align-items: center; gap: 6px; padding: 0 10px; height: 32px;
          border: 1px solid var(--border); border-radius: 6px; font-size: 9.5pt;
        }
        .bl-pro-badge {
          background: var(--accent); color: #fff; font-size: 8pt; font-weight: 700;
          padding: 1px 6px; border-radius: 10px;
        }
        .bl-free-left { color: var(--muted); font-size: 8.5pt; }

        .bl-notif-panel {
          display: none; position: fixed; top: 52px; right: 16px; width: 340px;
          max-height: 480px; overflow-y: auto; background: var(--surface);
          border: 1px solid var(--border); border-radius: 10px;
          box-shadow: 0 8px 32px rgba(0,0,0,0.5); z-index: 999; padding: 16px;
        }
        .bl-notif-panel.open { display: block; }

        .bl-upgrade-overlay {
          display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.6);
          z-index: 998; align-items: center; justify-content: center;
        }
        .bl-upgrade-overlay.open { display: flex; }
        .bl-upgrade-card {
          background: var(--surface); border: 1px solid var(--accent); border-radius: 12px;
          padding: 32px; max-width: 380px; width: 90%; text-align: center;
        }
        .bl-upgrade-icon { font-size: 26pt; margin-bottom: 12px; }
        .bl-upgrade-card h3 { color: var(--white); margin-bottom: 10px; font-size: 14pt; }
        .bl-upgrade-card p { color: var(--muted); font-size: 10pt; margin-bottom: 20px; line-height: 1.5; }
        .bl-upgrade-btn {
          display: block; background: linear-gradient(135deg, var(--accent), var(--accent-gradient)); color: #fff;
          padding: 12px; border-radius: 8px; text-decoration: none; font-weight: 700; margin-bottom: 12px; font-size: 0.95rem;
          transition: all 0.2s ease; box-shadow: 0 4px 15px rgba(var(--accent-rgb), 0.2);
        }
        .bl-upgrade-btn:hover {
          transform: translateY(-2px); box-shadow: 0 6px 20px rgba(var(--accent-rgb), 0.4);
        }
        .bl-upgrade-dismiss {
          background: none; border: none; color: var(--muted);
          font-size: 0.85rem; cursor: pointer; text-decoration: underline; font-family: inherit;
          transition: color 0.2s ease;
        }
        .bl-upgrade-dismiss:hover { color: var(--white); }

        .bl-hamburger { display: none; }

        @media (max-width: 900px) {
          .bl-nav-tabs {
            display: none; flex-direction: column; position: fixed; top: 48px; left: 0; right: 0;
            background: var(--surface); border-bottom: 1px solid var(--border);
            padding: 12px 0; z-index: 200; max-height: calc(100vh - 48px); overflow-y: auto;
          }
          .bl-nav-tabs.open { display: flex; }
          .bl-hamburger { display: flex; }
          .bl-tab { width: 100%; }
          .bl-tab-btn { width: 100%; text-align: left; padding: 10px 20px; height: auto; }
          .bl-dropdown { position: static; box-shadow: none; border: none; padding-left: 16px; display: none; }
          .bl-tab.open .bl-dropdown { display: block; }
          .bl-tab:hover .bl-dropdown { display: none; }
          .bl-tab.open:hover .bl-dropdown { display: block; }
        }
      `}</style>

      <div className="flex flex-col h-screen w-screen overflow-hidden bg-nexus-bg text-nexus-text font-sans">
        {/* Header Bar */}
        <header className="h-16 px-6 border-b border-nexus-border bg-nexus-sf flex items-center justify-between shrink-0 z-50">
          <div className="flex items-center gap-6">
            <Link to="/" className="text-xl font-bold tracking-wider">
              <span className="text-nexus-white">Bull</span>
              <span className="text-nexus-pur">Logic</span>
            </Link>

            {location.pathname.startsWith('/admin') ? (
              <span className="text-nexus-pur font-bold text-xs uppercase bg-nexus-pur/10 px-3 py-1 rounded-full border border-nexus-pur/20 animate-pulse">
                Admin Console
              </span>
            ) : (
              <span className="text-nexus-muted text-xs font-bold uppercase tracking-wider">
                Workspace
              </span>
            )}
          </div>

          <div className="flex items-center gap-4">
            <Toaster position="top-right" toastOptions={{
              style: {
                background: 'var(--surface)',
                color: 'var(--text)',
                border: '1px solid var(--border)',
              }
            }} />
            {user && (
              <div style={{ position: 'relative' }} ref={notifRef}>
                <button className="bl-icon-btn" onClick={() => setNotifOpen(prev => !prev)} title="Notifications">
                  🔔
                  {unreadCount > 0 && <span className="bl-badge">{unreadCount}</span>}
                </button>

                {/* Notification Panel */}
                <div className={`bl-notif-panel ${notifOpen ? 'open' : ''}`}>
                  <div className="flex justify-between items-center mb-4">
                    <span className="font-bold text-nexus-white">Notifications</span>
                    <button onClick={clearAllNotifs} className="bg-none border-none text-nexus-muted text-xs cursor-pointer hover:text-nexus-white">Clear all</button>
                  </div>
                  <div className="flex flex-col gap-2 max-h-[300px] overflow-y-auto">
                    {notifs.length === 0 ? (
                      <div className="text-nexus-muted text-sm text-center py-5">No notifications</div>
                    ) : (
                      notifs.map(n => (
                        <div key={n.id} onClick={() => markRead(n.id, n.link)} 
                             className="p-3 rounded-lg border border-nexus-border cursor-pointer text-left transition-all hover:bg-nexus-bg2"
                             style={{ background: n.read ? 'transparent' : 'rgba(255,107,53,0.07)' }}>
                          <div className="flex gap-2 items-start">
                            <span>{n.type === 'alert' ? '🔔' : n.type === 'signal' ? '📊' : 'ℹ️'}</span>
                            <div>
                              <div className={`text-sm text-nexus-white ${n.read ? 'font-medium opacity-70' : 'font-bold'}`}>{n.title}</div>
                              {n.body && <div className="text-xs text-nexus-muted mt-1">{n.body}</div>}
                            </div>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </div>
            )}

            <button className="bl-icon-btn" onClick={toggleTheme} title="Toggle theme">
              {theme === 'dark' ? '☀️' : '🌙'}
            </button>

            {user && (
              <div className="relative group">
                <button className="bl-tab-btn bl-user-btn" type="button">
                  <span>{user.username}</span>
                  {user.is_pro ? (
                    <span className="bl-pro-badge ml-2">PRO</span>
                  ) : user.is_plus ? (
                    <span className="bl-pro-badge ml-2 bg-nexus-blu text-nexus-white">PLUS</span>
                  ) : (
                    <span className="bl-free-left ml-2">{user.predictions_remaining ?? 5}/5</span>
                  )}
                </button>
                <div className="absolute right-0 top-full mt-2 w-48 bg-nexus-sf border border-nexus-border rounded-xl py-2 hidden group-hover:block hover:block z-50 shadow-2xl animate-fadeIn">
                  <Link to="/settings" className="block px-4 py-2 text-xs text-nexus-text hover:bg-nexus-bg2 hover:text-nexus-white">Profile & Settings</Link>
                  <Link to="/pricing" className="block px-4 py-2 text-xs text-nexus-text hover:bg-nexus-bg2 hover:text-nexus-white">Upgrade / Billing</Link>
                  {user.role_level >= 3 && <Link to="/admin" className="block px-4 py-2 text-xs text-nexus-pur font-bold hover:bg-nexus-bg2">Admin Console</Link>}
                  <hr className="border-nexus-border my-1" />
                  <button onClick={handleLogout} className="w-full text-left px-4 py-2 text-xs text-red-400 hover:bg-nexus-bg2">Logout</button>
                </div>
              </div>
            )}
          </div>
        </header>

        {/* Workspace Split Layout */}
        <div className="flex-1 flex overflow-hidden w-full bg-nexus-bg">
          {/* Sidebar Navigation Shell on the Left */}
          <Sidebar />

          {/* Main Content Area on the Right */}
          <main className="flex-1 overflow-y-auto p-4 md:p-8 flex flex-col gap-6">
            <Outlet />
          </main>
        </div>
      </div>

      {/* Upgrade Overlay Modal */}
      <div className={`bl-upgrade-overlay ${upgradeOpen ? 'open' : ''}`} onClick={() => setUpgradeOpen(false)}>
        <div className="bl-upgrade-card" onClick={(e) => e.stopPropagation()}>
          <div className="bl-upgrade-icon">⭐</div>
          <h3>This is a Pro feature</h3>
          <p>{upgradeMessage}</p>
          <Link to={upgradeCta} className="bl-upgrade-btn" onClick={() => setUpgradeOpen(false)}>See Pro Plans</Link>
          <button className="bl-upgrade-dismiss" onClick={() => setUpgradeOpen(false)}>Not now</button>
        </div>
      </div>
    </div>
    </ThemeProvider>
  );
};

