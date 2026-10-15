import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, type ReactNode, useContext, useEffect } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { ApiError, api, setUnauthorizedHandler } from "./api";
import type { SessionInfo, User } from "./types";

type AuthState = { user: User | null; loading: boolean; logout: () => Promise<void> };
const AuthContext = createContext<AuthState>({ user: null, loading: true, logout: async () => {} });

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { data, isLoading } = useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return await api.get<SessionInfo>("/auth/me");
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: 60_000,
    retry: false,
  });

  useEffect(() => {
    setUnauthorizedHandler(() => {
      qc.setQueryData(["me"], null);
    });
  }, [qc]);

  const logout = async () => {
    try {
      await api.post("/auth/logout");
    } finally {
      qc.clear();
      qc.setQueryData(["me"], null);
      navigate("/admin/login");
    }
  };

  return (
    <AuthContext.Provider value={{ user: data?.user ?? null, loading: isLoading, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <p className="p-8 text-center text-steel-2">Loading…</p>;
  if (!user) return <Navigate to="/admin/login" replace state={{ from: location.pathname + location.search }} />;
  return <>{children}</>;
}
