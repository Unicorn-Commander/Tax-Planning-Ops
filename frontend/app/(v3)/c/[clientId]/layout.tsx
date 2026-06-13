"use client";

// The FILE shell (§0.5) — posture-agnostic, byte-identical for individual /
// company / firm-client. The file is the context: the FileTopbar carries the
// client crumb, and the whole subtree is scoped to the client's stable hue
// (--chue) so avatars + accents inherit it. Reuses the existing
// ClientOverviewProvider (extend, don't replace).

import { use } from "react";
import { ClientOverviewProvider } from "@/components/client-overview";
import { Env } from "@/components/kit";
import { hueForClient } from "@/components/kit";
import { FileTopbar } from "../../shell";

export default function FileLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ clientId: string }>;
}) {
  const { clientId } = use(params);
  return (
    <ClientOverviewProvider clientId={clientId}>
      <Env clientId={clientId} hue={hueForClient(clientId)} className="min-h-screen">
        <FileTopbar clientId={clientId} />
        <main className="min-w-0">{children}</main>
      </Env>
    </ClientOverviewProvider>
  );
}
