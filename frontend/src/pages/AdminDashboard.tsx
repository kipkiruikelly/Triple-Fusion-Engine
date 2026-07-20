import React, { useState, useEffect } from 'react';
import toast from 'react-hot-toast';
import { 
  Users, Activity, Settings, Database, AlertTriangle, ShieldCheck, 
  Megaphone, Plus, Terminal, Power, CheckCircle2, ShieldAlert, Server
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { Navigate, useSearchParams } from 'react-router-dom';
import { HorizonCard } from '../components/HorizonCard';
import { HorizonWidget } from '../components/HorizonWidget';
import { apiFetch } from '../utils/api';

interface UserItem {
  id: number;
  username: string;
  email: string;
  plan: string;
  role?: string;
  status: string;
  created_at: string;
}

interface ErrorItem {
  id: number;
  severity: string;
  endpoint: string;
  message: string;
  created_at: string;
}

interface PaymentItem {
  id: number;
  username: string;
  email: string;
  provider: string;
  plan: string;
  tier: string;
  amount: number;
  currency: string;
  reference: string;
  status: string;
  created_at: string;
}

interface BroadcastItem {
  id: number;
  title: string;
  body: string;
  segment: string;
  channel: string;
  sent_count: number;
  created_at: string;
}

export const AdminDashboard: React.FC = () => {
  const { user } = useAuth();
  const [searchParams] = useSearchParams();
  const adminTab = (searchParams.get('tab') || 'overview') as 'overview' | 'client-management' | 'trade-management' | 'risk-management' | 'finance-accounting' | 'system-admin';
  
  // Pillars Sub-tabs states
  const [clientSubTab, setClientSubTab] = useState<'users' | 'kyc' | 'ib'>('users');
  const [tradeSubTab, setTradeSubTab] = useState<'routing' | 'allocation' | 'compliance'>('routing');
  const [riskSubTab, setRiskSubTab] = useState<'monitor' | 'margin' | 'liquidity'>('monitor');
  const [financeSubTab, setFinanceSubTab] = useState<'gateways' | 'ledger' | 'reconciliation'>('gateways');
  const [systemSubTab, setSystemSubTab] = useState<'telemetry' | 'rbac' | 'broadcasts' | 'mt5' | 'gift-codes' | 'bots'>('telemetry');

  // Pillars data state
  const [pillarData, setPillarData] = useState<any>(null);

  // Forms inputs states
  const [allocTicker, setAllocTicker] = useState('FOREXCOM:SPXUSD');
  const [allocVolume, setAllocVolume] = useState(10);
  const [allocMethod, setAllocMethod] = useState('equal');
  const [riskLeverage, setRiskLeverage] = useState(100);
  const [riskStopOut, setRiskStopOut] = useState(30);
  const [riskMarkup, setRiskMarkup] = useState(1.5);
  
  const [metrics, setMetrics] = useState<any>(null);
  const [usersList, setUsersList] = useState<UserItem[]>([]);
  const [paymentsList, setPaymentsList] = useState<PaymentItem[]>([]);
  const [broadcastsList, setBroadcastsList] = useState<BroadcastItem[]>([]);
  const [mt5Status, setMt5Status] = useState<string>('disconnected');
  const [giftCodesList, setGiftCodesList] = useState<any[]>([]);
  
  const [loading, setLoading] = useState(true);
  
  // Broadcast Form State
  const [broadcastTitle, setBroadcastTitle] = useState('');
  const [broadcastBody, setBroadcastBody] = useState('');
  const [broadcastSegment, setBroadcastSegment] = useState('all');
  const [broadcastChannel, setBroadcastChannel] = useState('in-app');
  const [sendingBroadcast, setSendingBroadcast] = useState(false);

  // Gift Codes Form State
  const [giftDays, setGiftDays] = useState(30);
  const [giftCount, setGiftCount] = useState(1);
  const [giftNote, setGiftNote] = useState('');
  const [generatingGift, setGeneratingGift] = useState(false);
  const [giftCodesGenerated, setGiftCodesGenerated] = useState<string[]>([]);

  // If not admin (role_level < 3), boot them out
  if (!user || user.role_level < 3) {
    return <Navigate to="/portfolio" replace />;
  }

  const loadOverview = async () => {
    try {
      const res = await apiFetch('/admin/api/overview');
      if (res.ok && res.overview) {
        setMetrics(res.overview);
      }
    } catch (err) {
      console.error('Failed to fetch overview metrics', err);
    }
  };

  const loadUsers = async () => {
    try {
      const res = await apiFetch('/admin/api/users/list');
      if (res.ok && res.users) {
        setUsersList(res.users);
      }
    } catch (err) {
      console.error('Failed to fetch user list', err);
    }
  };

  const loadPayments = async () => {
    try {
      const res = await apiFetch('/admin/api/payments/list');
      if (res.ok && res.payments) {
        setPaymentsList(res.payments);
      }
    } catch (err) {
      console.error('Failed to fetch payment list', err);
    }
  };

  const loadBroadcasts = async () => {
    try {
      const res = await apiFetch('/admin/api/broadcasts/list');
      if (res.ok && res.broadcasts) {
        setBroadcastsList(res.broadcasts);
      }
    } catch (err) {
      console.error('Failed to fetch broadcasts list', err);
    }
  };

  const loadMt5Status = async () => {
    try {
      const res = await apiFetch('/mt5/status');
      if (res.status) {
        setMt5Status(res.status);
      }
    } catch (err) {
      console.error('Failed to fetch MT5 status', err);
    }
  };

  const loadGiftCodes = async () => {
    try {
      const res = await apiFetch('/admin/api/gift-codes/list');
      if (res.ok && res.gift_codes) {
        setGiftCodesList(res.gift_codes);
      }
    } catch (err) {
      console.error('Failed to fetch gift codes list', err);
    }
  };

  const handleGenerateGiftCodes = async (e: React.FormEvent) => {
    e.preventDefault();
    setGeneratingGift(true);
    setGiftCodesGenerated([]);
    try {
      const res = await apiFetch('/admin/api/gift-codes/generate', {
        method: 'POST',
        body: { days: giftDays, count: giftCount, note: giftNote }
      });
      if (res.ok && res.codes) {
        toast.success(`Generated ${res.codes.length} code(s)!`);
        setGiftCodesGenerated(res.codes);
        setGiftNote('');
        loadGiftCodes();
      }
    } catch (err) {
      console.error('Failed to generate gift codes', err);
    } finally {
      setGeneratingGift(false);
    }
  };

  const loadPillarData = async () => {
    try {
      const res = await apiFetch('/admin/api/pillars/data');
      if (res.ok) {
        setPillarData(res);
      }
    } catch (err) {
      console.error('Failed to fetch operational pillars data', err);
    }
  };

  const handlePillarAction = async (actionType: string, targetId: any, status: string) => {
    try {
      const res = await apiFetch('/admin/api/pillars/action', {
        method: 'POST',
        body: JSON.stringify({ action_type: actionType, target_id: targetId, status }),
        headers: { 'Content-Type': 'application/json' }
      });
      if (res.ok) {
        toast.success(res.message || 'Operation executed successfully');
        loadPillarData();
      } else {
        toast.error(res.error || 'Operation failed');
      }
    } catch (err) {
      console.error('Pillar action failed', err);
      toast.error('Network error executing action');
    }
  };

  const loadData = async () => {
    setLoading(true);
    await loadOverview();
    await loadPillarData();
    await loadUsers();
    await loadPayments();
    await loadBroadcasts();
    await loadMt5Status();
    await loadGiftCodes();
    setLoading(false);
  };

  useEffect(() => {
    loadData();
  }, [adminTab]);

  const handleToggleStatus = async (userId: number) => {
    try {
      const res = await apiFetch(`/admin/api/users/${userId}/toggle-status/json`, {
        method: 'POST'
      });
      if (res.ok) {
        setUsersList(prev => prev.map(u => u.id === userId ? { ...u, status: res.status } : u));
        loadOverview();
      }
    } catch (err) {
      console.error('Failed to toggle status', err);
    }
  };

  const handlePlanChange = async (userId: number, newPlan: string) => {
    try {
      const res = await apiFetch(`/admin/api/users/${userId}/update-plan/json`, {
        method: 'POST',
        body: JSON.stringify({ plan: newPlan }),
        headers: { 'Content-Type': 'application/json' }
      });
      if (res.ok) {
        setUsersList(prev => prev.map(u => u.id === userId ? { ...u, plan: res.plan } : u));
      }
    } catch (err) {
      console.error('Failed to update plan', err);
    }
  };

  const handleRoleChange = async (userId: number, newRole: string) => {
    try {
      const res = await apiFetch(`/admin/api/users/${userId}/update-role/json`, {
        method: 'POST',
        body: JSON.stringify({ role: newRole }),
        headers: { 'Content-Type': 'application/json' }
      });
      if (res.ok) {
        setUsersList(prev => prev.map(u => u.id === userId ? { ...u, role: res.role } : u));
        toast.success('User role updated successfully');
      } else {
        toast.error(res.error || 'Failed to update user role');
      }
    } catch (err) {
      console.error('Failed to update role', err);
      toast.error('Network error updating role');
    }
  };

  const handleSendBroadcast = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!broadcastTitle || !broadcastBody) return;
    setSendingBroadcast(true);
    try {
      const res = await apiFetch('/admin/api/broadcasts/create', {
        method: 'POST',
        body: JSON.stringify({
          title: broadcastTitle,
          body: broadcastBody,
          segment: broadcastSegment,
          channel: broadcastChannel
        }),
        headers: { 'Content-Type': 'application/json' }
      });
      if (res.ok) {
        setBroadcastTitle('');
        setBroadcastBody('');
        loadBroadcasts();
      }
    } catch (err) {
      console.error('Failed to send broadcast', err);
    } finally {
      setSendingBroadcast(false);
    }
  };

  const handleMt5Control = async (action: 'start' | 'stop') => {
    try {
      const endpoint = action === 'start' ? '/mt5/start' : '/mt5/stop';
      const res = await apiFetch(endpoint, { method: 'POST' });
      if (res.ok) {
        loadMt5Status();
      }
    } catch (err) {
      console.error('Failed to route MT5 control request', err);
    }
  };

  return (
    <div className="flex-1 overflow-y-auto p-4 md:p-8 flex flex-col gap-6 bg-nexus-bg text-white min-h-screen">
      
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold flex items-center gap-2 text-white">
            <Settings className="text-nexus-pur" /> <span className="gt">Admin Console</span>
          </h2>
          <p className="text-sm text-gray-400 mt-1">
            Complete platform administrative control dashboard.
          </p>
        </div>
        <button
          onClick={loadData}
          className="px-5 py-2.5 bg-gradient-to-r from-nexus-pur to-nexus-blu hover:shadow-[0_8px_24px_rgba(139,92,246,0.3)] text-white font-bold rounded-xl transition duration-200 transform hover:-translate-y-0.5 cursor-pointer"
        >
          Refresh Views
        </button>
      </div>

      {adminTab === 'overview' && (
        <div className="flex flex-col gap-6 w-full animate-fadeIn">
          {/* Grid of Horizon metric cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5">
            <HorizonWidget
              icon={<Users className="w-6 h-6 text-nexus-pur" />}
              title="Total Users"
              subtitle={metrics?.users?.total ?? '-'}
            />
            <HorizonWidget
              icon={<Database className="w-6 h-6 text-green-400" />}
              title="Active Bots"
              subtitle={metrics?.bots?.active ?? '-'}
            />
            <HorizonWidget
              icon={<Activity className="w-6 h-6 text-nexus-blu" />}
              title="API Predictions"
              subtitle={metrics?.predictions?.total ?? '-'}
            />
            <HorizonWidget
              icon={<AlertTriangle className="w-6 h-6 text-red-400" />}
              title="System Exceptions"
              subtitle={metrics?.recent_errors?.length ?? '-'}
            />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            
            {/* Quick signup log */}
            <HorizonCard extra="col-span-1 lg:col-span-2 p-6 bg-nexus-sf border border-white/5">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-bold text-white">Recent Signups</h3>
                <span className="text-xs bg-nexus-bg text-gray-400 px-3 py-1 rounded-full border border-white/5">
                  Live View
                </span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="border-b border-white/5 text-gray-400 text-xs uppercase font-bold">
                      <th className="py-3 px-4">Username</th>
                      <th className="py-3 px-4">Plan</th>
                      <th className="py-3 px-4">Created Date</th>
                      <th className="py-3 px-4">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {loading ? (
                      <tr>
                        <td colSpan={4} className="py-8 text-center text-gray-400">Loading signups...</td>
                      </tr>
                    ) : (
                      usersList.slice(0, 5).map((usr) => (
                        <tr key={usr.id} className="border-b border-white/5 hover:bg-nexus-bg/40 text-sm">
                          <td className="py-3 px-4">
                            <div className="flex flex-col">
                              <span className="font-bold text-white">{usr.username}</span>
                              <span className="text-xs text-gray-500">{usr.email}</span>
                            </div>
                          </td>
                          <td className="py-3 px-4 text-xs font-bold uppercase text-nexus-pur">{usr.plan}</td>
                          <td className="py-3 px-4 text-xs text-gray-400">{usr.created_at.slice(0,10)}</td>
                          <td className="py-3 px-4">
                            <span className={`inline-block px-2 py-0.5 rounded text-[10px] font-bold ${
                              usr.status === 'active' ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'
                            }`}>
                              {usr.status.toUpperCase()}
                            </span>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </HorizonCard>

            {/* Quick exception log */}
            <HorizonCard extra="p-6 bg-nexus-sf border border-white/5">
              <h3 className="text-lg font-bold text-white flex items-center gap-2 mb-4">
                <AlertTriangle className="text-red-400 w-5 h-5" /> Recent Exceptions
              </h3>
              <div className="flex flex-col gap-4">
                {metrics?.recent_errors?.length > 0 ? (
                  metrics.recent_errors.map((err: ErrorItem) => (
                    <div key={err.id} className="p-3 bg-nexus-bg border border-white/5 rounded-xl text-xs flex flex-col gap-1.5">
                      <div className="flex justify-between items-center text-[10px] text-gray-500">
                        <span className="font-bold text-red-400 bg-red-400/10 px-2 py-0.5 rounded">
                          {err.severity?.toUpperCase() || 'ERROR'}
                        </span>
                        <span>{err.created_at.slice(0, 16)}</span>
                      </div>
                      <div className="font-semibold text-gray-300">
                        Endpoint: <span className="text-white">{err.endpoint || '/'}</span>
                      </div>
                      <div className="text-gray-400 font-mono break-all bg-nexus-bg p-2 rounded border border-white/5">
                        {err.message}
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="py-12 flex flex-col items-center justify-center gap-2 text-gray-500 text-sm">
                    <ShieldCheck size={36} className="text-green-500" />
                    <span>No errors logged in the system.</span>
                  </div>
                )}
              </div>
            </HorizonCard>

          </div>
        </div>
      )}

        {adminTab === 'client-management' && (
          <div className="flex flex-col gap-6 w-full">
            {/* Sub Tabs */}
            <div className="flex items-center gap-2 bg-[#16181d] border border-white/5 p-1 rounded-xl w-fit">
              <button
                onClick={() => setClientSubTab('users')}
                className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${
                  clientSubTab === 'users' ? 'bg-[#8b5cf6] text-white' : 'text-gray-400 hover:text-white'
                }`}
              >
                Accounts list
              </button>
              <button
                onClick={() => setClientSubTab('kyc')}
                className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${
                  clientSubTab === 'kyc' ? 'bg-[#8b5cf6] text-white' : 'text-gray-400 hover:text-white'
                }`}
              >
                KYC/AML Portal
              </button>
              <button
                onClick={() => setClientSubTab('ib')}
                className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${
                  clientSubTab === 'ib' ? 'bg-[#8b5cf6] text-white' : 'text-gray-400 hover:text-white'
                }`}
              >
                Introducing Brokers (IB)
              </button>
            </div>

            {/* Sub Tab: Users */}
            {clientSubTab === 'users' && (
              <HorizonCard extra="p-6 bg-nexus-sf border border-white/5">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-lg font-bold text-white">Registered Accounts</h3>
                  <span className="text-xs bg-nexus-bg text-gray-400 px-3 py-1 rounded-full border border-white/5">
                    {usersList.length} users
                  </span>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-left border-collapse">
                    <thead>
                      <tr className="border-b border-white/5 text-gray-400 text-xs uppercase font-bold">
                        <th className="py-3 px-4">User</th>
                        <th className="py-3 px-4">Plan Tier</th>
                        <th className="py-3 px-4">Role</th>
                        <th className="py-3 px-4">Created</th>
                        <th className="py-3 px-4">Status</th>
                        <th className="py-3 px-4">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {usersList.map((usr) => (
                        <tr key={usr.id} className="border-b border-white/5 hover:bg-nexus-bg/40 text-sm">
                          <td className="py-3 px-4">
                            <div className="flex flex-col">
                              <span className="font-bold text-white">{usr.username}</span>
                              <span className="text-xs text-gray-500">{usr.email}</span>
                            </div>
                          </td>
                          <td className="py-3 px-4">
                            <select
                              value={usr.plan}
                              onChange={(e) => handlePlanChange(usr.id, e.target.value)}
                              className="bg-nexus-bg border border-white/10 text-white text-xs rounded-lg p-1.5 focus:outline-none focus:border-nexus-pur font-bold"
                            >
                              <option value="free">Free</option>
                              <option value="plus">Plus</option>
                              <option value="pro">Pro</option>
                              <option value="enterprise">Enterprise</option>
                            </select>
                          </td>
                          <td className="py-3 px-4">
                            <select
                              value={usr.role || 'user'}
                              onChange={(e) => handleRoleChange(usr.id, e.target.value)}
                              className="bg-nexus-bg border border-white/10 text-white text-xs rounded-lg p-1.5 focus:outline-none focus:border-nexus-pur font-bold"
                            >
                              <option value="user">User</option>
                              <option value="support">Support</option>
                              <option value="admin">Admin</option>
                            </select>
                          </td>
                          <td className="py-3 px-4 text-xs text-gray-400">{usr.created_at}</td>
                          <td className="py-3 px-4">
                            <span className={`inline-block px-2.5 py-0.5 rounded-full text-xs font-semibold ${
                              usr.status === 'active' ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'
                            }`}>
                              {usr.status}
                            </span>
                          </td>
                          <td className="py-3 px-4">
                            <button
                              onClick={() => handleToggleStatus(usr.id)}
                              className={`px-3 py-1.5 text-xs font-bold rounded-lg border transition duration-150 cursor-pointer ${
                                usr.status === 'active'
                                  ? 'bg-red-500/10 hover:bg-red-500/20 text-red-400 border-red-500/20'
                                  : 'bg-green-500/10 hover:bg-green-500/20 text-green-400 border-green-500/20'
                              }`}
                            >
                              {usr.status === 'active' ? 'Ban User' : 'Activate'}
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </HorizonCard>
            )}

            {/* Sub Tab: KYC */}
            {clientSubTab === 'kyc' && (
              <HorizonCard extra="p-6 bg-nexus-sf border border-white/5">
                <h3 className="text-lg font-bold text-white mb-4">KYC / AML Onboarding Verification</h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs border-collapse">
                    <thead>
                      <tr className="border-b border-white/5 text-gray-400 font-bold uppercase">
                        <th className="py-2.5">User</th>
                        <th className="py-2.5">Document Type</th>
                        <th className="py-2.5">Risk Score</th>
                        <th className="py-2.5">Verification Status</th>
                        <th className="py-2.5">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pillarData?.kyc_list?.map((item: any) => (
                        <tr key={item.id} className="border-b border-white/5 hover:bg-white/2 transition">
                          <td className="py-3 font-bold text-white">
                            <div>{item.username}</div>
                            <div className="text-[10px] text-gray-500 font-normal">{item.email}</div>
                          </td>
                          <td className="py-3 text-gray-300">{item.doc_type}</td>
                          <td className="py-3">
                            <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                              item.risk_score > 60 ? 'bg-red-500/10 text-red-400' : item.risk_score > 30 ? 'bg-yellow-500/10 text-yellow-400' : 'bg-green-500/10 text-green-400'
                            }`}>
                              Score: {item.risk_score}%
                            </span>
                          </td>
                          <td className="py-3 font-semibold text-yellow-400">{item.status}</td>
                          <td className="py-3 flex gap-2">
                            <button
                              onClick={() => handlePillarAction('kyc_approve', item.id, 'Approved')}
                              className="px-2.5 py-1 bg-green-500/10 hover:bg-green-500/20 border border-green-500/20 text-green-400 font-bold rounded-lg cursor-pointer transition"
                            >
                              Approve
                            </button>
                            <button
                              onClick={() => handlePillarAction('kyc_reject', item.id, 'Rejected')}
                              className="px-2.5 py-1 bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 text-red-400 font-bold rounded-lg cursor-pointer transition"
                            >
                              Reject
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </HorizonCard>
            )}

            {/* Sub Tab: Introducing Brokers */}
            {clientSubTab === 'ib' && (
              <HorizonCard extra="p-6 bg-nexus-sf border border-white/5">
                <h3 className="text-lg font-bold text-white mb-4">Partner & Introducing Broker (IB) Portal</h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs border-collapse">
                    <thead>
                      <tr className="border-b border-white/5 text-gray-400 font-bold uppercase">
                        <th className="py-2.5">Partner Name</th>
                        <th className="py-2.5">Tier</th>
                        <th className="py-2.5">Total Referrals</th>
                        <th className="py-2.5">Accrued Commissions</th>
                        <th className="py-2.5">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pillarData?.ib_list?.map((item: any) => (
                        <tr key={item.id} className="border-b border-white/5 hover:bg-white/2 transition">
                          <td className="py-3 font-bold text-white">{item.name}</td>
                          <td className="py-3 text-gray-300">Level {item.tier} Partner</td>
                          <td className="py-3 font-bold text-nexus-blu">{item.referrals} accounts</td>
                          <td className="py-3 font-bold text-green-400">${item.commission.toFixed(2)}</td>
                          <td className="py-3">
                            <button
                              onClick={() => handlePillarAction('ib_payout', item.id, 'Disbursed')}
                              className="px-3 py-1 bg-nexus-pur/15 hover:bg-nexus-pur/25 border border-nexus-pur/20 text-nexus-pur font-bold rounded-lg cursor-pointer transition"
                            >
                              Process Payout
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </HorizonCard>
            )}
          </div>
        )}

        {adminTab === 'trade-management' && (
          <div className="flex flex-col gap-6 w-full">
            {/* Sub Tabs */}
            <div className="flex items-center gap-2 bg-[#16181d] border border-white/5 p-1 rounded-xl w-fit">
              <button
                onClick={() => setTradeSubTab('routing')}
                className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${
                  tradeSubTab === 'routing' ? 'bg-[#8b5cf6] text-white' : 'text-gray-400 hover:text-white'
                }`}
              >
                Routing & LP bridges
              </button>
              <button
                onClick={() => setTradeSubTab('allocation')}
                className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${
                  tradeSubTab === 'allocation' ? 'bg-[#8b5cf6] text-white' : 'text-gray-400 hover:text-white'
                }`}
              >
                Block Trade Allocator
              </button>
              <button
                onClick={() => setTradeSubTab('compliance')}
                className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${
                  tradeSubTab === 'compliance' ? 'bg-[#8b5cf6] text-white' : 'text-gray-400 hover:text-white'
                }`}
              >
                Compliance Monitor
              </button>
            </div>

            {/* Sub Tab: LP Routing */}
            {tradeSubTab === 'routing' && (
              <HorizonCard extra="p-6 bg-nexus-sf border border-white/5">
                <h3 className="text-lg font-bold text-white mb-4">Liquidity Provider Order Routing & Bridges</h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs border-collapse">
                    <thead>
                      <tr className="border-b border-white/5 text-gray-400 font-bold uppercase">
                        <th className="py-2.5">Bridge Venue</th>
                        <th className="py-2.5">Latency</th>
                        <th className="py-2.5">Load Level</th>
                        <th className="py-2.5">Connection Status</th>
                        <th className="py-2.5">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pillarData?.lp_connections?.map((item: any) => (
                        <tr key={item.id} className="border-b border-white/5 hover:bg-white/2 transition">
                          <td className="py-3 font-bold text-white">{item.name}</td>
                          <td className="py-3 text-nexus-blu font-mono">{item.latency}</td>
                          <td className="py-3 font-mono text-gray-300">{item.load}</td>
                          <td className="py-3">
                            <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-green-500/10 text-green-400">
                              {item.status}
                            </span>
                          </td>
                          <td className="py-3">
                            <button
                              onClick={() => handlePillarAction('lp_bridge_reset', item.id, 'Rebooted')}
                              className="px-3 py-1 bg-white/5 hover:bg-white/10 border border-white/10 text-white font-bold rounded-lg cursor-pointer transition flex items-center gap-1.5"
                            >
                              <Power size={10} /> Reset Connection
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </HorizonCard>
            )}

            {/* Sub Tab: Block trade allocator */}
            {tradeSubTab === 'allocation' && (
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 w-full">
                <HorizonCard extra="p-6 bg-nexus-sf border border-white/5 h-fit">
                  <h3 className="text-lg font-bold text-white mb-4">Split & Allocate Block Trades</h3>
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      handlePillarAction('block_allocation', allocTicker, `Allocated ${allocVolume} lots via ${allocMethod}`);
                      toast.success(`Allocated ${allocVolume} lots of ${allocTicker} successfully!`);
                    }}
                    className="flex flex-col gap-4"
                  >
                    <div>
                      <label className="text-xs text-gray-400 font-bold block mb-1">Contract Asset</label>
                      <select
                        value={allocTicker}
                        onChange={(e) => setAllocTicker(e.target.value)}
                        className="w-full bg-nexus-bg border border-white/10 text-white rounded-lg p-2 text-xs focus:outline-none focus:border-nexus-pur font-bold"
                      >
                        <option value="FOREXCOM:SPXUSD">SPXUSD (S&P 500 CFD)</option>
                        <option value="FOREXCOM:NAS100">NAS100 (Nasdaq CFD)</option>
                        <option value="EURUSD">EURUSD (Euro / US Dollar)</option>
                      </select>
                    </div>
                    <div>
                      <label className="text-xs text-gray-400 font-bold block mb-1">Total Volume (Lots)</label>
                      <input
                        type="number"
                        value={allocVolume}
                        onChange={(e) => setAllocVolume(parseFloat(e.target.value) || 1)}
                        min={0.1}
                        step={0.1}
                        required
                        className="w-full bg-nexus-bg border border-white/10 text-white rounded-lg p-2 text-xs focus:outline-none focus:border-nexus-pur"
                      />
                    </div>
                    <div>
                      <label className="text-xs text-gray-400 font-bold block mb-1">Allocation Rule</label>
                      <select
                        value={allocMethod}
                        onChange={(e) => setAllocMethod(e.target.value)}
                        className="w-full bg-nexus-bg border border-white/10 text-white rounded-lg p-2 text-xs focus:outline-none focus:border-nexus-pur"
                      >
                        <option value="equal">Equal Split (Equal lots to all accounts)</option>
                        <option value="prorata">Pro-Rata (Based on Account Equity ratios)</option>
                      </select>
                    </div>
                    <button
                      type="submit"
                      className="w-full py-2.5 bg-gradient-to-r from-nexus-pur to-nexus-blu text-white font-bold text-xs rounded-xl hover:shadow-lg transition cursor-pointer"
                    >
                      Process Allocations
                    </button>
                  </form>
                </HorizonCard>

                <HorizonCard extra="lg:col-span-2 p-6 bg-nexus-sf border border-white/5">
                  <h3 className="text-lg font-bold text-white mb-4">Target Accounts Allocation Matrix</h3>
                  <div className="text-xs text-gray-400 mb-4 font-normal">
                    The block trade volumes will be split and dispatched across active client accounts in real-time.
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs border-collapse">
                      <thead>
                        <tr className="border-b border-white/5 text-gray-400 font-bold uppercase">
                          <th className="py-2.5">Account ID</th>
                          <th className="py-2.5">Account Name</th>
                          <th className="py-2.5">Equity (USD)</th>
                          <th className="py-2.5">Equal Share</th>
                          <th className="py-2.5">Pro-Rata Share</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr className="border-b border-white/5 hover:bg-white/2 transition">
                          <td className="py-3 font-mono font-bold text-white">#ACC-9214</td>
                          <td className="py-3 text-gray-300">janedoe</td>
                          <td className="py-3 font-mono font-bold text-green-400">$10,432.00</td>
                          <td className="py-3 font-mono text-gray-400">{(allocVolume / 3).toFixed(2)} Lots</td>
                          <td className="py-3 font-mono text-white font-bold">{(allocVolume * 0.45).toFixed(2)} Lots</td>
                        </tr>
                        <tr className="border-b border-white/5 hover:bg-white/2 transition">
                          <td className="py-3 font-mono font-bold text-white">#ACC-3814</td>
                          <td className="py-3 text-gray-300">johnsmith</td>
                          <td className="py-3 font-mono font-bold text-green-400">$8,210.00</td>
                          <td className="py-3 font-mono text-gray-400">{(allocVolume / 3).toFixed(2)} Lots</td>
                          <td className="py-3 font-mono text-white font-bold">{(allocVolume * 0.35).toFixed(2)} Lots</td>
                        </tr>
                        <tr className="border-b border-white/5 hover:bg-white/2 transition">
                          <td className="py-3 font-mono font-bold text-white">#ACC-4712</td>
                          <td className="py-3 text-gray-300">cryptotrader</td>
                          <td className="py-3 font-mono font-bold text-green-400">$4,570.00</td>
                          <td className="py-3 font-mono text-gray-400">{(allocVolume / 3).toFixed(2)} Lots</td>
                          <td className="py-3 font-mono text-white font-bold">{(allocVolume * 0.20).toFixed(2)} Lots</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </HorizonCard>
              </div>
            )}

            {/* Sub Tab: Compliance Monitor */}
            {tradeSubTab === 'compliance' && (
              <HorizonCard extra="p-6 bg-nexus-sf border border-white/5">
                <h3 className="text-lg font-bold text-white mb-4">Regulatory Compliance Monitor Feed</h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs border-collapse">
                    <thead>
                      <tr className="border-b border-white/5 text-gray-400 font-bold uppercase">
                        <th className="py-2.5">User Account</th>
                        <th className="py-2.5">Violation Triggered</th>
                        <th className="py-2.5">Telemetry Details</th>
                        <th className="py-2.5">Severity</th>
                        <th className="py-2.5">Detected At</th>
                        <th className="py-2.5">Compliance Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pillarData?.compliance_alerts?.map((item: any) => (
                        <tr key={item.id} className="border-b border-white/5 hover:bg-white/2 transition">
                          <td className="py-3 font-bold text-white">{item.user}</td>
                          <td className="py-3 text-red-400 font-bold">{item.type}</td>
                          <td className="py-3 text-gray-300 max-w-[200px] truncate" title={item.details}>{item.details}</td>
                          <td className="py-3">
                            <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                              item.severity === 'High' ? 'bg-red-500/10 text-red-400 animate-pulse' : 'bg-yellow-500/10 text-yellow-400'
                            }`}>
                              {item.severity}
                            </span>
                          </td>
                          <td className="py-3 text-gray-500 font-mono">{item.created_at}</td>
                          <td className="py-3">
                            <button
                              onClick={() => handlePillarAction('compliance_clear', item.id, 'Cleared')}
                              className="px-2.5 py-1 bg-green-500/10 hover:bg-green-500/20 border border-green-500/20 text-green-400 font-bold rounded-lg cursor-pointer transition"
                            >
                              Resolve
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </HorizonCard>
            )}
          </div>
        )}

        {adminTab === 'risk-management' && (
          <div className="flex flex-col gap-6 w-full">
            {/* Sub Tabs */}
            <div className="flex items-center gap-2 bg-[#16181d] border border-white/5 p-1 rounded-xl w-fit">
              <button
                onClick={() => setRiskSubTab('monitor')}
                className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${
                  riskSubTab === 'monitor' ? 'bg-[#8b5cf6] text-white' : 'text-gray-400 hover:text-white'
                }`}
              >
                Risk Monitor
              </button>
              <button
                onClick={() => setRiskSubTab('margin')}
                className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${
                  riskSubTab === 'margin' ? 'bg-[#8b5cf6] text-white' : 'text-gray-400 hover:text-white'
                }`}
              >
                Margin & Leverage control
              </button>
              <button
                onClick={() => setRiskSubTab('liquidity')}
                className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${
                  riskSubTab === 'liquidity' ? 'bg-[#8b5cf6] text-white' : 'text-gray-400 hover:text-white'
                }`}
              >
                Liquidity & Spreads
              </button>
            </div>

            {/* Sub Tab: Risk Monitor */}
            {riskSubTab === 'monitor' && (
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 w-full">
                {/* Circuit Breaker Emergency Control */}
                <HorizonCard extra="p-6 bg-nexus-sf border border-white/5 h-fit text-center flex flex-col items-center justify-center gap-4">
                  <ShieldAlert className="text-red-500 w-16 h-16 animate-bounce" />
                  <div>
                    <h3 className="text-lg font-extrabold text-white">System Circuit Breaker</h3>
                    <p className="text-xs text-gray-400 mt-1 leading-relaxed">
                      Emergency override to immediately freeze MT5 order routing and reject incoming trading signals across all portfolios.
                    </p>
                  </div>
                  <button
                    onClick={() => {
                      handlePillarAction('circuit_breaker', 'system_wide', 'Tripped');
                      toast.success('EMERGENCY CIRCUIT BREAKER ARMED: FREEZING MT5 ROUTER');
                    }}
                    className="px-6 py-3 bg-red-600 hover:bg-red-700 hover:shadow-[0_8px_24px_rgba(220,38,38,0.4)] text-white font-extrabold text-xs uppercase tracking-wider rounded-xl transition duration-200 transform hover:-translate-y-0.5 cursor-pointer"
                  >
                    Trip Circuit Breaker
                  </button>
                </HorizonCard>

                {/* Positions exposure table */}
                <HorizonCard extra="lg:col-span-2 p-6 bg-nexus-sf border border-white/5">
                  <h3 className="text-lg font-bold text-white mb-2">Net Positions Market Exposure</h3>
                  <div className="text-xs text-gray-500 font-normal mb-4">
                    Aggregated open interest volume limits across liquidity venues. Total exposure: <strong className="text-white">${pillarData?.risk_metrics?.total_exposure.toLocaleString()}</strong>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs border-collapse">
                      <thead>
                        <tr className="border-b border-white/5 text-gray-400 font-bold uppercase">
                          <th className="py-2.5">Asset Symbol</th>
                          <th className="py-2.5">Aggregate Longs</th>
                          <th className="py-2.5">Aggregate Shorts</th>
                          <th className="py-2.5">Net Exposure (Lots)</th>
                          <th className="py-2.5">Exposure Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {pillarData?.risk_metrics?.exposures?.map((item: any, i: number) => (
                          <tr key={i} className="border-b border-white/5 hover:bg-white/2 transition">
                            <td className="py-3 font-mono font-bold text-white">{item.ticker}</td>
                            <td className="py-3 font-mono text-green-400">{item.long_lots} Lots</td>
                            <td className="py-3 font-mono text-red-400">{item.short_lots} Lots</td>
                            <td className={`py-3 font-mono font-bold ${item.net >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                              {item.net >= 0 ? `+${item.net}` : item.net} Lots
                            </td>
                            <td className="py-3">
                              <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-green-500/10 text-green-400">
                                Safe Limits
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </HorizonCard>
              </div>
            )}

            {/* Sub Tab: Margin leverage control */}
            {riskSubTab === 'margin' && (
              <HorizonCard extra="p-6 bg-nexus-sf border border-white/5 max-w-xl">
                <h3 className="text-lg font-bold text-white mb-4">Account Tier Leverage & Margin Configuration</h3>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    handlePillarAction('margin_settings', 'tiers', `Leverage Cap: 1:${riskLeverage}, Stop-out: ${riskStopOut}%`);
                    toast.success('Successfully updated margin thresholds!');
                  }}
                  className="flex flex-col gap-6"
                >
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <label className="text-xs text-gray-400 font-bold block mb-1">Max Leverage Cap (Default)</label>
                      <select
                        value={riskLeverage}
                        onChange={(e) => setRiskLeverage(parseInt(e.target.value) || 100)}
                        className="w-full bg-nexus-bg border border-white/10 text-white rounded-lg p-2.5 text-xs focus:outline-none focus:border-nexus-pur font-bold"
                      >
                        <option value={10}>1:10 (Conservative)</option>
                        <option value={30}>1:30 (Retail Standard)</option>
                        <option value={100}>1:100 (Professional)</option>
                        <option value={500}>1:500 (Aggressive CFD)</option>
                      </select>
                    </div>
                    <div>
                      <label className="text-xs text-gray-400 font-bold block mb-1">Stop-out Threshold Level (%)</label>
                      <input
                        type="number"
                        value={riskStopOut}
                        onChange={(e) => setRiskStopOut(parseInt(e.target.value) || 30)}
                        min={10}
                        max={100}
                        required
                        className="w-full bg-nexus-bg border border-white/10 text-white rounded-lg p-2.5 text-xs focus:outline-none focus:border-nexus-pur"
                      />
                    </div>
                  </div>
                  <div className="text-xs text-gray-400 leading-relaxed font-normal bg-nexus-bg p-3 rounded-xl border border-white/5">
                    <span className="font-bold text-white block mb-1">Impact of Margin Adjustment:</span>
                    Modifying leverage limits will instantly re-calculate required margins across all open and pending contracts. Changes apply globally to newly opened positions.
                  </div>
                  <button
                    type="submit"
                    className="w-fit px-6 py-2.5 bg-gradient-to-r from-nexus-pur to-nexus-blu text-white font-bold text-xs rounded-xl hover:shadow-lg transition cursor-pointer"
                  >
                    Save Changes
                  </button>
                </form>
              </HorizonCard>
            )}

            {/* Sub Tab: Liquidity settings */}
            {riskSubTab === 'liquidity' && (
              <HorizonCard extra="p-6 bg-nexus-sf border border-white/5 max-w-xl">
                <h3 className="text-lg font-bold text-white mb-4">Bid/Ask Spread Markups Control</h3>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    handlePillarAction('spread_markup', 'global', `Spread markup added: ${riskMarkup} pips`);
                    toast.success('Global spreads markup updated!');
                  }}
                  className="flex flex-col gap-6"
                >
                  <div>
                    <label className="text-xs text-gray-400 font-bold block mb-1">Global Markup Spread (Pips)</label>
                    <input
                      type="number"
                      value={riskMarkup}
                      onChange={(e) => setRiskMarkup(parseFloat(e.target.value) || 1.0)}
                      min={0.1}
                      max={10.0}
                      step={0.1}
                      required
                      className="w-full bg-nexus-bg border border-white/10 text-white rounded-lg p-2.5 text-xs focus:outline-none focus:border-nexus-pur font-mono font-bold"
                    />
                  </div>
                  <div className="text-xs text-gray-400 leading-relaxed font-normal bg-nexus-bg p-3 rounded-xl border border-white/5">
                    <span className="font-bold text-white block mb-1">Spread Markups Policy:</span>
                    Spreads markup defines the broker commission spread layered on top of liquidity provider raw bid/ask streams. A 1.5 pips markup applies $15.00 per lot traded.
                  </div>
                  <button
                    type="submit"
                    className="w-fit px-6 py-2.5 bg-gradient-to-r from-nexus-pur to-nexus-blu text-white font-bold text-xs rounded-xl hover:shadow-lg transition cursor-pointer"
                  >
                    Update Markups
                  </button>
                </form>
              </HorizonCard>
            )}
          </div>
        )}

        {adminTab === 'finance-accounting' && (
          <div className="flex flex-col gap-6 w-full">
            {/* Sub Tabs */}
            <div className="flex items-center gap-2 bg-[#16181d] border border-white/5 p-1 rounded-xl w-fit">
              <button
                onClick={() => setFinanceSubTab('gateways')}
                className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${
                  financeSubTab === 'gateways' ? 'bg-[#8b5cf6] text-white' : 'text-gray-400 hover:text-white'
                }`}
              >
                Payment Gateways (PSP)
              </button>
              <button
                onClick={() => setFinanceSubTab('ledger')}
                className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${
                  financeSubTab === 'ledger' ? 'bg-[#8b5cf6] text-white' : 'text-gray-400 hover:text-white'
                }`}
              >
                Custody Wallets & Ledger
              </button>
              <button
                onClick={() => setFinanceSubTab('reconciliation')}
                className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${
                  financeSubTab === 'reconciliation' ? 'bg-[#8b5cf6] text-white' : 'text-gray-400 hover:text-white'
                }`}
              >
                NAV Reconciliation Engine
              </button>
            </div>

            {/* Sub Tab: Gateways */}
            {financeSubTab === 'gateways' && (
              <div className="flex flex-col gap-6 w-full">
                <HorizonCard extra="p-6 bg-nexus-sf border border-white/5">
                  <h3 className="text-lg font-bold text-white mb-4">Payment Service Provider (PSP) Connections</h3>
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs border-collapse">
                      <thead>
                        <tr className="border-b border-white/5 text-gray-400 font-bold uppercase">
                          <th className="py-2.5">Gateway Provider</th>
                          <th className="py-2.5">Supported Currencies</th>
                          <th className="py-2.5">Volume Settled Today</th>
                          <th className="py-2.5">Status</th>
                          <th className="py-2.5">Gateway Action</th>
                        </tr>
                      </thead>
                      <tbody>
                        {pillarData?.gateways?.map((item: any) => (
                          <tr key={item.id} className="border-b border-white/5 hover:bg-white/2 transition">
                            <td className="py-3 font-bold text-white">{item.name}</td>
                            <td className="py-3 text-nexus-blu font-bold">{item.currency}</td>
                            <td className="py-3 font-mono font-bold text-green-400">
                              {item.id === 'mpesa' ? 'KES' : '$'} {item.processed_today.toLocaleString()}
                            </td>
                            <td className="py-3">
                              <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                                item.active ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'
                              }`}>
                                {item.active ? 'Active' : 'Offline'}
                              </span>
                            </td>
                            <td className="py-3">
                              <button
                                onClick={() => handlePillarAction('psp_toggle', item.id, item.active ? 'Disabled' : 'Enabled')}
                                className={`px-3 py-1 text-xs font-bold rounded-lg border transition cursor-pointer ${
                                  item.active
                                    ? 'bg-red-500/10 hover:bg-red-500/20 text-red-400 border-red-500/20'
                                    : 'bg-green-500/10 hover:bg-green-500/20 text-green-400 border-green-500/20'
                                }`}
                              >
                                {item.active ? 'Deactivate Gateway' : 'Activate Gateway'}
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </HorizonCard>

                {/* Live PSP Transactions Log */}
                <HorizonCard extra="p-6 bg-nexus-sf border border-white/5">
                  <h3 className="text-lg font-bold text-white mb-4">Live PSP Transaction Ledger</h3>
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs border-collapse">
                      <thead>
                        <tr className="border-b border-white/5 text-gray-400 font-bold uppercase">
                          <th className="py-2.5">User</th>
                          <th className="py-2.5">Gateway Provider</th>
                          <th className="py-2.5">Amount Settled</th>
                          <th className="py-2.5">Provider Reference</th>
                          <th className="py-2.5">Status</th>
                          <th className="py-2.5">Timestamp</th>
                        </tr>
                      </thead>
                      <tbody>
                        {paymentsList.length === 0 ? (
                          <tr>
                            <td colSpan={6} className="py-8 text-center text-gray-500">No PSP transactions recorded.</td>
                          </tr>
                        ) : (
                          paymentsList.map((item) => (
                            <tr key={item.id} className="border-b border-white/5 hover:bg-white/2 transition">
                              <td className="py-3 font-bold text-white">
                                <div>{item.username}</div>
                                <div className="text-[10px] text-gray-500 font-normal">{item.email}</div>
                              </td>
                              <td className="py-3 text-gray-300 uppercase">{item.provider}</td>
                              <td className="py-3 font-bold text-green-400">
                                {item.provider === 'mpesa' ? 'KES' : '$'} {item.amount}
                              </td>
                              <td className="py-3 text-gray-400 font-mono">{item.reference}</td>
                              <td className="py-3">
                                <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-green-500/10 text-green-400">
                                  {item.status.toUpperCase()}
                                </span>
                              </td>
                              <td className="py-3 text-gray-500 font-mono">{item.created_at?.slice(0, 16)}</td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </HorizonCard>
              </div>
            )}

            {/* Sub Tab: Ledger custody list */}
            {financeSubTab === 'ledger' && (
              <HorizonCard extra="p-6 bg-nexus-sf border border-white/5">
                <h3 className="text-lg font-bold text-white mb-2">Custodial Vault Ledger</h3>
                <div className="text-xs text-gray-500 font-normal mb-4">
                  Supervise cold storage nodes, regional banking API balances, and operational balances.
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5">
                  {pillarData?.wallets?.map((item: any, i: number) => (
                    <div key={i} className="p-4 bg-nexus-bg border border-white/5 rounded-xl flex flex-col gap-1">
                      <div className="text-[10px] text-gray-500 font-bold uppercase tracking-wider">{item.name}</div>
                      <div className="text-sm font-extrabold text-white mt-1">{item.balance}</div>
                    </div>
                  ))}
                </div>
              </HorizonCard>
            )}

            {/* Sub Tab: Reconciliation NAV calculations */}
            {financeSubTab === 'reconciliation' && (
              <HorizonCard extra="p-6 bg-[#16181d] border border-white/5 max-w-xl">
                <h3 className="text-lg font-bold text-white mb-4">Net Asset Value (NAV) & Daily Settler</h3>
                <div className="flex flex-col gap-4">
                  <div className="p-4 bg-nexus-bg border border-white/5 rounded-xl flex items-center justify-between">
                    <div>
                      <div className="text-[10px] text-gray-500 uppercase font-bold">Unsettled Commissions</div>
                      <div className="text-lg font-extrabold text-white mt-1">$1,234.50</div>
                    </div>
                    <button
                      onClick={() => {
                        handlePillarAction('reconciliation_nav', 'global_commissions', 'Settled');
                        toast.success('Successfully reconciled and swept commissions into payout balance');
                      }}
                      className="px-4 py-2 bg-nexus-pur hover:bg-nexus-pur/80 text-white font-bold text-xs rounded-xl transition cursor-pointer"
                    >
                      Settle Accounts
                    </button>
                  </div>
                  <div className="text-xs text-gray-400 leading-relaxed font-normal">
                    The reconciliation engine verifies trade fee ledger balances against MT5 bridges. Clicking settle computes swaps, accrues broker commission fees, and updates ledger balances.
                  </div>
                </div>
              </HorizonCard>
            )}
          </div>
        )}

        {adminTab === 'system-admin' && (
          <div className="flex flex-col gap-6 w-full">
            {/* Sub Tabs */}
            <div className="flex items-center gap-2 bg-[#16181d] border border-white/5 p-1 rounded-xl w-fit flex-wrap">
              <button
                onClick={() => setSystemSubTab('telemetry')}
                className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${
                  systemSubTab === 'telemetry' ? 'bg-[#8b5cf6] text-white' : 'text-gray-400 hover:text-white'
                }`}
              >
                Telemetry & Telemetry
              </button>
              <button
                onClick={() => setSystemSubTab('rbac')}
                className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${
                  systemSubTab === 'rbac' ? 'bg-[#8b5cf6] text-white' : 'text-gray-400 hover:text-white'
                }`}
              >
                Role Permissions (RBAC)
              </button>
              <button
                onClick={() => setSystemSubTab('broadcasts')}
                className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${
                  systemSubTab === 'broadcasts' ? 'bg-[#8b5cf6] text-white' : 'text-gray-400 hover:text-white'
                }`}
              >
                Broadcast announcements
              </button>
              <button
                onClick={() => setSystemSubTab('mt5')}
                className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${
                  systemSubTab === 'mt5' ? 'bg-[#8b5cf6] text-white' : 'text-gray-400 hover:text-white'
                }`}
              >
                MetaTrader 5 Settings
              </button>
              <button
                onClick={() => setSystemSubTab('gift-codes')}
                className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${
                  systemSubTab === 'gift-codes' ? 'bg-[#8b5cf6] text-white' : 'text-gray-400 hover:text-white'
                }`}
              >
                Gift Codes
              </button>
              <button
                onClick={() => setSystemSubTab('bots')}
                className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${
                  systemSubTab === 'bots' ? 'bg-[#8b5cf6] text-white' : 'text-gray-400 hover:text-white'
                }`}
              >
                AI Robots Controls
              </button>
            </div>

            {/* Sub Tab: Telemetry */}
            {systemSubTab === 'telemetry' && (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5 w-full">
                <HorizonCard extra="p-6 bg-nexus-sf border border-white/5 flex flex-col gap-2">
                  <Server className="w-8 h-8 text-nexus-blu" />
                  <div className="text-xs text-gray-500 font-bold uppercase">Main Server Load</div>
                  <div className="text-xl font-extrabold text-white mt-1">24.5%</div>
                </HorizonCard>
                <HorizonCard extra="p-6 bg-nexus-sf border border-white/5 flex flex-col gap-2">
                  <Activity className="w-8 h-8 text-green-400" />
                  <div className="text-xs text-gray-500 font-bold uppercase">Bridge Websockets</div>
                  <div className="text-xl font-extrabold text-white mt-1">1,482 channels</div>
                </HorizonCard>
                <HorizonCard extra="p-6 bg-nexus-sf border border-white/5 flex flex-col gap-2">
                  <Terminal className="w-8 h-8 text-nexus-pur" />
                  <div className="text-xs text-gray-500 font-bold uppercase">Main DB Latency</div>
                  <div className="text-xl font-extrabold text-white mt-1">2.4ms</div>
                </HorizonCard>
                <HorizonCard extra="p-6 bg-nexus-sf border border-white/5 flex flex-col gap-2">
                  <CheckCircle2 className="w-8 h-8 text-emerald-400" />
                  <div className="text-xs text-gray-500 font-bold uppercase">System Uptime</div>
                  <div className="text-xl font-extrabold text-white mt-1">99.98%</div>
                </HorizonCard>
              </div>
            )}

            {/* Sub Tab: RBAC Role Permissions */}
            {systemSubTab === 'rbac' && (
              <HorizonCard extra="p-6 bg-nexus-sf border border-white/5">
                <h3 className="text-lg font-bold text-white mb-2">Role Based Access Control (RBAC) Permissions Matrix</h3>
                <div className="text-xs text-gray-500 font-normal mb-4">
                  Modify module access privileges assigned to structural broker staff members roles.
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs border-collapse">
                    <thead>
                      <tr className="border-b border-white/5 text-gray-400 font-bold uppercase">
                        <th className="py-2.5">Staff Role</th>
                        <th className="py-2.5 text-center">Client Accounts (Read)</th>
                        <th className="py-2.5 text-center">Client Accounts (Write)</th>
                        <th className="py-2.5 text-center">Trade OMS (Read)</th>
                        <th className="py-2.5 text-center">Trade OMS (Write)</th>
                        <th className="py-2.5 text-center">Finance Billing (Read)</th>
                        <th className="py-2.5 text-center">Finance Billing (Write)</th>
                        <th className="py-2.5 text-center">Risk Settings (Write)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {['admin', 'support', 'compliance', 'dealer'].map((role) => (
                        <tr key={role} className="border-b border-white/5 hover:bg-white/2 transition">
                          <td className="py-3 font-bold text-white uppercase">{role}</td>
                          <td className="py-3 text-center">
                            <input
                              type="checkbox"
                              defaultChecked={pillarData?.rbac?.[role]?.includes('client_read')}
                              onChange={() => handlePillarAction('rbac_toggle', role, 'client_read')}
                              className="rounded border-white/10 text-[#8b5cf6] focus:ring-0"
                            />
                          </td>
                          <td className="py-3 text-center">
                            <input
                              type="checkbox"
                              defaultChecked={pillarData?.rbac?.[role]?.includes('client_write')}
                              onChange={() => handlePillarAction('rbac_toggle', role, 'client_write')}
                              className="rounded border-white/10 text-[#8b5cf6] focus:ring-0"
                            />
                          </td>
                          <td className="py-3 text-center">
                            <input
                              type="checkbox"
                              defaultChecked={pillarData?.rbac?.[role]?.includes('trade_read')}
                              onChange={() => handlePillarAction('rbac_toggle', role, 'trade_read')}
                              className="rounded border-white/10 text-[#8b5cf6] focus:ring-0"
                            />
                          </td>
                          <td className="py-3 text-center">
                            <input
                              type="checkbox"
                              defaultChecked={pillarData?.rbac?.[role]?.includes('trade_write')}
                              onChange={() => handlePillarAction('rbac_toggle', role, 'trade_write')}
                              className="rounded border-white/10 text-[#8b5cf6] focus:ring-0"
                            />
                          </td>
                          <td className="py-3 text-center">
                            <input
                              type="checkbox"
                              defaultChecked={pillarData?.rbac?.[role]?.includes('billing_read')}
                              onChange={() => handlePillarAction('rbac_toggle', role, 'billing_read')}
                              className="rounded border-white/10 text-[#8b5cf6] focus:ring-0"
                            />
                          </td>
                          <td className="py-3 text-center">
                            <input
                              type="checkbox"
                              defaultChecked={pillarData?.rbac?.[role]?.includes('billing_write')}
                              onChange={() => handlePillarAction('rbac_toggle', role, 'billing_write')}
                              className="rounded border-white/10 text-[#8b5cf6] focus:ring-0"
                            />
                          </td>
                          <td className="py-3 text-center">
                            <input
                              type="checkbox"
                              defaultChecked={pillarData?.rbac?.[role]?.includes('risk_write')}
                              onChange={() => handlePillarAction('rbac_toggle', role, 'risk_write')}
                              className="rounded border-white/10 text-[#8b5cf6] focus:ring-0"
                            />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </HorizonCard>
            )}

            {/* Sub Tab: Broadcast Announcements */}
            {systemSubTab === 'broadcasts' && (
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 w-full">
                {/* Dispatch form */}
                <HorizonCard extra="p-6 bg-nexus-sf border border-white/5 h-fit">
                  <h3 className="text-lg font-bold text-white flex items-center gap-2 mb-4">
                    <Megaphone className="text-nexus-pur animate-pulse" /> Dispatch Broadcast
                  </h3>
                  <form onSubmit={handleSendBroadcast} className="flex flex-col gap-4">
                    <div>
                      <label className="text-xs text-gray-400 font-bold block mb-1">Broadcast Title</label>
                      <input
                        type="text"
                        value={broadcastTitle}
                        onChange={(e) => setBroadcastTitle(e.target.value)}
                        placeholder="e.g. Critical MT5 System Upgrade"
                        required
                        className="w-full bg-nexus-bg border border-white/10 text-white rounded-lg p-2 text-xs focus:outline-none focus:border-nexus-pur"
                      />
                    </div>
                    <div>
                      <label className="text-xs text-gray-400 font-bold block mb-1">Message Body</label>
                      <textarea
                        value={broadcastBody}
                        onChange={(e) => setBroadcastBody(e.target.value)}
                        placeholder="Type announcements details here..."
                        required
                        rows={4}
                        className="w-full bg-nexus-bg border border-white/10 text-white rounded-lg p-2 text-xs focus:outline-none focus:border-nexus-pur"
                      />
                    </div>
                    <div>
                      <label className="text-xs text-gray-400 font-bold block mb-1">Target Segment</label>
                      <select
                        value={broadcastSegment}
                        onChange={(e) => setBroadcastSegment(e.target.value)}
                        className="w-full bg-nexus-bg border border-white/10 text-white rounded-lg p-2 text-xs focus:outline-none focus:border-nexus-pur font-bold"
                      >
                        <option value="all">All Members</option>
                        <option value="free">Free Tier only</option>
                        <option value="pro">Pro Tier only</option>
                        <option value="admin">Administrators</option>
                      </select>
                    </div>
                    <div>
                      <label className="text-xs text-gray-400 font-bold block mb-1">Dispatch Channel</label>
                      <select
                        value={broadcastChannel}
                        onChange={(e) => setBroadcastChannel(e.target.value)}
                        className="w-full bg-nexus-bg border border-white/10 text-white rounded-lg p-2 text-xs focus:outline-none focus:border-nexus-pur font-bold"
                      >
                        <option value="in-app">In-App Notification</option>
                        <option value="email">Direct Email blast</option>
                        <option value="both">Both Channels</option>
                      </select>
                    </div>
                    <button
                      type="submit"
                      disabled={sendingBroadcast}
                      className="w-full py-2.5 bg-gradient-to-r from-nexus-pur to-nexus-blu text-white font-bold text-xs rounded-xl hover:shadow-lg transition cursor-pointer"
                    >
                      {sendingBroadcast ? 'Dispatching...' : 'Dispatch Announcement'}
                    </button>
                  </form>
                </HorizonCard>

                {/* Dispatch logs */}
                <HorizonCard extra="lg:col-span-2 p-6 bg-nexus-sf border border-white/5">
                  <h3 className="text-lg font-bold text-white flex items-center gap-2 mb-4">
                    <Database className="text-nexus-pur" /> Dispatch History Log
                  </h3>
                  <div className="flex flex-col gap-4 max-h-[500px] overflow-y-auto pr-2">
                    {broadcastsList.length === 0 ? (
                      <div className="text-xs text-gray-500 py-6 text-center">No broadcasts dispatched yet.</div>
                    ) : (
                      broadcastsList.map((ann) => (
                        <div key={ann.id} className="p-4 bg-nexus-bg border border-white/5 rounded-xl text-xs flex flex-col gap-2">
                          <div className="flex justify-between items-center text-[10px] text-gray-500">
                            <span className="font-bold text-nexus-pur bg-nexus-pur/10 px-2 py-0.5 rounded">
                              Segment: {ann.segment.toUpperCase()} · Channel: {ann.channel.toUpperCase()}
                            </span>
                            <span>{ann.created_at.slice(0, 16)}</span>
                          </div>
                          <h4 className="font-bold text-white text-sm">{ann.title}</h4>
                          <p className="text-gray-400 font-normal leading-relaxed">{ann.body}</p>
                          <div className="text-[10px] text-gray-500 mt-1">
                            Dispatched to: <span className="text-white font-bold">{ann.sent_count} accounts</span>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </HorizonCard>
              </div>
            )}

            {/* Sub Tab: MT5 Settings */}
            {systemSubTab === 'mt5' && (
              <HorizonCard extra="p-6 bg-nexus-sf border border-white/5 max-w-xl">
                <h3 className="text-lg font-bold text-white flex items-center gap-2 mb-4">
                  <Terminal className="text-nexus-pur" /> MetaTrader 5 Terminal Control
                </h3>
                
                <div className="flex flex-col gap-6">
                  <div className="p-4 bg-nexus-bg border border-white/5 rounded-xl flex items-center justify-between">
                    <div>
                      <div className="text-xs text-gray-500 uppercase font-bold">Execution Engine Status</div>
                      <div className={`text-lg font-extrabold mt-1 uppercase ${
                        mt5Status === 'connected' ? 'text-green-400' : 'text-red-400'
                      }`}>
                        {mt5Status}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => handleMt5Control('start')}
                        disabled={mt5Status === 'connected'}
                        className="p-3 bg-green-500/10 text-green-400 border border-green-500/20 rounded-xl hover:bg-green-500/20 transition cursor-pointer"
                        title="Start MT5 Connector"
                      >
                        <Power size={20} />
                      </button>
                      <button
                        onClick={() => handleMt5Control('stop')}
                        disabled={mt5Status === 'disconnected'}
                        className="p-3 bg-red-500/10 text-red-400 border border-red-500/20 rounded-xl hover:bg-red-500/20 transition cursor-pointer"
                        title="Stop Execution Engine"
                      >
                        <Power size={20} />
                      </button>
                    </div>
                  </div>

                  <div className="text-xs text-gray-400 leading-relaxed font-normal">
                    <span className="font-bold text-white block mb-1">Configuration Guidelines:</span>
                    The MT5 Server requires local middleware. Ensure the MetaTrader terminal software is running on the host execution server and ports are active. Custom logs can be inspected from the system exception logs in the overview panel.
                  </div>
                </div>
              </HorizonCard>
            )}

            {/* Sub Tab: Gift Codes */}
            {systemSubTab === 'gift-codes' && (
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 w-full">
                {/* Generate Gift Code */}
                <HorizonCard extra="p-6 bg-nexus-sf border border-white/5 h-fit">
                  <h3 className="text-lg font-bold text-white flex items-center gap-2 mb-4">
                    <Plus className="text-nexus-pur animate-pulse" /> Generate Gift Codes
                  </h3>
                  <form onSubmit={handleGenerateGiftCodes} className="flex flex-col gap-4">
                    <div>
                      <label className="text-xs text-gray-400 font-bold block mb-1">Access Duration (Days)</label>
                      <input
                        type="number"
                        value={giftDays}
                        onChange={(e) => setGiftDays(parseInt(e.target.value) || 30)}
                        min={1}
                        max={365}
                        required
                        className="w-full bg-nexus-bg border border-white/10 text-white rounded-lg p-2 text-xs focus:outline-none focus:border-nexus-pur"
                      />
                    </div>
                    <div>
                      <label className="text-xs text-gray-400 font-bold block mb-1">Quantity</label>
                      <input
                        type="number"
                        value={giftCount}
                        onChange={(e) => setGiftCount(parseInt(e.target.value) || 1)}
                        min={1}
                        max={20}
                        required
                        className="w-full bg-nexus-bg border border-white/10 text-white rounded-lg p-2 text-xs focus:outline-none focus:border-nexus-pur"
                      />
                    </div>
                    <div>
                      <label className="text-xs text-gray-400 font-bold block mb-1">Administrative Note</label>
                      <input
                        type="text"
                        value={giftNote}
                        onChange={(e) => setGiftNote(e.target.value)}
                        placeholder="e.g. Promo campaign, Support compensation"
                        className="w-full bg-nexus-bg border border-white/10 text-white rounded-lg p-2 text-xs focus:outline-none focus:border-nexus-pur"
                      />
                    </div>
                    <button
                      type="submit"
                      disabled={generatingGift}
                      className="w-full py-2.5 bg-gradient-to-r from-nexus-pur to-nexus-blu text-white font-bold text-xs rounded-xl hover:shadow-lg transition cursor-pointer"
                    >
                      {generatingGift ? 'Generating...' : 'Generate Codes'}
                    </button>
                  </form>

                  {giftCodesGenerated.length > 0 && (
                    <div className="mt-6 p-4 bg-green-500/10 border border-green-500/20 rounded-xl">
                      <div className="text-xs font-bold text-green-400 mb-2">Generated Codes:</div>
                      <div className="flex flex-col gap-1">
                        {giftCodesGenerated.map((code) => (
                          <div key={code} className="flex justify-between items-center text-xs">
                            <code className="text-white font-mono bg-black/30 px-2 py-0.5 rounded select-all">{code}</code>
                            <button
                              onClick={() => {
                                navigator.clipboard.writeText(code);
                                toast.success('Copied code!');
                              }}
                              className="text-[10px] text-nexus-blu font-bold hover:underline"
                            >
                              Copy
                            </button>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </HorizonCard>

                {/* Gift Codes List */}
                <HorizonCard extra="lg:col-span-2 p-6 bg-nexus-sf border border-white/5">
                  <h3 className="text-lg font-bold text-white flex items-center gap-2 mb-4">
                    <Database className="text-nexus-pur" /> Gift Codes Inventory
                  </h3>
                  <div className="overflow-x-auto w-full">
                    <table className="w-full text-left text-xs border-collapse">
                      <thead>
                        <tr className="border-b border-white/5 text-gray-400 font-bold">
                          <th className="py-2.5">Code</th>
                          <th className="py-2.5">Duration</th>
                          <th className="py-2.5">Status</th>
                          <th className="py-2.5">Redeemed By</th>
                          <th className="py-2.5">Note</th>
                        </tr>
                      </thead>
                      <tbody>
                        {giftCodesList.length === 0 ? (
                          <tr>
                            <td colSpan={5} className="py-8 text-center text-gray-500">No gift codes found.</td>
                          </tr>
                        ) : (
                          giftCodesList.map((item) => (
                            <tr key={item.id} className="border-b border-white/5 hover:bg-white/2 transition">
                              <td className="py-3 font-mono font-bold text-white">{item.code}</td>
                              <td className="py-3 text-gray-300">{item.days} Days</td>
                              <td className="py-3">
                                <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                                  item.used ? 'bg-red-500/10 text-red-400' : 'bg-green-500/10 text-green-400'
                                }`}>
                                  {item.used ? 'Redeemed' : 'Active'}
                                </span>
                              </td>
                              <td className="py-3">
                                {item.used ? (
                                  <div className="flex flex-col">
                                    <span className="text-white font-bold">{item.used_by}</span>
                                    <span className="text-[10px] text-gray-500">{item.used_at?.slice(0, 16)}</span>
                                  </div>
                                ) : '-'}
                              </td>
                              <td className="py-3 text-gray-400 italic max-w-[150px] truncate" title={item.note || ''}>
                                {item.note || '-'}
                              </td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </HorizonCard>
              </div>
            )}

            {/* Sub Tab: AI Robots Controls */}
            {systemSubTab === 'bots' && (
              <HorizonCard extra="p-6 bg-nexus-sf border border-white/5 w-full">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <h3 className="text-lg font-bold text-white flex items-center gap-2">
                      <Database className="text-nexus-pur" /> Registered Algorithmic Robots
                    </h3>
                    <p className="text-xs text-gray-400 mt-1">
                      Activate, deactivate, or tune parameters for deployment.
                    </p>
                  </div>
                </div>
                <div className="overflow-x-auto w-full">
                  <table className="w-full text-left text-xs border-collapse">
                    <thead>
                      <tr className="border-b border-white/5 text-gray-400 font-bold uppercase">
                        <th className="py-2.5">Robot Name</th>
                        <th className="py-2.5">Asset Class</th>
                        <th className="py-2.5">Interval</th>
                        <th className="py-2.5">Status</th>
                        <th className="py-2.5">Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pillarData?.bots_list?.length > 0 ? (
                        pillarData.bots_list.map((bot: any) => (
                          <tr key={bot.id} className="border-b border-white/5 hover:bg-white/2 transition">
                            <td className="py-3">
                              <div className="font-bold text-white">{bot.name}</div>
                              <div className="text-[10px] text-gray-500 font-normal max-w-[300px] truncate" title={bot.description}>{bot.description}</div>
                            </td>
                            <td className="py-3 text-nexus-blu font-bold">{bot.asset_class}</td>
                            <td className="py-3 text-gray-300 font-mono">{bot.interval}</td>
                            <td className="py-3">
                              <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                                bot.is_active ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'
                              }`}>
                                {bot.is_active ? 'Active' : 'Halted'}
                              </span>
                            </td>
                            <td className="py-3">
                              <button
                                onClick={() => handlePillarAction('bot_toggle', bot.slug, bot.is_active ? 'Disabled' : 'Enabled')}
                                className={`px-3 py-1 text-xs font-bold rounded-lg border transition cursor-pointer ${
                                  bot.is_active
                                    ? 'bg-red-500/10 hover:bg-red-500/20 text-red-400 border-red-500/20'
                                    : 'bg-green-500/10 hover:bg-green-500/20 text-green-400 border-green-500/20'
                                }`}
                              >
                                {bot.is_active ? 'Deactivate Robot' : 'Activate Robot'}
                              </button>
                            </td>
                          </tr>
                        ))
                      ) : (
                        <tr>
                          <td colSpan={5} className="py-8 text-center text-gray-500">No trading robots loaded.</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </HorizonCard>
            )}
          </div>
        )}
      </div>
  );
};