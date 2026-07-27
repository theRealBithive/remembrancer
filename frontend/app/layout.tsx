import type { Metadata } from "next";
import { Bodoni_Moda, IBM_Plex_Mono, Newsreader } from "next/font/google";
import Link from "next/link";

import "./globals.css";

// Self-hosted at build time by next/font -- no external font requests at runtime.
const bodoni = Bodoni_Moda({
  subsets: ["latin"],
  variable: "--font-bodoni",
  display: "swap",
});
const newsreader = Newsreader({
  subsets: ["latin"],
  variable: "--font-newsreader",
  display: "swap",
});
const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-plex-mono",
  display: "swap",
});

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";
const SITE_NAME = process.env.NEXT_PUBLIC_SITE_NAME ?? "Remembrancer";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: { default: SITE_NAME, template: `%s — ${SITE_NAME}` },
  description: "A listening record: ratings and reviews of audiobooks.",
  openGraph: { siteName: SITE_NAME, type: "website", locale: "en_GB" },
  alternates: { types: { "application/atom+xml": "/feed.xml" } },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${bodoni.variable} ${newsreader.variable} ${plexMono.variable}`}>
      <body className="min-h-dvh flex flex-col">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:m-4 focus:bg-raised focus:px-3 focus:py-2"
        >
          Skip to content
        </a>

        <header className="mx-auto w-full max-w-3xl px-6 pt-12 pb-8 sm:pt-16">
          <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
            <Link
              href="/"
              className="font-display text-2xl tracking-tight sm:text-3xl"
              style={{ fontVariantCaps: "small-caps", letterSpacing: "0.04em" }}
            >
              {SITE_NAME}
            </Link>
            <p className="font-mono text-[0.7rem] uppercase tracking-[0.18em] text-muted">
              A listening record
            </p>
          </div>
          <hr className="mt-6 border-0 border-t border-rule" />
        </header>

        <main id="main" className="mx-auto w-full max-w-3xl flex-1 px-6">
          {children}
        </main>

        <footer className="mx-auto w-full max-w-3xl px-6 py-16">
          <hr className="mb-6 border-0 border-t border-rule" />
          <nav className="flex flex-wrap gap-x-6 gap-y-2 font-mono text-[0.7rem] uppercase tracking-[0.15em] text-muted">
            <Link href="/" className="hover:text-ink">
              Reviews
            </Link>
            <a href="/feed.xml" className="hover:text-ink">
              Feed
            </a>
            <Link href="/legal" className="hover:text-ink">
              Impressum &amp; Datenschutz
            </Link>
          </nav>
        </footer>
      </body>
    </html>
  );
}
