import { createContext } from "react";
import type { CurrentUser } from "@/types/domain";

export type AuthState = {
  user: CurrentUser | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

export const AuthContext = createContext<AuthState | null>(null);
