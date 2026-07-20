import { Bell, User, Sun } from 'lucide-react';

export const Header: React.FC = () => {
  return (
    <div className="h-16 bg-[#16181d] border-b border-[#2a2e39] flex items-center justify-between px-6 sticky top-0 z-10">
      <div className="flex-1">
        {/* Optional Search Bar or Breadcrumbs */}
      </div>
      
      <div className="flex items-center gap-4">
        {/* DEMO DATA BADGE */}
        <div className="hidden md:flex items-center gap-2 bg-[#ef4444]/10 border border-[#ef4444]/30 px-3 py-1 rounded text-[#ef4444] text-xs font-bold tracking-wider">
          <span className="w-2 h-2 rounded-full bg-[#ef4444] animate-pulse"></span>
          DEMO DATA
        </div>

        <button className="text-[#a0a5b1] hover:text-white transition-colors relative">
          <Bell size={20} />
          <span className="absolute -top-1 -right-1 bg-[#8b5cf6] w-2 h-2 rounded-full"></span>
        </button>
        
        <button className="text-[#a0a5b1] hover:text-white transition-colors">
          <Sun size={20} />
        </button>
        
        <div className="h-8 w-px bg-[#2a2e39] mx-2"></div>
        
        <div className="flex items-center gap-2 cursor-pointer group">
          <div className="w-8 h-8 rounded-full bg-[#2a2e39] flex items-center justify-center text-[#a0a5b1] group-hover:text-white transition-colors">
            <User size={16} />
          </div>
          <span className="text-sm font-medium text-[#a0a5b1] group-hover:text-white transition-colors">
            Trader Profile
          </span>
        </div>
      </div>
    </div>
  );
};
