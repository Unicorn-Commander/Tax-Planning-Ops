"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuthStore, type User } from "@/lib/store";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const setUser = useAuthStore((state) => state.setUser);

  useEffect(() => {
    // Dev-only auto-login (gated by env; off in production). Lets local/headless
    // previews render authed screens against a STANDALONE backend without the
    // Keycloak round-trip.
    if (
      process.env.NEXT_PUBLIC_DEV_AUTOLOGIN === "1" &&
      !localStorage.getItem("access_token")
    ) {
      localStorage.setItem("access_token", "dev");
      localStorage.setItem(
        "user",
        JSON.stringify({ sub: "standalone-user", name: "Demo Advisor", email: "advisor@northstar.test" }),
      );
    }
    const token = localStorage.getItem("access_token");
    const userJson = localStorage.getItem("user");
    if (token && userJson) {
      try {
        setUser(JSON.parse(userJson) as User);
        if (pathname === "/auth/login") {
          router.replace("/dashboard");
        }
        return;
      } catch {
        localStorage.removeItem("access_token");
        localStorage.removeItem("user");
      }
    }
    setUser(null);
    if (pathname?.startsWith("/dashboard")) {
      router.replace("/auth/login");
    }
  }, [pathname, router, setUser]);

  return <>{children}</>;
}
