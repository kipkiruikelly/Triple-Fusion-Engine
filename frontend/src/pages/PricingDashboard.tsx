import React, { useState } from 'react';
import { Check, CreditCard, Phone, Mail, HelpCircle, Loader2 } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { apiFetch } from '../utils/api';
import toast from 'react-hot-toast';

export const PricingDashboard: React.FC = () => {
  const { user, checkAuth } = useAuth();
  const [billingMode, setBillingMode] = useState<'monthly' | 'annual'>('monthly');
  const [loadingTier, setLoadingTier] = useState<string | null>(null);
  const [mpesaModal, setMpesaModal] = useState<{ open: boolean; tier: string; amount: number } | null>(null);
  const [mpesaPhone, setMpesaPhone] = useState('');
  const [mpesaLoading, setMpesaLoading] = useState(false);
  const [openFaq, setOpenFaq] = useState<number | null>(null);
  const [giftCode, setGiftCode] = useState('');
  const [redeemingGift, setRedeemingGift] = useState(false);

  const handleRedeemGift = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!giftCode) {
      toast.error('Please enter a gift code');
      return;
    }
    setRedeemingGift(true);
    try {
      const res = await apiFetch('/api/gift/redeem', {
        method: 'POST',
        body: { code: giftCode.trim().toUpperCase() }
      });
      if (res.ok) {
        toast.success(`Redeemed code successfully! Plan is now ${res.plan}`);
        setGiftCode('');
        await checkAuth(); // Refresh user profile status
      } else {
        toast.error(res.error || 'Invalid or expired gift code');
      }
    } catch (err) {
      toast.error('Network error during redemption');
    } finally {
      setRedeemingGift(false);
    }
  };

  // Price calculations
  const prices = {
    plus: billingMode === 'monthly' ? 12 : 8,
    pro: billingMode === 'monthly' ? 29 : 19,
    enterprise: 999,
  };

  const kesRates = {
    plus: billingMode === 'monthly' ? 1600 : 12800, // Annual billed at once
    pro: billingMode === 'monthly' ? 3900 : 30000,
  };

  const handleStripeCheckout = async (tier: string) => {
    setLoadingTier(tier);
    try {
      const res = await apiFetch('/api/stripe/checkout', {
        method: 'POST',
        body: { tier, billing_mode: billingMode }
      });
      if (res.ok) {
        toast.success(res.message || `Upgraded to ${tier.toUpperCase()} successfully!`);
        await checkAuth(); // Refresh user profile
      } else {
        toast.error(res.error || 'Checkout failed');
      }
    } catch (err) {
      toast.error('Network error during checkout');
    } finally {
      setLoadingTier(null);
    }
  };

  const handleOpenMpesa = (tier: string) => {
    const amount = tier === 'plus' ? kesRates.plus : kesRates.pro;
    setMpesaModal({ open: true, tier, amount });
  };

  const handleSubmitMpesa = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!mpesaPhone || !mpesaPhone.startsWith('07') && !mpesaPhone.startsWith('01') && !mpesaPhone.startsWith('254')) {
      toast.error('Please enter a valid Safaricom phone number (e.g. 0712345678)');
      return;
    }

    setMpesaLoading(true);
    try {
      const res = await apiFetch('/api/mpesa/pay', {
        method: 'POST',
        body: {
          phone: mpesaPhone,
          tier: mpesaModal?.tier,
          billing_mode: billingMode,
        }
      });
      if (res.ok) {
        toast.success(res.message || 'M-Pesa payment processed successfully!');
        setMpesaModal(null);
        await checkAuth(); // Refresh user profile
      } else {
        toast.error(res.error || 'Payment failed');
      }
    } catch (err) {
      toast.error('Network error processing payment');
    } finally {
      setMpesaLoading(false);
    }
  };

  const currentPlan = user?.plan || 'free';

  const isCurrent = (tier: string) => {
    if (currentPlan === tier) return true;
    if (tier === 'free' && !['plus', 'pro', 'enterprise'].includes(currentPlan)) return true;
    return false;
  };

  return (
    <div className="flex-1 overflow-y-auto px-4 md:px-12 py-8 bg-[#0b0c10] text-gray-200">
      {/* Header */}
      <div className="text-center max-w-2xl mx-auto mb-12">
        <div className="text-xs font-bold uppercase tracking-widest text-[#8b5cf6] mb-3">Pricing Matrix</div>
        <h1 className="text-3xl md:text-5xl font-extrabold text-white tracking-tight">Institutional signals. Individual pricing.</h1>
        <p className="text-gray-400 mt-4 text-sm md:text-base leading-relaxed">
          ML price predictions across 76+ tickers and 8 timeframes, fused with ICT market structure analysis.
        </p>
      </div>

      {/* Toggle wrap */}
      <div className="flex justify-center items-center gap-4 mb-12">
        <div className="bg-[#16181d] border border-white/5 p-1 rounded-xl flex">
          <button
            onClick={() => setBillingMode('monthly')}
            className={`px-6 py-2 rounded-lg text-xs font-bold transition-all ${
              billingMode === 'monthly' ? 'bg-[#8b5cf6] text-white' : 'text-gray-400 hover:text-white'
            }`}
          >
            Monthly
          </button>
          <button
            onClick={() => setBillingMode('annual')}
            className={`px-6 py-2 rounded-lg text-xs font-bold transition-all flex items-center gap-2 ${
              billingMode === 'annual' ? 'bg-[#8b5cf6] text-white' : 'text-gray-400 hover:text-white'
            }`}
          >
            Annual
            <span className="bg-emerald-500/20 text-emerald-400 text-[10px] px-2 py-0.5 rounded-full font-extrabold">
              Save 43%
            </span>
          </button>
        </div>
      </div>

      {/* Pricing Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6 max-w-6xl mx-auto mb-16">
        
        {/* Starter (Free) */}
        <div className="p-8 rounded-3xl bg-[#16181d] border border-white/5 flex flex-col gap-6 hover:scale-[1.01] transition-transform duration-300">
          <div>
            <h4 className="text-xs font-bold text-gray-400 uppercase tracking-wider">Starter</h4>
            <div className="text-3xl font-extrabold text-white mt-2">$0</div>
            <p className="text-xs text-gray-500 mt-1">Start out, scan indices, verify signals</p>
          </div>
          <ul className="flex flex-col gap-3 text-xs text-gray-300">
            <li className="flex items-center gap-2"><Check size={14} className="text-[#8b5cf6] shrink-0" /> 5 daily neural predictions</li>
            <li className="flex items-center gap-2"><Check size={14} className="text-[#8b5cf6] shrink-0" /> Market overview dashboard</li>
            <li className="flex items-center gap-2"><Check size={14} className="text-[#8b5cf6] shrink-0" /> Basic watchlists & alerts</li>
            <li className="flex items-center gap-2 text-gray-500"><span className="shrink-0">-</span> No multi-timeframe confluence</li>
            <li className="flex items-center gap-2 text-gray-500"><span className="shrink-0">-</span> No broker integration</li>
          </ul>
          {isCurrent('free') ? (
            <span className="w-full py-2.5 bg-white/5 border border-white/10 text-gray-400 text-center font-bold text-xs rounded-xl mt-auto">
              Current Plan
            </span>
          ) : (
            <button disabled className="w-full py-2.5 bg-white/5 border border-white/10 text-gray-500 text-center font-bold text-xs rounded-xl mt-auto cursor-not-allowed">
              Starter
            </button>
          )}
        </div>

        {/* Plus */}
        <div className="p-8 rounded-3xl bg-[#16181d] border border-white/5 flex flex-col gap-6 hover:scale-[1.01] transition-transform duration-300">
          <div>
            <h4 className="text-xs font-bold text-gray-400 uppercase tracking-wider">Plus</h4>
            <div className="text-3xl font-extrabold text-white mt-2">
              ${prices.plus}
              <span className="text-xs font-normal text-gray-400">/mo</span>
            </div>
            <p className="text-xs text-gray-500 mt-1">
              {billingMode === 'annual' ? 'Billed $96 annually' : 'Cancel subscription anytime'}
            </p>
          </div>
          <ul className="flex flex-col gap-3 text-xs text-gray-300">
            <li className="flex items-center gap-2"><Check size={14} className="text-[#8b5cf6] shrink-0" /> Everything in Starter</li>
            <li className="flex items-center gap-2"><Check size={14} className="text-[#8b5cf6] shrink-0" /> Unlimited predictions</li>
            <li className="flex items-center gap-2"><Check size={14} className="text-[#8b5cf6] shrink-0" /> Multi-timeframe confluence</li>
            <li className="flex items-center gap-2"><Check size={14} className="text-[#8b5cf6] shrink-0" /> Backtester (1 run/day)</li>
            <li className="flex items-center gap-2"><Check size={14} className="text-[#8b5cf6] shrink-0" /> Priority email support</li>
          </ul>
          {isCurrent('plus') ? (
            <span className="w-full py-2.5 bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-center font-bold text-xs rounded-xl mt-auto">
              Current Plan ✓
            </span>
          ) : (
            <div className="flex flex-col gap-2 mt-auto">
              <button
                disabled={loadingTier !== null}
                onClick={() => handleStripeCheckout('plus')}
                className="w-full py-2 bg-[#8b5cf6] text-white font-bold text-xs rounded-xl hover:bg-[#7c3aed] transition flex items-center justify-center gap-1.5"
              >
                {loadingTier === 'plus' ? <Loader2 size={12} className="animate-spin" /> : <CreditCard size={12} />}
                Pay with Card
              </button>
              <button
                onClick={() => handleOpenMpesa('plus')}
                className="w-full py-2 bg-emerald-600 text-white font-bold text-xs rounded-xl hover:bg-emerald-700 transition flex items-center justify-center gap-1.5"
              >
                <Phone size={12} />
                Pay with M-Pesa
              </button>
            </div>
          )}
        </div>

        {/* Pro */}
        <div className="p-8 rounded-3xl bg-[#16181d] border-2 border-[#8b5cf6] flex flex-col gap-6 relative hover:scale-[1.01] transition-transform duration-300 shadow-[0_12px_40px_rgba(139,92,246,0.15)]">
          <span className="absolute top-0 right-8 transform -translate-y-1/2 bg-gradient-to-r from-[#8b5cf6] to-[#3b82f6] text-white text-[9px] font-bold uppercase tracking-wider px-3 py-1 rounded-full">
            Most Popular
          </span>
          <div>
            <h4 className="text-xs font-bold text-[#8b5cf6] uppercase tracking-wider">Pro</h4>
            <div className="text-3xl font-extrabold text-white mt-2">
              ${prices.pro}
              <span className="text-xs font-normal text-gray-400">/mo</span>
            </div>
            <p className="text-xs text-gray-400 mt-1">
              {billingMode === 'annual' ? 'Billed $228 annually' : 'Cancel subscription anytime'}
            </p>
          </div>
          <ul className="flex flex-col gap-3 text-xs text-gray-200">
            <li className="flex items-center gap-2"><Check size={14} className="text-[#8b5cf6] shrink-0" /> Everything in Plus</li>
            <li className="flex items-center gap-2"><Check size={14} className="text-[#8b5cf6] shrink-0" /> Unlimited backtester</li>
            <li className="flex items-center gap-2"><Check size={14} className="text-[#8b5cf6] shrink-0" /> REST API access (5 keys)</li>
            <li className="flex items-center gap-2"><Check size={14} className="text-[#8b5cf6] shrink-0" /> MT5 broker connectivity</li>
            <li className="flex items-center gap-2"><Check size={14} className="text-[#8b5cf6] shrink-0" /> Quick-Trade panel integration</li>
          </ul>
          {isCurrent('pro') ? (
            <span className="w-full py-2.5 bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-center font-bold text-xs rounded-xl mt-auto">
              Current Plan ✓
            </span>
          ) : (
            <div className="flex flex-col gap-2 mt-auto">
              <button
                disabled={loadingTier !== null}
                onClick={() => handleStripeCheckout('pro')}
                className="w-full py-2 bg-[#8b5cf6] text-white font-bold text-xs rounded-xl hover:bg-[#7c3aed] transition flex items-center justify-center gap-1.5"
              >
                {loadingTier === 'pro' ? <Loader2 size={12} className="animate-spin" /> : <CreditCard size={12} />}
                Pay with Card
              </button>
              <button
                onClick={() => handleOpenMpesa('pro')}
                className="w-full py-2 bg-emerald-600 text-white font-bold text-xs rounded-xl hover:bg-emerald-700 transition flex items-center justify-center gap-1.5"
              >
                <Phone size={12} />
                Pay with M-Pesa
              </button>
            </div>
          )}
        </div>

        {/* Enterprise */}
        <div className="p-8 rounded-3xl bg-[#16181d] border border-white/5 flex flex-col gap-6 hover:scale-[1.01] transition-transform duration-300">
          <div>
            <h4 className="text-xs font-bold text-[#8b5cf6] uppercase tracking-wider">Enterprise</h4>
            <div className="text-3xl font-extrabold text-white mt-2">$999<span className="text-xs font-normal text-gray-400">/mo</span></div>
            <p className="text-xs text-gray-500 mt-1">For trading funds & institutions</p>
          </div>
          <ul className="flex flex-col gap-3 text-xs text-gray-300">
            <li className="flex items-center gap-2"><Check size={14} className="text-[#8b5cf6] shrink-0" /> Everything in Pro</li>
            <li className="flex items-center gap-2"><Check size={14} className="text-[#8b5cf6] shrink-0" /> Custom model fine-tuning</li>
            <li className="flex items-center gap-2"><Check size={14} className="text-[#8b5cf6] shrink-0" /> Dedicated API rate limits</li>
            <li className="flex items-center gap-2"><Check size={14} className="text-[#8b5cf6] shrink-0" /> White-label reporting portal</li>
            <li className="flex items-center gap-2"><Check size={14} className="text-[#8b5cf6] shrink-0" /> Dedicated support representative</li>
          </ul>
          {isCurrent('enterprise') ? (
            <span className="w-full py-2.5 bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-center font-bold text-xs rounded-xl mt-auto">
              Current Plan ✓
            </span>
          ) : (
            <a
              href="mailto:sales@bulllogic.com?subject=Institutional Upgrade Inquiry"
              className="w-full py-2.5 bg-white/5 border border-white/10 text-white text-center font-bold text-xs rounded-xl hover:bg-white/10 transition mt-auto flex items-center justify-center gap-1.5"
            >
              <Mail size={12} />
              Contact Sales
            </a>
          )}
        </div>

      </div>

      {/* Comparison table */}
      <div className="max-w-4xl mx-auto mb-16">
        <h2 className="text-xl font-bold text-white mb-6 text-center">Full feature comparison</h2>
        <div className="bg-[#16181d] border border-white/5 rounded-2xl overflow-hidden overflow-x-auto">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="border-b border-white/5 bg-[#1f222b]">
                <th className="p-4 font-bold text-gray-400">Feature</th>
                <th className="p-4 text-center font-bold text-gray-400">Starter</th>
                <th className="p-4 text-center font-bold text-gray-400">Plus</th>
                <th className="p-4 text-center font-bold text-gray-400">Pro</th>
                <th className="p-4 text-center font-bold text-gray-400">Enterprise</th>
              </tr>
            </thead>
            <tbody>
              {[
                { name: 'Daily Predictions Limit', starter: '5 / day', plus: 'Unlimited', pro: 'Unlimited', enterprise: 'Unlimited', highlight: true },
                { name: 'Supported Tickers', starter: '76+', plus: '76+', pro: '76+', enterprise: 'All Markets' },
                { name: 'ICT structure analysis', starter: '✓', plus: '✓', pro: '✓', enterprise: '✓' },
                { name: 'Multi-timeframe confluence', starter: '-', plus: '✓', pro: '✓', enterprise: '✓' },
                { name: 'Backtest history range', starter: '-', plus: 'Up to 1 year', pro: 'Up to 2 years', enterprise: 'Unlimited' },
                { name: 'REST API keys', starter: '-', plus: '-', pro: '5 keys', enterprise: 'Dedicated limits' },
                { name: 'MT5 Broker integration', starter: '-', plus: '-', pro: '✓', enterprise: '✓' },
                { name: 'Support SLA', starter: 'Community', plus: 'Email support', pro: 'Priority email', enterprise: 'Dedicated Representative' },
              ].map((row, i) => (
                <tr key={i} className="border-b border-white/5 hover:bg-white/[0.01]">
                  <td className="p-4 font-semibold text-gray-300">{row.name}</td>
                  <td className="p-4 text-center text-gray-400">{row.starter}</td>
                  <td className={`p-4 text-center ${row.highlight && row.plus === 'Unlimited' ? 'text-emerald-400 font-bold' : 'text-gray-300'}`}>{row.plus}</td>
                  <td className={`p-4 text-center ${row.highlight && row.pro === 'Unlimited' ? 'text-emerald-400 font-bold' : 'text-gray-300'}`}>{row.pro}</td>
                  <td className={`p-4 text-center ${row.highlight && row.enterprise === 'Unlimited' ? 'text-emerald-400 font-bold' : 'text-gray-300'}`}>{row.enterprise}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Gift Code Redemption */}
      <div className="max-w-2xl mx-auto mb-16 p-6 rounded-3xl bg-[#16181d] border border-white/5 flex flex-col md:flex-row md:items-center justify-between gap-6">
        <div>
          <h3 className="text-lg font-extrabold text-white">Have a promo key or gift code?</h3>
          <p className="text-xs text-gray-400 mt-1">
            Redeem access code credentials to activate your subscription plan.
          </p>
        </div>
        <form onSubmit={handleRedeemGift} className="flex gap-3 w-full md:w-auto">
          <input
            type="text"
            placeholder="XXXXXX"
            value={giftCode}
            onChange={(e) => setGiftCode(e.target.value)}
            disabled={redeemingGift}
            required
            className="bg-[#0b0c10] border border-white/10 text-white font-mono uppercase rounded-xl px-4 py-2 text-sm focus:outline-none focus:border-[#8b5cf6] transition w-full md:w-32 text-center"
          />
          <button
            type="submit"
            disabled={redeemingGift}
            className="py-2 px-5 bg-[#8b5cf6] hover:bg-[#7c4dff] disabled:bg-[#8b5cf6]/50 text-white font-bold text-xs rounded-xl transition whitespace-nowrap cursor-pointer"
          >
            {redeemingGift ? 'Redeeming...' : 'Redeem Code'}
          </button>
        </form>
      </div>

      {/* FAQ Accordion */}
      <div className="max-w-2xl mx-auto mb-8">
        <h2 className="text-xl font-bold text-white mb-6 text-center flex items-center justify-center gap-2">
          <HelpCircle size={20} className="text-[#8b5cf6]" />
          Frequently Asked Questions
        </h2>
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
              a: "We support major credit cards via Stripe checkout, alongside regional Safaricom M-Pesa automated billing flows."
            }
          ].map((faq, idx) => (
            <div key={idx} className="p-5 rounded-2xl bg-[#16181d] border border-white/5 flex flex-col gap-3 transition">
              <button 
                onClick={() => setOpenFaq(openFaq === idx ? null : idx)} 
                className="w-full text-left font-bold text-white text-xs md:text-sm flex items-center justify-between focus:outline-none"
              >
                <span>{faq.q}</span>
                <span className={`text-[#8b5cf6] transition-transform duration-200 transform ${openFaq === idx ? 'rotate-180' : ''}`}>
                  ▼
                </span>
              </button>
              {openFaq === idx && (
                <p className="text-[11px] md:text-xs text-gray-400 leading-relaxed transition-all">
                  {faq.a}
                </p>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* M-Pesa Modal Overlay */}
      {mpesaModal && mpesaModal.open && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
          <div className="bg-[#16181d] border border-white/10 rounded-3xl p-6 md:p-8 w-full max-w-sm flex flex-col gap-4 shadow-2xl relative">
            <h3 className="text-lg font-extrabold text-white flex items-center gap-2">
              <Phone className="text-emerald-500" />
              Pay with M-Pesa
            </h3>
            <p className="text-xs text-gray-400">
              You are subscribing to the <strong className="text-white uppercase">{mpesaModal.tier}</strong> plan.
              Please input your Safaricom phone number to receive an STK Push confirmation.
            </p>
            <div className="bg-[#1f222b] p-3 rounded-xl border border-white/5 text-center text-xs font-mono">
              Amount Due: <span className="text-emerald-400 font-extrabold">KES {mpesaModal.amount}</span>
            </div>
            
            <form onSubmit={handleSubmitMpesa} className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <label className="text-[10px] text-gray-400 font-bold uppercase tracking-wider">Phone Number</label>
                <input
                  type="tel"
                  placeholder="0712345678"
                  value={mpesaPhone}
                  onChange={(e) => setMpesaPhone(e.target.value)}
                  disabled={mpesaLoading}
                  required
                  className="bg-[#0b0c10] border border-white/10 text-white rounded-xl px-4 py-2 text-sm focus:outline-none focus:border-[#8b5cf6] transition"
                />
              </div>

              <div className="flex gap-3 mt-2">
                <button
                  type="button"
                  onClick={() => setMpesaModal(null)}
                  disabled={mpesaLoading}
                  className="flex-1 py-2 bg-white/5 hover:bg-white/10 text-white font-bold text-xs rounded-xl transition"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={mpesaLoading}
                  className="flex-1 py-2 bg-emerald-600 hover:bg-emerald-700 text-white font-bold text-xs rounded-xl transition flex items-center justify-center gap-1.5"
                >
                  {mpesaLoading ? (
                    <>
                      <Loader2 size={12} className="animate-spin" />
                      Processing
                    </>
                  ) : (
                    'Confirm STK'
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
