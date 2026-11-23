"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import api from "@/lib/api";
import { useAuthStore } from "@/lib/store";
import { cleanCallbackUrl, parseTokenParams } from "@/app/auth/sso-callback-lib";

// Read the fragment and strip it from the address bar AT MODULE LOAD, before
// React renders. The tokens must not sit in the URL for a single paint (a
// third-party asset loaded during first render could echo them in a Referer),
// so this runs synchronously on import, not inside useEffect.
const initialTokens = parseTokenParams();
cleanCallbackUrl();

function CallbackInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const setUser = useAuthStore((state) => state.setUser);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const { token, refreshToken } = initialTokens;
    if (!token) {
      setError("No token returned from Keycloak.");
      return;
    }
    localStorage.setItem("access_token", token);
    // Keep the refresh token so the access token can be renewed silently
    // (see lib/api.ts) instead of bouncing to /auth/login when it expires.
    if (refreshToken) localStorage.setItem("refresh_token", refreshToken);
    api
      .get("/me", { headers: { Authorization: `Bearer ${token}` } })
      .then((response) => {
        const user = {
          sub: response.data.sub,
          workspaces: response.data.authorized_workspace_ids,
        };
        localStorage.setItem("user", JSON.stringify(user));
        setUser(user);
        // v3: land on the posture resolver (→ Desk for a firm, Your Plan for solo)
        router.replace("/");
      })
      .catch(() => {
        // A failed /me means the tokens are not a valid session. Remove BOTH
        // (a lingering refresh token would let a later renewal resurrect a
        // dead or attacker-supplied session).
        localStorage.removeItem("access_token");
        localStorage.removeItem("refresh_token");
        setError("Could not complete sign-in.");
      });
  }, [router, setUser]);
  // searchParams is only a Suspense boundary requirement here; the tokens were
  // already read from window.location (fragment) at module load.
  void searchParams;

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
