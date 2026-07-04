import Link from "next/link";
import type {
  AnchorHTMLAttributes,
  ButtonHTMLAttributes,
  HTMLAttributes,
  InputHTMLAttributes,
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

export function CivitasTextField({
  label,
  helper,
  className,
  inputClassName,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & {
  label: ReactNode;
  helper?: ReactNode;
  inputClassName?: string;
}) {
  return (
    <label className={cn("block", className)}>
      <span className="text-xs font-semibold uppercase tracking-[0.16em] text-white/52">
        {label}
      </span>
      <input
        className={cn(
          "mt-2 w-full rounded-[8px] border border-white/14 bg-navy-dark px-3 py-2.5 text-sm text-white outline-none transition placeholder:text-white/30 focus:border-gold/70",
          inputClassName
        )}
        {...props}
      />
      {helper && <span className="mt-2 block text-xs leading-5 text-white/48">{helper}</span>}
    </label>
  );
}

export function CivitasSelectableChip({
  children,
  selected,
  rank,
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  selected?: boolean;
  rank?: number;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      className={cn(
        "inline-flex min-h-9 items-center rounded-full border px-3.5 py-1.5 text-sm leading-5 transition",
        selected
          ? "border-gold bg-gold/12 text-gold shadow-[0_0_0_1px_rgba(182,141,93,0.08)]"
          : "border-white/14 text-white/62 hover:border-gold/50 hover:text-white",
        className
      )}
      {...props}
    >
      {rank !== undefined && (
        <span className="mr-1.5 font-mono text-xs font-semibold text-gold/90">#{rank}</span>
      )}
      {children}
    </button>
  );
}

export function CivitasProgressPanel({
  steps,
  currentStep,
  className,
}: {
  steps: { id: string; label: ReactNode; detail?: ReactNode }[];
  currentStep: string;
  className?: string;
}) {
  const currentIndex = Math.max(
    0,
    steps.findIndex((step) => step.id === currentStep)
  );
  const progress = steps.length <= 1 ? 100 : ((currentIndex + 1) / steps.length) * 100;

  return (
    <CivitasPanel className={cn("p-4", className)} as="aside">
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-gold/85">
          Intake progress
        </p>
        <span className="font-mono text-xs text-white/46">
          {currentIndex + 1}/{steps.length}
        </span>
      </div>
      <div className="mb-4 h-1 rounded-full bg-white/12" aria-hidden="true">
        <div className="h-1 rounded-full bg-gold transition-all" style={{ width: `${progress}%` }} />
      </div>
      <ol className="grid gap-3">
        {steps.map((step, index) => {
          const active = index === currentIndex;
          const complete = index < currentIndex;
          return (
            <li key={step.id} className="grid grid-cols-[1.75rem_1fr] gap-3">
              <span
                className={cn(
                  "flex h-7 w-7 items-center justify-center rounded-full border font-mono text-xs",
                  active && "border-gold bg-gold/12 text-gold",
                  complete && "border-gold/55 bg-gold/10 text-gold/78",
                  !active && !complete && "border-white/14 text-white/38"
                )}
              >
                {index + 1}
              </span>
              <span>
                <span
                  className={cn(
                    "block text-sm font-semibold",
                    active ? "text-white" : "text-white/58"
                  )}
                >
                  {step.label}
                </span>
                {step.detail && (
                  <span className="mt-0.5 block text-xs leading-5 text-white/42">
                    {step.detail}
                  </span>
                )}
              </span>
            </li>
          );
        })}
      </ol>
    </CivitasPanel>
  );
}

export function CivitasNotice({
  children,
  className,
  tone = "neutral",
}: {
  children: ReactNode;
  className?: string;
  tone?: "neutral" | "gold" | "red";
}) {
  return (
    <div
      className={cn(
        "rounded-[8px] border px-4 py-3 text-sm leading-6",
        tone === "neutral" && "border-white/12 bg-navy-dark/55 text-white/58",
        tone === "gold" && "border-gold/35 bg-gold/10 text-cream-light/82",
        tone === "red" && "border-red/40 bg-red/10 text-red-100",
        className
      )}
    >
      {children}
    </div>
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
