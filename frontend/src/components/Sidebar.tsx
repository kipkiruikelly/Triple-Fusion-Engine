import { NavLink, useLocation } from 'react-router-dom';
import { 
  Activity, Briefcase, BarChart2, BookOpen, Settings, Cpu, Zap, Search, Layers, 
  ShieldCheck, Users, Sliders, ShieldAlert, DollarSign
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';

export const Sidebar: React.FC = () => {
  const { user } = useAuth();
  const location = useLocation();
  const isAdminView = location.pathname.startsWith('/admin');
  
  const navItems = isAdminView ? [
    { name: 'Overview', path: '/admin?tab=overview', icon: <Layers size={20} /> },
    { name: 'Client & User Management', path: '/admin?tab=client-management', icon: <Users size={20} /> },
    { name: 'TOMS/OMS Control', path: '/admin?tab=trade-management', icon: <Sliders size={20} /> },
    { name: 'Risk & Exposure', path: '/admin?tab=risk-management', icon: <ShieldAlert size={20} /> },
    { name: 'Finance & Ledgers', path: '/admin?tab=finance-accounting', icon: <DollarSign size={20} /> },
    { name: 'System Admin & Settings', path: '/admin?tab=system-admin', icon: <Settings size={20} /> },
  ] : [
    { name: 'Portfolio', path: '/portfolio', icon: <Briefcase size={20} /> },
    { name: 'Live Trading', path: '/live', icon: <Zap size={20} /> },
    { name: 'Journal', path: '/journal', icon: <BookOpen size={20} /> },
    { name: 'Markets', path: '/markets', icon: <BarChart2 size={20} /> },
    { name: 'Research', path: '/research', icon: <Search size={20} /> },
    { name: 'Screener', path: '/screener', icon: <Activity size={20} /> },
    { name: 'AI Robots', path: '/bots', icon: <Cpu size={20} /> },
    { name: 'Strategy Tools', path: '/tools', icon: <Layers size={20} /> },
    { name: 'Settings', path: '/settings', icon: <Settings size={20} /> },
  ];

  if (!isAdminView && user && user.role_level >= 3) {
    navItems.push({ name: 'Admin Console', path: '/admin', icon: <ShieldCheck size={20} /> });
  }

  return (
    <div className="w-64 h-full bg-nexus-sf border-r border-nexus-border flex flex-col shrink-0">
      <div className="flex-1 overflow-y-auto py-4">
        <nav className="flex flex-col gap-2 px-4">
          {navItems.map((item) => (
            <NavLink
              key={item.name}
              to={item.path}
              className={() => {
                const isItemActive = isAdminView
                  ? location.search === item.path.substring(6) || (location.search === '' && item.path.endsWith('overview'))
                  : location.pathname === item.path;
                return `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
                  isItemActive 
                    ? 'bg-nexus-bg2 text-nexus-pur' 
                    : 'text-nexus-muted hover:text-nexus-white hover:bg-nexus-bg'
                }`;
              }}
            >
              {item.icon}
              <span className="font-medium text-xs md:text-sm">{item.name}</span>
            </NavLink>
          ))}
        </nav>
      </div>

      {isAdminView && (
        <div className="p-4 border-t border-nexus-border">
          <NavLink
            to="/portfolio"
            className="flex items-center justify-center gap-2 w-full py-2.5 bg-nexus-pur hover:bg-nexus-pur/80 text-white font-bold text-xs rounded-xl transition cursor-pointer"
          >
            ← Return to Workspace
          </NavLink>
        </div>
      )}
    </div>
  );
};
