"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import api from "@/lib/api";
import { useAuthStore } from "@/lib/store";

function CallbackInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const setUser = useAuthStore((state) => state.setUser);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = searchParams.get("token");
    if (!token) {
      setError("No token returned from Keycloak.");
      return;
    }
    localStorage.setItem("access_token", token);
    api
      .get("/me", { headers: { Authorization: `Bearer ${token}` } })
      .then((response) => {
        const user = {
          sub: response.data.sub,
          workspaces: response.data.authorized_workspace_ids,
        };
        localStorage.setItem("user", JSON.stringify(user));
        setUser(user);
        router.replace("/dashboard");
      })
      .catch(() => {
        localStorage.removeItem("access_token");
        setError("Could not complete sign-in.");
      });
  }, [router, searchParams, setUser]);

  if (error) return <p className="text-[var(--warning)]">{error}</p>;
  return <p className="text-[var(--muted)]">Completing sign-in...</p>;
}

export default function SsoCallbackPage() {
  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <Suspense fallback={<p className="text-[var(--muted)]">Completing sign-in...</p>}>
        <CallbackInner />
      </Suspense>
    </main>
  );
}
