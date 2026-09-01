import { useCallback, useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { auth } from "@/api/endpoints";
import { apiMode, setAuthToken, setSessionLostHandler } from "@/api/client";
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
  // În `http`, ce scrie în localStorage este cel mult o presupunere: adevărul este
  // cookie-ul, iar el poate fi expirat sau revocat. Pornim de la ce știm, dar
  // întrebăm serverul înainte de a lăsa utilizatorul să lucreze.
  const [user, setUser] = useState<CurrentUser | null>(() => readStoredSession());
  const [isLoading, setIsLoading] = useState(false);
  const [isBootstrapping, setBootstrapping] = useState(apiMode() === "http");
  const queryClient = useQueryClient();

  useEffect(() => {
    // Antetul `Authorization` are rost doar în mock. În `http`, sesiunea este
    // cookie-ul httpOnly — un token inventat aici ar avea prioritate în fața lui
    // și ar face fiecare cerere să răspundă 401.
    if (apiMode() === "mock") {
      setAuthToken(user ? `mock-session-${user.id}` : null);
    }
  }, [user]);

  const forget = useCallback(() => {
    setUser(null);
    writeStoredSession(null);
    queryClient.clear();
  }, [queryClient]);

  // Când nici reîmprospătarea nu mai reușește, sesiunea chiar s-a terminat.
  useEffect(() => {
    setSessionLostHandler(forget);
    return () => setSessionLostHandler(null);
  }, [forget]);

  // Cine este utilizatorul îl spune serverul, nu localStorage-ul.
  useEffect(() => {
    if (apiMode() !== "http") return;
    let cancelled = false;

    void auth
      .me()
      .then((current) => {
        if (cancelled) return;
        setUser(current);
        writeStoredSession(current);
      })
      .catch(() => {
        if (!cancelled) forget();
      })
      .finally(() => {
        if (!cancelled) setBootstrapping(false);
      });

    return () => {
      cancelled = true;
    };
  }, [forget]);

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
      forget();
    }
  }, [forget]);

  const value = useMemo<AuthState>(
    () => ({ user, isLoading: isLoading || isBootstrapping, login, logout }),
    [user, isLoading, isBootstrapping, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
