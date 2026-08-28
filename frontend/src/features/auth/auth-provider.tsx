import { useCallback, useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { auth } from "@/api/endpoints";
import { setAuthToken } from "@/api/client";
import { AuthContext, type AuthState } from "@/features/auth/auth-context";
import type { CurrentUser } from "@/types/domain";

const SESSION_KEY = "contacrm.session";

/**
 * Sesiunea în modul `mock` este doar o simulare de development: nu verifică parola
 * și nu oferă nicio garanție de securitate. Autorizarea reală se face în backend,
 * la fiecare cerere. Ascunderea unui buton în interfață nu este o măsură de securitate.
 */
function readStoredSession(): CurrentUser | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    return raw ? (JSON.parse(raw) as CurrentUser) : null;
  } catch {
    return null;
  }
}

function writeStoredSession(user: CurrentUser | null) {
  try {
    if (user) localStorage.setItem(SESSION_KEY, JSON.stringify(user));
    else localStorage.removeItem(SESSION_KEY);
  } catch {
    // Persistarea sesiunii nu este critică pentru funcționare.
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(() => readStoredSession());
  const [isLoading, setIsLoading] = useState(false);
  const queryClient = useQueryClient();

  useEffect(() => {
    // Tokenul real va veni de la `/auth/login`; în mock ținem doar identitatea.
    setAuthToken(user ? `mock-session-${user.id}` : null);
  }, [user]);

  const login = useCallback(async (email: string, password: string) => {
    setIsLoading(true);
    try {
      const nextUser = await auth.login(email, password);
      setUser(nextUser);
      writeStoredSession(nextUser);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await auth.logout();
    } finally {
      setUser(null);
      writeStoredSession(null);
      queryClient.clear();
    }
  }, [queryClient]);

  const value = useMemo<AuthState>(
    () => ({ user, isLoading, login, logout }),
    [user, isLoading, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
