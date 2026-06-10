import type { Metadata } from "next";
import "./globals.css";
import { ClientProviders } from "@/components/client-providers";

export const metadata: Metadata = {
  title: "Tax-Planning-Ops",
  description: "Workspace-scoped tax planning operations for Unicorn Commander.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <ClientProviders>{children}</ClientProviders>
      </body>
    </html>
  );
}
