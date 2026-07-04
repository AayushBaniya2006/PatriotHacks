import Link from "next/link";
import type {
  AnchorHTMLAttributes,
  ButtonHTMLAttributes,
  HTMLAttributes,
  ReactNode,
} from "react";

export function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

export function CivitasPage({
  eyebrow,
  title,
  description,
  children,
  wide = false,
  className,
}: {
  eyebrow?: string;
  title?: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  wide?: boolean;
  className?: string;
}) {
  return (
    <div className="relative min-h-full overflow-hidden bg-navy text-cream-light">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 h-[28rem] opacity-45"
        style={{
          backgroundImage:
            "linear-gradient(180deg, rgba(4,22,41,.2), #041629 92%), linear-gradient(90deg, rgba(4,22,41,.95), rgba(4,22,41,.5)), url('/images/stone-pillars.png')",
          backgroundPosition: "center top",
          backgroundSize: "cover",
        }}
      />
      <section
        className={cn(
          "relative mx-auto px-4 py-10 sm:px-6 lg:py-14",
          wide ? "max-w-7xl" : "max-w-4xl",
          className
        )}
      >
        {(eyebrow || title || description) && (
          <header className="mb-9 max-w-3xl">
            {eyebrow && (
              <p className="mb-3 text-xs font-semibold uppercase tracking-[0.24em] text-gold">
                {eyebrow}
              </p>
            )}
            {title && (
              <h1 className="font-serif text-4xl font-normal leading-tight text-white sm:text-5xl">
                {title}
              </h1>
            )}
            {description && (
              <p className="mt-4 max-w-2xl text-sm leading-6 text-white/68 sm:text-base sm:leading-7">
                {description}
              </p>
            )}
            <div className="mt-6 h-0.5 w-14 bg-red" />
          </header>
        )}
        {children}
      </section>
    </div>
  );
}

export function CivitasPanel({
  children,
  className,
  as: Component = "div",
}: HTMLAttributes<HTMLElement> & {
  children: ReactNode;
  as?: "div" | "section" | "article" | "aside" | "details";
}) {
  return (
    <Component
      className={cn(
        "rounded-[10px] border border-white/12 bg-white/[0.035] shadow-[0_18px_54px_rgba(0,0,0,0.2)]",
        className
      )}
    >
      {children}
    </Component>
  );
}

export function CivitasSectionHeading({
  eyebrow,
  title,
  description,
  className,
}: {
  eyebrow?: string;
  title: ReactNode;
  description?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("mb-5", className)}>
      {eyebrow && (
        <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.22em] text-gold/85">
          {eyebrow}
        </p>
      )}
      <h2 className="font-serif text-2xl font-normal leading-tight text-white">{title}</h2>
      {description && <p className="mt-2 text-sm leading-6 text-white/58">{description}</p>}
    </div>
  );
}

export function CivitasButton({
  children,
  className,
  variant = "primary",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost";
}) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center rounded-[8px] px-5 py-3 text-xs font-black uppercase tracking-[0.2em] transition disabled:cursor-not-allowed disabled:opacity-45",
        variant === "primary" &&
          "bg-red text-white shadow-[0_12px_28px_rgba(156,42,42,0.28)] hover:bg-red/90",
        variant === "secondary" &&
          "border border-gold/45 bg-gold/10 text-gold hover:border-gold hover:bg-gold/15",
        variant === "ghost" && "text-gold hover:bg-gold/10",
        className
      )}
      {...props}
    >
      {children}
    </button>
  );
}

export function CivitasLinkButton({
  href,
  children,
  className,
  variant = "primary",
}: {
  href: string;
  children: ReactNode;
  className?: string;
  variant?: "primary" | "secondary" | "ghost";
}) {
  return (
    <Link
      href={href}
      className={cn(
        "inline-flex items-center justify-center rounded-[8px] px-5 py-3 text-xs font-black uppercase tracking-[0.2em] transition",
        variant === "primary" &&
          "bg-red text-white shadow-[0_12px_28px_rgba(156,42,42,0.28)] hover:bg-red/90",
        variant === "secondary" &&
          "border border-gold/45 bg-gold/10 text-gold hover:border-gold hover:bg-gold/15",
        variant === "ghost" && "text-gold hover:bg-gold/10",
        className
      )}
    >
      {children}
    </Link>
  );
}

export function SourceLink({
  href,
  children = "source",
  className,
  ...props
}: AnchorHTMLAttributes<HTMLAnchorElement> & {
  href: string;
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className={cn(
        "font-semibold text-gold underline decoration-gold/35 underline-offset-4 transition hover:text-cream-light hover:decoration-cream-light",
        className
      )}
      {...props}
    >
      {children}
    </a>
  );
}

export function StatusPill({
  children,
  tone = "neutral",
  className,
  title,
}: {
  children: ReactNode;
  tone?: "neutral" | "gold" | "red";
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex shrink-0 items-center rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em]",
        tone === "neutral" && "border-white/14 text-white/50",
        tone === "gold" && "border-gold/45 bg-gold/10 text-gold",
        tone === "red" && "border-red/45 bg-red/10 text-red-200",
        className
      )}
    >
      {children}
    </span>
  );
}

export function MetricSeal({
  value,
  label,
  className,
}: {
  value: ReactNode;
  label: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex h-16 w-16 shrink-0 flex-col items-center justify-center rounded-full border border-gold/55 bg-navy-dark/80 text-gold shadow-[0_0_0_1px_rgba(182,141,93,0.12)]",
        className
      )}
    >
      <span className="font-serif text-2xl leading-none text-white">{value}</span>
      <span className="mt-1 text-[9px] font-bold uppercase tracking-[0.18em] text-gold/80">
        {label}
      </span>
    </div>
  );
}
