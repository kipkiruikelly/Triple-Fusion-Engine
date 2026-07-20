import React, { createContext, useContext, useState, useEffect } from 'react';
import type { ReactNode } from 'react';
import { apiFetch } from '../utils/api';

export interface User {
  id: number;
  username: string;
  email: string;
  role: string;
  role_level: number;
  plan: string;
  status: string;
  theme_preference: string;
  alerts_enabled: boolean;
  xp: number;
  level: number;
  xp_into_level: number;
  current_streak: number;
  longest_streak: number;
  paper_trading_opted_in: boolean;
  is_pro: boolean;
  is_plus: boolean;
  predictions_remaining: number | null;
  predictions_today?: number;
  total_predictions?: number;
}


interface AuthContextType {
  user: User | null;
  loading: boolean;
  checkAuth: () => Promise<void>;
  logout: () => Promise<void>;
  setUser: React.Dispatch<React.SetStateAction<User | null>>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const checkAuth = async () => {
    try {
      const res = await fetch('/api/me', { credentials: 'include' });
      const data = await res.json();
      if (data.ok) {
        setUser(data.user);
        if (data.csrf_token) {
          localStorage.setItem('csrf_token', data.csrf_token);
        }
      } else {
        setUser(null);
        localStorage.removeItem('csrf_token');
      }
    } catch (err) {
      setUser(null);
      localStorage.removeItem('csrf_token');
    } finally {
      setLoading(false);
    }
  };

  const logout = async () => {
    try {
      await apiFetch('/api/logout', { method: 'POST', credentials: 'include' });
      setUser(null);
      localStorage.removeItem('csrf_token');
      window.location.href = '/login';
    } catch (err) {
      console.error('Logout failed', err);
    }
  };

  useEffect(() => {
    checkAuth();
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, checkAuth, logout, setUser }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
