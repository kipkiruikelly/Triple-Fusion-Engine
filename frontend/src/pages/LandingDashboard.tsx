import React, { useState } from 'react';
import { Link, Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { Play, ArrowRight, Cpu, TrendingUp, Zap, BarChart2, Check, HelpCircle, Layers, Activity } from 'lucide-react';

export const LandingDashboard: React.FC = () => {
  const { user, loading } = useAuth();
  const [activeTab, setActiveTab] = useState<'scan' | 'predict' | 'trade'>('scan');
  const [openFaq, setOpenFaq] = useState<number | null>(null);

  if (loading) {
    return <div className="min-h-screen bg-nexus-bg" />;
  }

  if (user) {
    return <Navigate to="/home" replace />;
  }

  const toggleFaq = (index: number) => {
    setOpenFaq(prev => (prev === index ? null : index));
  };

  const tickerItems = [
    { ticker: 'AAPL', price: '$193.07', change: '+1.05%', signal: 'BULL', isUp: true },
    { ticker: 'TSLA', price: '$248.91', change: '-2.15%', signal: 'BEAR', isUp: false },
    { ticker: 'NVDA', price: '$875.32', change: '+4.21%', signal: 'BULL', isUp: true },
    { ticker: 'MSFT', price: '$423.65', change: '+0.78%', signal: 'BULL', isUp: true },
    { ticker: 'META', price: '$502.84', change: '+2.88%', signal: 'BULL', isUp: true },
    { ticker: 'AMD', price: '$178.43', change: '-1.85%', signal: 'BEAR', isUp: false },
    { ticker: 'AMZN', price: '$180.05', change: '+1.12%', signal: 'BULL', isUp: true },
    { ticker: 'GOOGL', price: '$151.60', change: '+0.95%', signal: 'BULL', isUp: true }
  ];

  return (
    <div className="bg-nexus-bg text-white font-sans min-h-screen relative overflow-x-hidden selection:bg-nexus-pur/30">
      
      {/* CSS Animation for Ticker Marquee */}
      <style>{`
        @keyframes scroll-left {
          0%   { transform: translateX(0); }
          100% { transform: translateX(-50%); }
        }
        .animate-scroll {
          animation: scroll-left 30s linear infinite;
        }
      `}</style>

      {/* Auroras (Glowing background blobs) */}
      <div className="absolute top-[-100px] left-[-150px] w-[500px] h-[500px] rounded-full bg-nexus-pur/10 blur-[100px] pointer-events-none z-0" />
      <div className="absolute top-[300px] right-[-200px] w-[600px] h-[600px] rounded-full bg-nexus-blu/10 blur-[120px] pointer-events-none z-0" />
      <div className="absolute bottom-[400px] left-[10%] w-[500px] h-[500px] rounded-full bg-nexus-pur/5 blur-[100px] pointer-events-none z-0" />

      {/* Navigation */}
      <nav className="fixed top-0 left-0 right-0 z-50 bg-nexus-bg/85 backdrop-blur-md border-b border-white/5 py-4 px-6 md:px-12 flex items-center justify-between">
        <Link to="/" className="flex items-center gap-2 text-lg font-bold text-white tracking-tight">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-tr from-nexus-pur to-nexus-blu flex items-center justify-center text-white">
            <Layers size={18} />
          </div>
          <span className="gt font-extrabold">BullLogic</span>
        </Link>

        <div className="hidden md:flex items-center gap-8 text-sm font-semibold text-gray-400">
          <a href="#features" className="hover:text-white transition">Features</a>
          <a href="#how-it-works" className="hover:text-white transition">How It Works</a>
          <a href="#demo" className="hover:text-white transition">Platform</a>
          <a href="#pricing" className="hover:text-white transition">Pricing</a>
          <a href="#faq" className="hover:text-white transition">FAQ</a>
        </div>

        <div className="flex items-center gap-3">
          <Link to="/login" className="px-4 py-2 border border-white/10 rounded-xl text-sm font-medium hover:border-nexus-pur hover:bg-nexus-pur/5 transition text-gray-300 hover:text-white">
            Log in
          </Link>
          <Link to="/register" className="px-4 py-2 bg-gradient-to-r from-nexus-pur to-nexus-blu hover:shadow-[0_8px_24px_rgba(139,92,246,0.3)] text-white text-sm font-semibold rounded-xl transition duration-200 transform hover:-translate-y-0.5">
            Get Started
          </Link>
        </div>
      </nav>

      {/* Hero Section */}
      <section className="pt-32 pb-12 px-6 md:px-12 max-w-7xl mx-auto flex flex-col items-center text-center relative z-10">
        <div className="inline-flex items-center gap-2 bg-nexus-sf border border-white/5 px-3 py-1 rounded-full text-xs font-semibold text-nexus-pur mb-6 hover:border-nexus-pur/20 transition">
          <span className="w-2 h-2 rounded-full bg-nexus-pur animate-pulse" />
          Fusing Machine Learning with ICT concepts & execution
        </div>

        <h1 className="text-4xl md:text-6xl lg:text-7xl font-bold tracking-tight leading-[1.1] text-white">
          Institutional-Grade<br />
          <span className="gt">Trading analytics</span>
        </h1>

        <p className="text-gray-400 mt-6 max-w-2xl text-base md:text-lg lg:text-xl font-normal leading-relaxed">
          Predict market direction across stocks, ETFs, indices, and crypto using machine learning fused with liquidity concepts.
        </p>

        <div className="flex flex-col sm:flex-row items-center gap-4 mt-8">
          <Link to="/register" className="px-6 py-3.5 bg-gradient-to-r from-nexus-pur to-nexus-blu hover:shadow-[0_8px_24px_rgba(139,92,246,0.3)] text-white font-bold rounded-xl transition duration-200 transform hover:-translate-y-0.5 flex items-center gap-2">
            Start Trading Free <ArrowRight size={18} />
          </Link>
          <a href="#demo" className="px-6 py-3.5 border border-white/10 rounded-xl text-sm font-semibold hover:border-nexus-pur hover:bg-nexus-pur/5 transition text-gray-300 hover:text-white flex items-center gap-2">
            <Play size={16} className="text-nexus-pur" /> Watch Demo Platform
          </a>
        </div>

        {/* Hero stats */}
        <div className="mt-12 flex items-center justify-center gap-8 md:gap-12 flex-wrap text-left">
          <div>
            <div className="text-3xl font-extrabold text-white">10</div>
            <div className="text-xs text-gray-500 font-bold uppercase mt-1">Instruments Covered</div>
          </div>
          <div className="w-[1px] h-8 bg-white/10 hidden sm:block" />
          <div>
            <div className="text-3xl font-extrabold text-green-400">52.6%</div>
            <div className="text-xs text-gray-500 font-bold uppercase mt-1">Backtest Win Rate</div>
          </div>
          <div className="w-[1px] h-8 bg-white/10 hidden sm:block" />
          <div>
            <div className="text-3xl font-extrabold text-white">1.71<span className="text-gray-500 text-lg">×</span></div>
            <div className="text-xs text-gray-500 font-bold uppercase mt-1">Profit Factor</div>
          </div>
          <div className="w-[1px] h-8 bg-white/10 hidden sm:block" />
          <div>
            <div className="text-3xl font-extrabold text-white">3</div>
            <div className="text-xs text-gray-500 font-bold uppercase mt-1">Timeframes Supported</div>
          </div>
        </div>
      </section>

      {/* Ticker Strip */}
      <div className="bg-nexus-sf border-y border-white/5 py-3 overflow-hidden w-full relative z-10">
        <div className="flex w-max items-center gap-12 animate-scroll">
          {/* Double list for smooth infinite scrolling */}
          {[...tickerItems, ...tickerItems].map((item, idx) => (
            <div key={idx} className="flex items-center gap-3 text-xs">
              <span className="font-bold text-white">{item.ticker}</span>
              <span className="text-gray-400">{item.price}</span>
              <span className={`font-semibold ${item.isUp ? 'text-green-400' : 'text-red-400'}`}>
                {item.change}
              </span>
              <span className={`text-[9px] font-bold px-2 py-0.5 rounded ${
                item.isUp ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'
              }`}>
                {item.signal}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Mock Interactive App Dashboard & Signal Demo */}
      <section id="demo" className="py-20 px-6 md:px-12 max-w-6xl mx-auto relative z-10">
        <div className="bg-nexus-sf border border-white/5 rounded-[24px] shadow-2xl overflow-hidden">
          
          {/* Mock Browser Header */}
          <div className="bg-nexus-bg border-b border-white/5 py-3 px-4 flex items-center gap-2">
            <div className="flex items-center gap-1.5">
              <span className="w-3 h-3 rounded-full bg-red-500/80" />
              <span className="w-3 h-3 rounded-full bg-yellow-500/80" />
              <span className="w-3 h-3 rounded-full bg-green-500/80" />
            </div>
            <div className="mx-auto bg-nexus-sf text-[11px] text-gray-400 py-1 px-8 rounded-lg w-full max-w-sm text-center border border-white/5">
              bulllogic.ai/console/dashboard
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-4 min-h-[500px]">
            {/* Sidebar */}
            <div className="bg-nexus-bg/50 p-6 border-r border-white/5 flex flex-col gap-4">
              <div className="text-xs font-bold text-gray-500 uppercase tracking-widest px-2 mb-2">Platform Overview</div>
              <button 
                onClick={() => setActiveTab('scan')} 
                className={`w-full py-2.5 px-4 rounded-xl text-left text-xs font-bold flex items-center gap-2 transition ${
                  activeTab === 'scan' ? 'bg-nexus-pur/10 text-white border-l-4 border-nexus-pur' : 'text-gray-400 hover:text-white hover:bg-white/5'
                }`}
              >
                <Cpu size={14} /> AI Movers Scanner
              </button>
              <button 
                onClick={() => setActiveTab('predict')} 
                className={`w-full py-2.5 px-4 rounded-xl text-left text-xs font-bold flex items-center gap-2 transition ${
                  activeTab === 'predict' ? 'bg-nexus-pur/10 text-white border-l-4 border-nexus-pur' : 'text-gray-400 hover:text-white hover:bg-white/5'
                }`}
              >
                <TrendingUp size={14} /> Neural Predictions
              </button>
              <button 
                onClick={() => setActiveTab('trade')} 
                className={`w-full py-2.5 px-4 rounded-xl text-left text-xs font-bold flex items-center gap-2 transition ${
                  activeTab === 'trade' ? 'bg-nexus-pur/10 text-white border-l-4 border-nexus-pur' : 'text-gray-400 hover:text-white hover:bg-white/5'
                }`}
              >
                <Zap size={14} /> MT5 Algo Bots
              </button>
            </div>

            {/* Dashboard Content */}
            <div className="lg:col-span-3 p-6 flex flex-col gap-6">
              {activeTab === 'scan' && (
                <div className="flex flex-col gap-4">
                  <div className="flex justify-between items-center">
                    <div>
                      <h3 className="text-lg font-bold text-white">AI Movers Scanner</h3>
                      <p className="text-xs text-gray-400">Movers flagged by sentiment & technical indices</p>
                    </div>
                    <span className="text-[10px] bg-green-500/10 text-green-400 px-2 py-0.5 rounded font-bold uppercase">Live Scanning</span>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div className="bg-nexus-bg p-4 rounded-xl border border-white/5">
                      <div className="text-[10px] text-gray-400 font-bold uppercase mb-1">NVDA</div>
                      <div className="text-lg font-bold text-white">$875.32</div>
                      <div className="text-xs text-green-400 mt-1 font-semibold">+4.21% Sentiment High</div>
                    </div>
                    <div className="bg-nexus-bg p-4 rounded-xl border border-white/5">
                      <div className="text-[10px] text-gray-400 font-bold uppercase mb-1">TSLA</div>
                      <div className="text-lg font-bold text-white">$248.91</div>
                      <div className="text-xs text-red-400 mt-1 font-semibold">-2.15% Short Signal</div>
                    </div>
                    <div className="bg-nexus-bg p-4 rounded-xl border border-white/5">
                      <div className="text-[10px] text-gray-400 font-bold uppercase mb-1">AAPL</div>
                      <div className="text-lg font-bold text-white">$193.07</div>
                      <div className="text-xs text-green-400 mt-1 font-semibold">+1.05% Consolidation Break</div>
                    </div>
                  </div>
                </div>
              )}

              {activeTab === 'predict' && (
                <div className="flex flex-col gap-4">
                  <div className="flex justify-between items-center">
                    <div>
                      <h3 className="text-lg font-bold text-white">Neural Signal Output</h3>
                      <p className="text-xs text-gray-400">Deep learning predictions outputting high-prob signals</p>
                    </div>
                    <span className="text-[10px] bg-green-500/10 text-green-400 px-2.5 py-0.5 rounded font-bold border border-green-500/20">BULLISH</span>
                  </div>

                  <div className="bg-nexus-bg rounded-xl border border-white/5 p-4 flex flex-col gap-3">
                    <div className="flex justify-between items-center text-xs pb-2 border-b border-white/5">
                      <span className="text-gray-400">Target Asset</span>
                      <span className="font-bold text-white">AAPL (Apple Inc.)</span>
                    </div>
                    <div className="grid grid-cols-2 gap-4 text-xs">
                      <div>
                        <div className="text-gray-500">Entry Range</div>
                        <div className="font-semibold text-white">$192.50 - $193.10</div>
                      </div>
                      <div>
                        <div className="text-gray-500">ICT Order Block</div>
                        <div className="font-semibold text-nexus-pur">$191.80 Support</div>
                      </div>
                      <div>
                        <div className="text-gray-500">Take Profit</div>
                        <div className="font-semibold text-green-400">$198.50</div>
                      </div>
                      <div>
                        <div className="text-gray-500">Stop Loss</div>
                        <div className="font-semibold text-red-400">$189.90</div>
                      </div>
                    </div>

                    <div className="mt-2">
                      <div className="flex justify-between text-[10px] text-gray-400 mb-1">
                        <span>Confidence Score</span>
                        <span className="text-green-400 font-bold">92.4%</span>
                      </div>
                      <div className="h-1.5 bg-nexus-sf rounded-full overflow-hidden w-full">
                        <div className="h-full bg-gradient-to-r from-nexus-pur to-green-400 rounded-full" style={{ width: '92.4%' }} />
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {activeTab === 'trade' && (
                <div className="flex flex-col gap-4">
                  <div className="flex justify-between items-center">
                    <div>
                      <h3 className="text-lg font-bold text-white">MT5 Algo Bots</h3>
                      <p className="text-xs text-gray-400">Manage algorithmic executors bound to MT5 terminal</p>
                    </div>
                    <span className="text-[10px] bg-nexus-blu/20 text-nexus-blu px-2.5 py-0.5 rounded-full font-bold">Execution Engine</span>
                  </div>

                  <div className="p-4 bg-nexus-bg rounded-xl border border-white/5 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-full bg-nexus-pur/10 flex items-center justify-center text-nexus-pur font-bold">
                        B1
                      </div>
                      <div>
                        <div className="text-xs font-bold text-white">Momentum breakout Bot</div>
                        <div className="text-[10px] text-gray-400">MT5 Server Connection: Active</div>
                      </div>
                    </div>
                    <button className="px-3 py-1.5 bg-gradient-to-r from-nexus-pur to-nexus-blu text-white text-xs font-bold rounded-lg hover:shadow-lg transition">
                      Running
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </section>

      {/* Steps Section: How It Works */}
      <section id="how-it-works" className="py-20 bg-nexus-bg2/40 border-y border-white/5 relative z-10">
        <div className="max-w-7xl mx-auto px-6 md:px-12">
          <div className="text-center max-w-xl mx-auto mb-16">
            <div className="text-xs font-bold uppercase tracking-wider text-nexus-pur mb-3">Workflow Pipeline</div>
            <h2 className="text-3xl md:text-4xl font-bold text-white">How it Works</h2>
            <p className="text-gray-400 mt-3 text-sm">Our automated system tracks sentiment, runs neural evaluations, and trades on autopilot.</p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-4 gap-8 md:gap-4 relative">
            <div className="absolute top-[28px] left-[15%] right-[15%] h-[1px] bg-gradient-to-r from-white/5 via-nexus-pur to-white/5 hidden md:block" />
            
            {/* Step 1 */}
            <div className="text-center flex flex-col items-center relative z-10">
              <div className="w-14 h-14 rounded-full bg-nexus-sf border border-white/10 text-nexus-pur flex items-center justify-center font-extrabold text-lg mb-4 shadow-md">
                01
              </div>
              <h4 className="font-bold text-white text-sm mb-2">Scan & Detect</h4>
              <p className="text-gray-400 text-xs px-4">Continuous scanner queries global indices, flagging high-volume assets.</p>
            </div>

            {/* Step 2 */}
            <div className="text-center flex flex-col items-center relative z-10">
              <div className="w-14 h-14 rounded-full bg-nexus-sf border border-white/10 text-nexus-pur flex items-center justify-center font-extrabold text-lg mb-4 shadow-md">
                02
              </div>
              <h4 className="font-bold text-white text-sm mb-2">Neural Assessment</h4>
              <p className="text-gray-400 text-xs px-4">Runs neural array checks, analyzing historical chart patterns.</p>
            </div>

            {/* Step 3 */}
            <div className="text-center flex flex-col items-center relative z-10">
              <div className="w-14 h-14 rounded-full bg-nexus-sf border border-white/10 text-nexus-pur flex items-center justify-center font-extrabold text-lg mb-4 shadow-md">
                03
              </div>
              <h4 className="font-bold text-white text-sm mb-2">Liquidity Verification</h4>
              <p className="text-gray-400 text-xs px-4">Fuses order blocks and ICT concepts to verify trade validity.</p>
            </div>

            {/* Step 4 */}
            <div className="text-center flex flex-col items-center relative z-10">
              <div className="w-14 h-14 rounded-full bg-nexus-sf border border-white/10 text-nexus-pur flex items-center justify-center font-extrabold text-lg mb-4 shadow-md">
                04
              </div>
              <h4 className="font-bold text-white text-sm mb-2">Autopilot Execution</h4>
              <p className="text-gray-400 text-xs px-4">Instantly routes execution orders to linked MetaTrader 5 accounts.</p>
            </div>

          </div>
        </div>
      </section>

      {/* Features Grid & Checklists */}
      <section id="features" className="py-20 px-6 md:px-12 max-w-7xl mx-auto relative z-10">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 items-center">
          
          <div>
            <div className="text-xs font-bold uppercase tracking-wider text-nexus-pur mb-3">Platform Features</div>
            <h2 className="text-3xl md:text-4xl font-bold text-white">Engineered for Automated Accuracy</h2>
            <p className="text-gray-400 mt-4 text-sm leading-relaxed">
              We leverage machine learning directly alongside traditional execution models. By integrating ICT liquidity indices, BullLogic captures structural turns ahead of retail chart tools.
            </p>

            <ul className="mt-8 flex flex-col gap-4">
              <li className="flex items-start gap-3 text-xs text-gray-300">
                <div className="w-5 h-5 rounded-full bg-nexus-pur/10 text-nexus-pur flex items-center justify-center flex-shrink-0 mt-0.5">
                  <Check size={12} />
                </div>
                <div>
                  <span className="font-bold text-white block">Institutional-grade ML models</span>
                  Trained on multi-year ticks, volume changes, and pattern arrays.
                </div>
              </li>
              <li className="flex items-start gap-3 text-xs text-gray-300">
                <div className="w-5 h-5 rounded-full bg-nexus-pur/10 text-nexus-pur flex items-center justify-center flex-shrink-0 mt-0.5">
                  <Check size={12} />
                </div>
                <div>
                  <span className="font-bold text-white block">MetaTrader 5 algorithmic execution</span>
                  Split-second order execution with custom stop-loss/take-profit boundaries.
                </div>
              </li>
              <li className="flex items-start gap-3 text-xs text-gray-300">
                <div className="w-5 h-5 rounded-full bg-nexus-pur/10 text-nexus-pur flex items-center justify-center flex-shrink-0 mt-0.5">
                  <Check size={12} />
                </div>
                <div>
                  <span className="font-bold text-white block">ICT order blocks & liquidity concepts</span>
                  Fuses institutional order blocks, fair value gaps, and liquidity sweeps.
                </div>
              </li>
            </ul>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
            <div className="p-6 rounded-2xl bg-nexus-sf border border-white/5 hover:border-nexus-pur/20 transition group">
              <div className="w-10 h-10 rounded-xl bg-nexus-pur/10 text-nexus-pur flex items-center justify-center mb-4 group-hover:scale-105 transition">
                <Cpu size={20} />
              </div>
              <h4 className="font-bold text-white text-sm">Deep Learning Scanner</h4>
              <p className="text-gray-400 text-xs mt-2 leading-relaxed">
                Flags structural breakouts across stocks and indexes.
              </p>
            </div>

            <div className="p-6 rounded-2xl bg-nexus-sf border border-white/5 hover:border-nexus-pur/20 transition group">
              <div className="w-10 h-10 rounded-xl bg-nexus-pur/10 text-nexus-pur flex items-center justify-center mb-4 group-hover:scale-105 transition">
                <Zap size={20} />
              </div>
              <h4 className="font-bold text-white text-sm">Autopilot Bots</h4>
              <p className="text-gray-400 text-xs mt-2 leading-relaxed">
                Runs trading strategies connected to live accounts.
              </p>
            </div>

            <div className="p-6 rounded-2xl bg-nexus-sf border border-white/5 hover:border-nexus-pur/20 transition group">
              <div className="w-10 h-10 rounded-xl bg-nexus-pur/10 text-nexus-pur flex items-center justify-center mb-4 group-hover:scale-105 transition">
                <BarChart2 size={20} />
              </div>
              <h4 className="font-bold text-white text-sm">Sentiment Scanners</h4>
              <p className="text-gray-400 text-xs mt-2 leading-relaxed">
                Indexes news and forums to capture social momentum.
              </p>
            </div>

            <div className="p-6 rounded-2xl bg-nexus-sf border border-white/5 hover:border-nexus-pur/20 transition group">
              <div className="w-10 h-10 rounded-xl bg-nexus-pur/10 text-nexus-pur flex items-center justify-center mb-4 group-hover:scale-105 transition">
                <Activity size={20} />
              </div>
              <h4 className="font-bold text-white text-sm">Accuracy Track</h4>
              <p className="text-gray-400 text-xs mt-2 leading-relaxed">
                Transparent verification of all historical signal records.
              </p>
            </div>
          </div>

        </div>
      </section>

      {/* Pricing Matrix */}
      <section id="pricing" className="py-20 bg-nexus-bg2/40 border-y border-white/5 relative z-10">
        <div className="max-w-7xl mx-auto px-6 md:px-12">
          <div className="text-center max-w-xl mx-auto mb-16">
            <div className="text-xs font-bold uppercase tracking-wider text-nexus-pur mb-3">Subscription plans</div>
            <h2 className="text-3xl md:text-4xl font-bold text-white">Choose Your Trading Tier</h2>
            <p className="text-gray-400 mt-3 text-sm">Flexible levels built for starting traders and algorithmic institutions alike.</p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 max-w-5xl mx-auto">
            {/* Free */}
            <div className="p-8 rounded-3xl bg-nexus-sf border border-white/5 flex flex-col gap-6 hover:scale-[1.02] transition duration-300">
              <div>
                <h4 className="text-sm font-bold text-gray-400 uppercase">Free Tier</h4>
                <div className="text-3xl font-extrabold text-white mt-2">$0</div>
                <p className="text-xs text-gray-500 mt-1">Start out, scan indices, verify signals</p>
              </div>
              <ul className="flex flex-col gap-3 text-xs text-gray-300">
                <li className="flex items-center gap-2"><Check size={14} className="text-nexus-pur" /> 5 daily neural predictions</li>
                <li className="flex items-center gap-2"><Check size={14} className="text-nexus-pur" /> Market overview dashboard</li>
                <li className="flex items-center gap-2"><Check size={14} className="text-nexus-pur" /> Basic user profile</li>
              </ul>
              <Link to="/register" className="w-full py-2.5 bg-white/5 border border-white/10 text-white text-center font-bold text-xs rounded-xl hover:bg-white/10 transition mt-auto">
                Get Started
              </Link>
            </div>

            {/* Pro */}
            <div className="p-8 rounded-3xl bg-nexus-sf border-2 border-nexus-pur flex flex-col gap-6 relative hover:scale-[1.02] transition duration-300 shadow-[0_12px_40px_rgba(139,92,246,0.15)]">
              <span className="absolute top-0 right-8 transform -translate-y-1/2 bg-gradient-to-r from-nexus-pur to-nexus-blu text-white text-[10px] font-bold uppercase tracking-wider px-3 py-1 rounded-full">
                Most Popular
              </span>
              <div>
                <h4 className="text-sm font-bold text-nexus-pur uppercase">Pro Tier</h4>
                <div className="text-3xl font-extrabold text-white mt-2">$29<span className="text-xs font-normal text-gray-400">/mo</span></div>
                <p className="text-xs text-gray-400 mt-1">Advanced machine learning stock scanners</p>
              </div>
              <ul className="flex flex-col gap-3 text-xs text-gray-200">
                <li className="flex items-center gap-2"><Check size={14} className="text-nexus-pur" /> Unlimited daily predictions</li>
                <li className="flex items-center gap-2"><Check size={14} className="text-nexus-pur" /> Live MT5 algo execution</li>
                <li className="flex items-center gap-2"><Check size={14} className="text-nexus-pur" /> Sentiment analyzer logs</li>
                <li className="flex items-center gap-2"><Check size={14} className="text-nexus-pur" /> Custom watchlists & alerts</li>
              </ul>
              <Link to="/register" className="w-full py-2.5 bg-gradient-to-r from-nexus-pur to-nexus-blu text-white text-center font-bold text-xs rounded-xl hover:shadow-lg transition mt-auto">
                Start Pro Free Trial
              </Link>
            </div>

            {/* Enterprise */}
            <div className="p-8 rounded-3xl bg-nexus-sf border border-white/5 flex flex-col gap-6 hover:scale-[1.02] transition duration-300">
              <div>
                <h4 className="text-sm font-bold text-gray-400 uppercase">Enterprise</h4>
                <div className="text-3xl font-extrabold text-white mt-2">$99<span className="text-xs font-normal text-gray-400">/mo</span></div>
                <p className="text-xs text-gray-500 mt-1">Institutional pipelines and API endpoints</p>
              </div>
              <ul className="flex flex-col gap-3 text-xs text-gray-300">
                <li className="flex items-center gap-2"><Check size={14} className="text-nexus-pur" /> Everything in Pro tier</li>
                <li className="flex items-center gap-2"><Check size={14} className="text-nexus-pur" /> Direct API access limits</li>
                <li className="flex items-center gap-2"><Check size={14} className="text-nexus-pur" /> Multi-bot parallel routing</li>
                <li className="flex items-center gap-2"><Check size={14} className="text-nexus-pur" /> Dedicated support representative</li>
              </ul>
              <Link to="/register" className="w-full py-2.5 bg-white/5 border border-white/10 text-white text-center font-bold text-xs rounded-xl hover:bg-white/10 transition mt-auto">
                Contact Enterprise
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* FAQ accordion */}
      <section id="faq" className="py-20 px-6 md:px-12 max-w-4xl mx-auto relative z-10">
        <div className="text-center mb-12">
          <div className="text-xs font-bold uppercase tracking-wider text-nexus-pur mb-3 flex items-center justify-center gap-1">
            <HelpCircle size={14} /> Common Questions
          </div>
          <h2 className="text-3xl font-bold text-white">Frequently Asked Questions</h2>
        </div>

        <div className="flex flex-col gap-4">
          {[
            {
              q: "How accurate are the neural predictions?",
              a: "Our deep learning models compile historical price indicators, volumes, and sentiment arrays to output directional confidence rates. Standard model accuracy indexes around 78% on major indexes."
            },
            {
              q: "Is it safe to link my MT5 account?",
              a: "Absolutely. BullLogic connects to MetaTrader via official local terminal integrations. We store no credentials on public cloud nodes; execution orders are routed strictly via secure local middleware."
            },
            {
              q: "What payment systems do you support?",
              a: "We support major credit cards via Stripe, alongside regional M-Pesa automated billing flows."
            }
          ].map((faq, idx) => (
            <div key={idx} className="p-5 rounded-2xl bg-nexus-sf border border-white/5 flex flex-col gap-3 transition">
              <button 
                onClick={() => toggleFaq(idx)} 
                className="w-full text-left font-bold text-white text-sm flex items-center justify-between focus:outline-none"
              >
                <span>{faq.q}</span>
                <span className={`text-nexus-pur transition-transform duration-200 transform ${openFaq === idx ? 'rotate-180' : ''}`}>
                  ▼
                </span>
              </button>
              {openFaq === idx && (
                <p className="text-xs text-gray-400 leading-relaxed transition-all">
                  {faq.a}
                </p>
              )}
            </div>
          ))}
        </div>
      </section>

      {/* Footer */}
      <footer className="py-12 border-t border-white/5 bg-nexus-bg text-center relative z-10">
        <div className="max-w-7xl mx-auto px-6 md:px-12 flex flex-col md:flex-row items-center justify-between gap-6">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded bg-gradient-to-tr from-nexus-pur to-nexus-blu flex items-center justify-center text-white text-xs font-bold">
              B
            </div>
            <span className="text-sm font-extrabold text-white tracking-tight">BullLogic</span>
          </div>

          <p className="text-xs text-gray-500">
            &copy; {new Date().getFullYear()} BullLogic Systems. Cover under MIT License. All rights reserved.
          </p>

          <div className="flex gap-4 text-xs text-gray-400">
            <Link to="/login" className="hover:text-white transition">Platform App</Link>
            <Link to="/register" className="hover:text-white transition">Get Started</Link>
          </div>
        </div>
      </footer>

    </div>
  );
};
