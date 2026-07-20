import React, { useState } from 'react';
import { useNavigate, Link, Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import toast from 'react-hot-toast';

export const RegisterDashboard: React.FC = () => {
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [agree, setAgree] = useState(false);
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const { checkAuth, user } = useAuth();
  const navigate = useNavigate();

  if (user) {
    return <Navigate to="/portfolio" replace />;
  }

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg('');

    if (password !== confirmPassword) {
      setErrorMsg('Passwords do not match.');
      toast.error('Passwords do not match.');
      return;
    }

    if (!agree) {
      setErrorMsg('You must agree to the Terms of Service and Privacy Policy.');
      toast.error('You must agree to the Terms.');
      return;
    }

    setLoading(true);
    try {
      const res = await fetch('/api/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ username, email, password }),
      });
      const data = await res.json();
      if (data.ok) {
        await checkAuth(); // refresh user context
        toast.success('Registration successful! Welcome to BullLogic.');
        navigate('/portfolio');
      } else {
        setErrorMsg(data.error || 'Registration failed');
        toast.error(data.error || 'Registration failed');
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.error('[RegisterDashboard] fetch error:', err);
      setErrorMsg(`Network error: ${msg}`);
      toast.error(`Network error: ${msg}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <style>{`
        .register-body {
          font-family: 'Inter', sans-serif;
          background: var(--bg);
          color: var(--text);
          min-height: 100vh;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
        }
        .register-main {
          flex: 1;
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 24px;
        }
        .register-box {
          background: var(--surface);
          border: 1px solid var(--border);
          border-radius: 16px;
          padding: 36px;
          width: min(420px, 94vw);
        }
        .register-logo {
          font-size: 17pt;
          font-weight: 700;
          color: var(--white);
          text-align: center;
        }
        .register-logo span {
          color: var(--accent);
        }
        .register-sub {
          color: var(--text-muted, var(--muted));
          font-size: 9.5pt;
          text-align: center;
          margin: 6px 0 24px;
        }
        .register-label {
          display: block;
          font-size: 8.5pt;
          font-weight: 600;
          color: var(--text-muted, var(--muted));
          margin: 13px 0 6px;
          text-transform: uppercase;
          letter-spacing: .4px;
        }
        .register-input {
          width: 100%;
          padding: 11px 13px;
          border-radius: 8px;
          border: 1px solid var(--border);
          background: var(--bg);
          color: var(--text);
          font-size: 10pt;
          font-family: inherit;
        }
        .register-input:focus {
          outline: none;
          border-color: var(--accent);
        }
        .register-btn {
          width: 100%;
          margin-top: 18px;
          padding: 12px;
          border-radius: 8px;
          border: none;
          background: var(--accent);
          color: #fff;
          font-weight: 700;
          font-size: 10.5pt;
          cursor: pointer;
          font-family: inherit;
        }
        .register-btn:hover {
          filter: brightness(1.08);
        }
        .register-btn:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }
        .register-gbtn {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 10px;
          width: 100%;
          padding: 11px;
          border-radius: 8px;
          border: 1px solid var(--border);
          background: #fff;
          color: #1a1a1a;
          font-weight: 600;
          font-size: 10pt;
          cursor: pointer;
          font-family: inherit;
          text-decoration: none;
          margin-bottom: 6px;
        }
        .register-gbtn:hover {
          background: #f2f2f2;
        }
        .register-divider {
          display: flex;
          align-items: center;
          gap: 12px;
          margin: 18px 0;
          color: var(--text-muted, var(--muted));
          font-size: 8.5pt;
        }
        .register-divider::before, .register-divider::after {
          content: "";
          flex: 1;
          height: 1px;
          background: var(--border);
        }
        .register-err {
          background: rgba(255,77,77,.1);
          border: 1px solid rgba(255,77,77,.4);
          color: #ef4444;
          border-radius: 8px;
          padding: 10px 13px;
          font-size: 9pt;
          margin-bottom: 8px;
          text-align: center;
        }
        .register-terms {
          display: flex;
          gap: 10px;
          align-items: flex-start;
          margin-top: 16px;
          font-size: 8.5pt;
          color: var(--text-muted, var(--muted));
          line-height: 1.5;
        }
        .register-terms input {
          margin-top: 2px;
        }
        .register-terms a {
          color: var(--accent);
          text-decoration: none;
        }
        .register-links {
          margin-top: 16px;
          text-align: center;
          font-size: 9pt;
          color: var(--text-muted, var(--muted));
        }
        .register-links a {
          color: var(--accent);
          text-decoration: none;
          font-weight: 600;
        }
        .register-footer {
          border-top: 1px solid var(--border);
          padding: 16px;
          text-align: center;
          font-size: 8.5pt;
          color: var(--text-muted, var(--muted));
          width: 100%;
        }
        .register-footer a {
          color: var(--text-muted, var(--muted));
          text-decoration: none;
          margin: 0 8px;
        }
        .register-footer a:hover {
          color: var(--text);
        }
      `}</style>

      <div className="register-body">
        <div className="register-main">
          <form className="register-box" onSubmit={handleRegister}>
            <div className="register-logo">Bull<span>Logic</span></div>
            <div className="register-sub">Create your account. 5 free predictions daily.</div>

            {errorMsg && <div className="register-err">{errorMsg}</div>}

            <a className="register-gbtn" href="/auth/google">
              <svg width="18" height="18" viewBox="0 0 48 48">
                <path fill="#FFC107" d="M43.6 20.1H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.9 1.2 8 3l5.7-5.7C34.2 6.1 29.3 4 24 4 13 4 4 13 4 24s9 20 20 20 20-9 20-20c0-1.3-.1-2.6-.4-3.9z"/>
                <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.6 15.1 18.9 12 24 12c3.1 0 5.9 1.2 8 3l5.7-5.7C34.2 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"/>
                <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z"/>
                <path fill="#1976D2" d="M43.6 20.1H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C36.9 39.2 44 34 44 24c0-1.3-.1-2.6-.4-3.9z"/>
              </svg>
              Continue with Google
            </a>
            
            <div className="register-divider">or register with email</div>

            <label className="register-label">Username</label>
            <input 
              className="register-input"
              type="text" 
              name="username" 
              autoComplete="username" 
              minLength={3} 
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />

            <label className="register-label">Email address</label>
            <input 
              className="register-input"
              type="email" 
              name="email" 
              autoComplete="email" 
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />

            <label className="register-label">Password (min 8 characters)</label>
            <input 
              className="register-input"
              type="password" 
              name="password" 
              autoComplete="new-password" 
              minLength={8} 
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />

            <label className="register-label">Confirm password</label>
            <input 
              className="register-input"
              type="password" 
              name="confirm" 
              autoComplete="new-password" 
              minLength={8} 
              required
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
            />

            <div className="register-terms">
              <input 
                type="checkbox" 
                name="agree_terms" 
                id="agree" 
                required
                checked={agree}
                onChange={(e) => setAgree(e.target.checked)}
              />
              <label htmlFor="agree" style={{ all: 'unset', cursor: 'pointer' }}>
                I agree to the <a href="/terms" target="_blank" rel="noreferrer">Terms of Service</a> and <a href="/privacy-policy" target="_blank" rel="noreferrer">Privacy Policy</a>, and I understand BullLogic provides information, not financial advice.
              </label>
            </div>

            <button className="register-btn" type="submit" disabled={loading}>
              {loading ? 'Creating account...' : 'Create account'}
            </button>
            <div className="register-links">Already registered? <Link to="/login">Sign in</Link></div>
          </form>
        </div>
        <footer className="register-footer">
          <Link to="/track-record">Track Record</Link> · <Link to="/faq">FAQ</Link> ·
          <Link to="/privacy-policy">Privacy</Link> · <Link to="/terms">Terms</Link> · <Link to="/disclosures">Disclosures</Link>
        </footer>
      </div>
    </>
  );
};

