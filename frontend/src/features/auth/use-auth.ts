import { useContext } from "react";
import { AuthContext, type AuthState } from "@/features/auth/auth-context";
import type { Permission } from "@/types/domain";

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth trebuie folosit în interiorul <AuthProvider>.");
  }
  return context;
}

/**
 * Ascunde acțiunile pe care utilizatorul nu le poate executa.
 * Este doar ergonomie de interfață — regula obligatorie se aplică în backend.
 */
export function useHasPermission(permission: Permission): boolean {
  const { user } = useAuth();
  return user?.permissions.includes(permission) ?? false;
}
