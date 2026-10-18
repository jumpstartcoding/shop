import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { Button, ErrorNote, Field } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import type { SessionInfo } from "../lib/types";

export function Login() {
  const { user } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const qc = useQueryClient();
  const navigate = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from ?? "/admin";

  const login = useMutation({
    mutationFn: () => api.post<SessionInfo>("/auth/login", { email, password }),
    onSuccess: (session) => {
      qc.setQueryData(["me"], session);
      navigate(from, { replace: true });
    },
  });

  if (user) return <Navigate to={from} replace />;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    login.mutate();
  };

  return (
    <main className="flex min-h-dvh flex-col bg-steel md:items-center md:justify-center">
      <div className="px-6 pt-14 pb-8 text-white md:pt-0 md:text-center">
        <img src="/favicon.svg" alt="" className="mb-4 h-12 w-12 md:mx-auto" />
        <h1 className="font-display text-4xl font-bold">Shop sign-in</h1>
      </div>
      <form
        onSubmit={submit}
        className="flex-1 space-y-4 rounded-t-2xl bg-sheet px-6 pt-8 pb-10 md:w-full md:max-w-sm md:flex-none md:rounded-2xl"
      >
        <ErrorNote error={login.error} />
        <Field label="Email">
          {(p) => (
            <input {...p} className="field" type="email" autoComplete="username" required value={email}
              onChange={(e) => setEmail(e.target.value)} />
          )}
        </Field>
        <Field label="Password">
          {(p) => (
            <input {...p} className="field" type="password" autoComplete="current-password" required
              value={password} onChange={(e) => setPassword(e.target.value)} />
          )}
        </Field>
        <Button type="submit" variant="primary" className="w-full" busy={login.isPending}>
          Sign in
        </Button>
      </form>
    </main>
  );
}
