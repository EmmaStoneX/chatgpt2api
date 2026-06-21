"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { getValidatedAuthSession } from "@/lib/auth-session";
import {
  clearStoredAuthSession,
  getStoredAuthSession,
  setStoredAuthSession,
  type StoredAuthSession,
} from "@/store/auth";

type AuthContextValue = {
  session: StoredAuthSession | null;
  isCheckingAuth: boolean;
  refreshSession: () => Promise<StoredAuthSession | null>;
  setSession: (session: StoredAuthSession) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSessionState] = useState<StoredAuthSession | null>(null);
  const [isCheckingAuth, setIsCheckingAuth] = useState(true);

  const refreshSession = useCallback(async () => {
    const nextSession = await getValidatedAuthSession({ clearOnFailure: false });
    if (nextSession) {
      setSessionState(nextSession);
    }
    return nextSession;
  }, []);

  const setSession = useCallback(async (nextSession: StoredAuthSession) => {
    await setStoredAuthSession(nextSession);
    setSessionState(nextSession);
  }, []);

  const logout = useCallback(async () => {
    await clearStoredAuthSession();
    setSessionState(null);
  }, []);

  useEffect(() => {
    let active = true;

    const loadStoredSession = async () => {
      const storedSession = await getStoredAuthSession();
      if (!active) {
        return;
      }

      setSessionState(storedSession);
      setIsCheckingAuth(false);

      if (storedSession) {
        void refreshSession();
      }
    };

    void loadStoredSession();
    return () => {
      active = false;
    };
  }, [refreshSession]);

  const value = useMemo(
    () => ({
      session,
      isCheckingAuth,
      refreshSession,
      setSession,
      logout,
    }),
    [isCheckingAuth, logout, refreshSession, session, setSession],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return context;
}
