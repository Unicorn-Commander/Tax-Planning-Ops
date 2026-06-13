"use client";

// The root route resolves by posture (§0.5): solo/company → Your Plan (/home),
// firm → The Desk (/desk). A thin client redirector so the resolved home keeps
// a stable, shareable URL. (Old /dashboard etc. remain reachable as v1
// fallbacks during the v3 migration; they flip to redirects in Phase 3.)

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { usePosture, homeFor } from "@/lib/posture";

export default function HomeResolver() {
  const router = useRouter();
  const posture = usePosture();
  useEffect(() => {
    router.replace(homeFor(posture));
  }, [router, posture]);
  return (
    <div className="grid min-h-screen place-items-center">
      <div className="skeleton h-8 w-48" />
    </div>
  );
}
