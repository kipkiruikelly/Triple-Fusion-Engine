import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { Layers } from 'lucide-react';

interface StaticPageProps {
  pageIdOverride?: string;
}

export const StaticPage: React.FC<StaticPageProps> = ({ pageIdOverride }) => {
  const { pageId: paramPageId } = useParams();
  const pageId = pageIdOverride || paramPageId;
  const [content, setContent] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    const fetchContent = async () => {
      setLoading(true);
      try {
        const res = await fetch(`/api/content/${pageId}`);
        const data = await res.json();
        if (data.ok) {
          setContent(data.data);
          setError('');
        } else {
          setError('Content not found');
        }
      } catch (err) {
        setError('Network error');
      } finally {
        setLoading(false);
      }
    };
    fetchContent();
  }, [pageId]);

  return (
    <div className="bg-nexus-bg text-white font-sans min-h-screen relative overflow-x-hidden flex flex-col justify-between selection:bg-nexus-pur/30">
      
      {/* Auroras (Glowing background blobs) */}
      <div className="absolute top-[-100px] left-[-150px] w-[500px] h-[500px] rounded-full bg-nexus-pur/10 blur-[100px] pointer-events-none z-0" />
      <div className="absolute bottom-[200px] right-[-200px] w-[500px] h-[500px] rounded-full bg-nexus-blu/10 blur-[120px] pointer-events-none z-0" />

      {/* Navigation Header */}
      <nav className="sticky top-0 z-50 bg-nexus-bg/80 backdrop-blur-md border-b border-white/5 py-4 px-6 md:px-12 flex items-center justify-between z-10">
        <Link to="/" className="flex items-center gap-2 text-lg font-bold text-white tracking-tight">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-tr from-nexus-pur to-nexus-blu flex items-center justify-center text-white">
            <Layers size={18} />
          </div>
          <span className="gt font-extrabold">BullLogic</span>
        </Link>
        <Link to="/" className="text-xs text-gray-400 hover:text-white transition">
          ← Back to Site
        </Link>
      </nav>

      {/* Main Container */}
      <main className="flex-1 max-w-[800px] w-full mx-auto px-6 py-12 z-10">
        {loading ? (
          <div className="flex justify-center items-center py-24">
            <div className="w-8 h-8 border-4 border-nexus-pur border-t-transparent rounded-full animate-spin" />
          </div>
        ) : error ? (
          <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-xs rounded-xl p-4 text-center">
            {error}
          </div>
        ) : Array.isArray(content) ? (
          <div>
            <h2 className="text-2xl md:text-3xl font-bold capitalize text-white mb-8 tracking-tight">
              {pageId}
            </h2>
            <div className="flex flex-col gap-6">
              {content.map((item: any, i: number) => (
                <div key={i} className="bg-nexus-sf border border-white/5 rounded-2xl p-6 shadow-lg">
                  <h3 className="text-base font-bold text-white mb-3">
                    {item.question}
                  </h3>
                  <p className="text-xs text-gray-400 leading-relaxed font-normal">
                    {item.answer}
                  </p>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="bg-nexus-sf border border-white/5 rounded-[24px] p-6 md:p-10 shadow-2xl">
            <h2 className="text-2xl md:text-3xl font-extrabold text-white mb-6 tracking-tight">
              {content.title}
            </h2>
            <p className="text-xs text-gray-300 leading-relaxed font-normal whitespace-pre-wrap">
              {content.content}
            </p>
          </div>
        )}
      </main>

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
