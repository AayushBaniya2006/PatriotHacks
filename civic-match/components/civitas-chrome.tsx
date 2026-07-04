"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode, SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

function StarIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" {...props}>
      <path
        d="m12 2 2.88 6.58L22 9.26l-5.36 4.68 1.58 7.06L12 17.36 5.78 21l1.58-7.06L2 9.26l7.12-.68L12 2Z"
        fill="currentColor"
      />
    </svg>
  );
}

const navItems = [
  ["Your ballot", "/ballot"],
  ["Priorities", "/intake"],
  ["Matches", "/results"],
  ["Future", "/future"],
  ["Debate", "/debate"],
  ["Graph", "/graph"],
] as const;

export default function CivitasChrome({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  if (pathname === "/" || pathname === "/ballot") return <>{children}</>;

  return (
    <div className="flex min-h-screen flex-col bg-navy text-cream-light">
      <header className="border-b border-white/10 bg-navy/95">
        <div className="mx-auto flex max-w-6xl flex-col gap-5 px-4 py-4 lg:flex-row lg:items-center lg:justify-between lg:px-6">
          <Link href="/" className="flex items-center gap-3" aria-label="Civitas home">
            <StarIcon className="h-8 w-8 text-gold" />
            <span className="flex flex-col">
              <span className="font-serif text-2xl font-semibold leading-none tracking-wider text-white">
                CIVITAS
              </span>
              <span className="mt-1 text-[0.55rem] uppercase tracking-[0.2em] text-white/50">
                Data for Democracy
              </span>
            </span>
          </Link>
          <nav className="flex flex-wrap gap-x-5 gap-y-2 text-xs uppercase tracking-widest text-white/65">
            {navItems.map(([label, href]) => (
              <Link
                key={href}
                href={href}
                className={`transition-colors hover:text-white ${
                  pathname === href ? "text-gold" : ""
                }`}
              >
                {label}
              </Link>
            ))}
          </nav>
        </div>
      </header>
      <main className="flex-1">{children}</main>
      <footer className="border-t border-white/10 text-xs text-white/45">
        <div className="mx-auto max-w-6xl px-4 py-4 lg:px-6">
          Neutral, evidence-backed candidate alignment built on ground truth: every claim links to a
          verifiable source. Matches reflect your stated priorities, not endorsements. No source, no claim.
        </div>
      </footer>
    </div>
  );
}
