import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { Layers } from 'lucide-react';
import toast from 'react-hot-toast';

export const ForgotPassword: React.FC = () => {
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      const res = await fetch('/api/forgot-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      });
      const data = await res.json();
      if (data.ok) {
        setSent(true);
        toast.success('Reset link sent to your email.');
      } else {
        toast.error(data.error || 'Failed to send reset link');
      }
    } catch (err) {
      toast.error('Network error. Please try again.');
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
          <h2 className="text-xl md:text-2xl font-bold text-white mb-2 text-center">Reset Password</h2>
          <p className="text-xs text-gray-400 text-center mb-8">Provide your registered email to request a reset token.</p>

          {sent ? (
            <div className="text-center">
              <p className="text-xs text-gray-300 leading-relaxed mb-6">
                If an account exists for <span className="font-bold text-white">{email}</span>, a password reset link has been dispatched to that inbox.
              </p>
              <Link to="/login" className="inline-block px-5 py-2.5 bg-gradient-to-r from-nexus-pur to-nexus-blu text-white font-bold text-xs rounded-xl hover:shadow-[0_8px_24px_rgba(139,92,246,0.3)] transition">
                Return to Login
              </Link>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="flex flex-col gap-4">
              <div>
                <label className="text-[10px] text-gray-500 font-bold block mb-2 uppercase tracking-wider">Email Address</label>
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="trader@example.com"
                  className="w-full bg-nexus-bg border border-white/10 text-white rounded-xl p-3 text-xs focus:outline-none focus:border-nexus-pur transition"
                />
              </div>

              <button
                type="submit"
                disabled={loading}
                className="w-full py-3 bg-gradient-to-r from-nexus-pur to-nexus-blu hover:shadow-[0_8px_24px_rgba(139,92,246,0.3)] text-white font-bold text-xs rounded-xl transition duration-200 transform hover:-translate-y-0.5 cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed"
              >
                {loading ? 'Sending link...' : 'Send Reset Link'}
              </button>
            </form>
          )}

          <div className="text-center mt-6 text-xs text-gray-500">
            Remember your password?{' '}
            <Link to="/login" className="text-nexus-pur font-bold hover:underline">
              Log in
            </Link>
          </div>
        </div>

      </div>

      {/* Footer */}
      <footer className="py-6 border-t border-white/5 bg-nexus-bg/50 text-center text-[10px] text-gray-500 z-10">
        <div className="max-w-7xl mx-auto px-6 flex justify-center gap-6">
          <Link to="/track-record" className="hover:text-white transition">Track Record</Link>
          <Link to="/faq" className="hover:text-white transition">FAQ</Link>
          <Link to="/privacy-policy" className="hover:text-white transition">Privacy</Link>
          <Link to="/terms" className="hover:text-white transition">Terms</Link>
        </div>
      </footer>

    </div>
  );
};
