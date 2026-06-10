"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuthStore, type User } from "@/lib/store";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const setUser = useAuthStore((state) => state.setUser);

  useEffect(() => {
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
