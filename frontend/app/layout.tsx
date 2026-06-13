import type { Metadata } from "next";
import { Libre_Franklin, Source_Serif_4, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";
import { ClientProviders } from "@/components/client-providers";
import { ThemeToggle } from "@/components/theme";

/* Daylight & Paper type system:
   - Franklin = the instrument/UI voice (the 1040's own letterform heritage)
   - Source Serif 4 = the document/counsel voice (memos, present)
   - IBM Plex Mono = the ledger voice (figures, citations, hashes) */
const franklin = Libre_Franklin({
  subsets: ["latin"],
  variable: "--font-franklin",
  weight: ["400", "500", "600", "700", "800"],
  display: "swap",
});
const sourceSerif = Source_Serif_4({
  subsets: ["latin"],
  variable: "--font-source-serif",
  weight: ["400", "600"],
  style: ["normal", "italic"],
  display: "swap",
});
const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  variable: "--font-plex-mono",
  weight: ["400", "500", "600"],
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
