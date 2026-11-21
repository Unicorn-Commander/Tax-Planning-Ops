import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import { ClientProviders } from "@/components/client-providers";
import { ThemeToggle } from "@/components/theme";

/* Daylight & Paper type system:
   - Franklin = the instrument/UI voice (the 1040's own letterform heritage)
   - Source Serif 4 = the document/counsel voice (memos, present)
   - IBM Plex Mono = the ledger voice (figures, citations, hashes) */
const franklin = localFont({
  src: [
    {
      path: "../node_modules/@fontsource-variable/libre-franklin/files/libre-franklin-latin-wght-normal.woff2",
      weight: "100 900",
      style: "normal",
    },
  ],
  variable: "--font-franklin",
  display: "swap",
});
const sourceSerif = localFont({
  src: [
    {
      path: "../node_modules/@fontsource-variable/source-serif-4/files/source-serif-4-latin-wght-normal.woff2",
      weight: "100 900",
      style: "normal",
    },
    {
      path: "../node_modules/@fontsource-variable/source-serif-4/files/source-serif-4-latin-wght-italic.woff2",
      weight: "100 900",
      style: "italic",
    },
  ],
  variable: "--font-source-serif",
  display: "swap",
});
const plexMono = localFont({
  src: [
    {
      path: "../node_modules/@fontsource/ibm-plex-mono/files/ibm-plex-mono-latin-400-normal.woff2",
      weight: "400",
      style: "normal",
    },
    {
      path: "../node_modules/@fontsource/ibm-plex-mono/files/ibm-plex-mono-latin-500-normal.woff2",
      weight: "500",
      style: "normal",
    },
    {
      path: "../node_modules/@fontsource/ibm-plex-mono/files/ibm-plex-mono-latin-600-normal.woff2",
      weight: "600",
      style: "normal",
    },
  ],
  variable: "--font-plex-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Tax-Planning-Ops",
  description: "Sovereign, agent-first tax planning & advisory for Unicorn Commander.",
};

/* Set the theme before first paint (no flash). Light is the default; honors a
   saved choice, else the OS preference. Real setting lives in the avatar menu;
   a cookie-backed server read can replace this later (Stripe's lesson). */
const THEME_INIT = `(function(){try{var t=localStorage.getItem('tpo-theme')||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');document.documentElement.setAttribute('data-theme',t);}catch(e){document.documentElement.setAttribute('data-theme','light');}})();`;

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      data-theme="light"
      className={`${franklin.variable} ${sourceSerif.variable} ${plexMono.variable}`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT }} />
      </head>
      <body className="grain">
        <ClientProviders>{children}</ClientProviders>
        <ThemeToggle />
      </body>
    </html>
  );
}
