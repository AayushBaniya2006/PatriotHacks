import type { Metadata } from "next";
import Link from "next/link";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Civic Match — Source-Grounded Candidate Alignment",
  description:
    "Compare your priorities against candidates' public records, with every claim backed by a source.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-zinc-950 text-zinc-100">
        <header className="border-b border-zinc-800">
          <div className="mx-auto max-w-5xl px-4 py-3 flex items-center justify-between">
            <Link href="/" className="font-semibold tracking-tight text-lg">
              Civic<span className="text-emerald-400">Match</span>
            </Link>
            <nav className="flex gap-5 text-sm text-zinc-400">
              <Link href="/ballot" className="hover:text-zinc-100">Your ballot</Link>
              <Link href="/intake" className="hover:text-zinc-100">Your priorities</Link>
              <Link href="/results" className="hover:text-zinc-100">Your matches</Link>
              <Link href="/future" className="hover:text-zinc-100">Down the line</Link>
              <Link href="/debate" className="hover:text-zinc-100">Debate</Link>
              <Link href="/graph" className="hover:text-zinc-100">Graph</Link>
            </nav>
          </div>
        </header>
        <main className="flex-1">{children}</main>
        <footer className="border-t border-zinc-800 text-xs text-zinc-500">
          <div className="mx-auto max-w-5xl px-4 py-4">
            Neutral, evidence-backed candidate alignment built on ground truth: every
            claim links to a verifiable source. Matches reflect your stated priorities —
            not endorsements. No source, no claim.
          </div>
        </footer>
      </body>
    </html>
  );
}
