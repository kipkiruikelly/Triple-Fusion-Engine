import React, { useState } from 'react';
import { useNavigate, Link, Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import toast from 'react-hot-toast';
import { Layers } from 'lucide-react';

export const LoginDashboard: React.FC = () => {
  const [identifier, setIdentifier] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const { checkAuth, user } = useAuth();
  const navigate = useNavigate();

  if (user) {
    return <Navigate to="/portfolio" replace />;
  }

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setErrorMsg('');
    try {
      const res = await fetch('/api/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ identifier, password }),
      });
      const data = await res.json();
      if (data.ok) {
        await checkAuth(); // refresh user context
        toast.success('Login successful');
        navigate('/portfolio');
      } else {
        setErrorMsg(data.error || 'Login failed');
        toast.error(data.error || 'Login failed');
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.error('[LoginDashboard] fetch error:', err);
      setErrorMsg(`Network error: ${msg}`);
      toast.error(`Network error: ${msg}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-nexus-bg text-white font-sans min-h-screen relative overflow-x-hidden flex flex-col justify-between selection:bg-nexus-pur/30">
      
      {/* Auroras (Glowing background blobs) */}
      <div className="absolute top-[-100px] left-[-150px] w-[500px] h-[500px] rounded-full bg-nexus-pur/10 blur-[100px] pointer-events-none z-0" />
      <div className="absolute bottom-[200px] right-[-200px] w-[500px] h-[500px] rounded-full bg-nexus-blu/10 blur-[120px] pointer-events-none z-0" />

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col justify-center items-center p-6 z-10">
        
        {/* Brand Logo */}
        <Link to="/" className="flex items-center gap-2 text-2xl font-bold text-white tracking-tight mb-8">
          <div className="w-9 h-9 rounded-lg bg-gradient-to-tr from-nexus-pur to-nexus-blu flex items-center justify-center text-white">
            <Layers size={20} />
          </div>
          <span className="gt font-extrabold">BullLogic</span>
        </Link>

        {/* Card Frame */}
        <div className="bg-nexus-sf border border-white/5 rounded-[24px] p-8 md:p-10 w-full max-w-[420px] shadow-2xl">
          <h2 className="text-xl md:text-2xl font-bold text-white mb-2 text-center">Welcome Back</h2>
          <p className="text-xs text-gray-400 text-center mb-8">Sign in to manage your algorithmic predictions.</p>

          {errorMsg && (
            <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-xs rounded-xl p-3 text-center mb-6">
              {errorMsg}
            </div>
          )}

          <form onSubmit={handleLogin} className="flex flex-col gap-4">
            <div>
              <label className="text-[10px] text-gray-500 font-bold block mb-2 uppercase tracking-wider">Username or email</label>
              <input
                type="text"
                autoFocus
                autoComplete="username"
                required
                value={identifier}
                onChange={(e) => setIdentifier(e.target.value)}
                className="w-full bg-nexus-bg border border-white/10 text-white rounded-xl p-3 text-xs focus:outline-none focus:border-nexus-pur transition"
              />
            </div>

            <div>
              <div className="flex justify-between items-center mb-2">
                <label className="text-[10px] text-gray-500 font-bold uppercase tracking-wider">Password</label>
                <Link to="/forgot-password" className="text-[10px] text-nexus-pur hover:underline">
                  Forgot password?
                </Link>
              </div>
              <input
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full bg-nexus-bg border border-white/10 text-white rounded-xl p-3 text-xs focus:outline-none focus:border-nexus-pur transition"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 bg-gradient-to-r from-nexus-pur to-nexus-blu hover:shadow-[0_8px_24px_rgba(139,92,246,0.3)] text-white font-bold text-xs rounded-xl transition duration-200 transform hover:-translate-y-0.5 cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed mt-2"
            >
              {loading ? 'Signing in...' : 'Sign In'}
            </button>

            <div className="flex items-center gap-4 my-2 text-xs text-gray-500">
              <div className="flex-1 h-[1px] bg-white/5" />
              <span>or</span>
              <div className="flex-1 h-[1px] bg-white/5" />
            </div>

            <a
              href="/auth/google"
              className="w-full py-3 bg-white border border-white/10 text-gray-900 font-bold text-xs rounded-xl hover:bg-gray-100 transition flex items-center justify-center gap-2 cursor-pointer"
            >
              <svg width="16" height="16" viewBox="0 0 48 48" className="flex-shrink-0">
                <path fill="#FFC107" d="M43.6 20.1H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.9 1.2 8 3l5.7-5.7C34.2 6.1 29.3 4 24 4 13 4 4 13 4 24s9 20 20 20 20-9 20-20c0-1.3-.1-2.6-.4-3.9z"/>
                <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.6 15.1 18.9 12 24 12c3.1 0 5.9 1.2 8 3l5.7-5.7C34.2 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"/>
                <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z"/>
                <path fill="#1976D2" d="M43.6 20.1H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C36.9 39.2 44 34 44 24c0-1.3-.1-2.6-.4-3.9z"/>
              </svg>
              Sign in with Google
            </a>
          </form>

          <div className="text-center mt-6 text-xs text-gray-500">
            Don't have an account?{' '}
            <Link to="/register" className="text-nexus-pur font-bold hover:underline">
              Register here
            </Link>
          </div>
        </div>

      </div>

      {/* Footer */}
      <footer className="py-6 border-t border-white/5 bg-nexus-bg/50 text-center text-[10px] text-gray-500 z-10">
        <div className="max-w-7xl mx-auto px-6 flex justify-center gap-6 flex-wrap">
          <Link to="/track-record" className="hover:text-white transition">Track Record</Link>
          <Link to="/faq" className="hover:text-white transition">FAQ</Link>
          <Link to="/privacy-policy" className="hover:text-white transition">Privacy</Link>
          <Link to="/terms" className="hover:text-white transition">Terms</Link>
          <Link to="/disclosures" className="hover:text-white transition">Disclosures</Link>
        </div>
      </footer>

    </div>
  );
};
