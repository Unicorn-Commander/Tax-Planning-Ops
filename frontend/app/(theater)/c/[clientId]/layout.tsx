"use client";

import { use } from "react";
import { ClientOverviewProvider } from "@/components/client-overview";

export default function PresentClientLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ clientId: string }>;
}) {
  const { clientId } = use(params);
  return <ClientOverviewProvider clientId={clientId}>{children}</ClientOverviewProvider>;
}
