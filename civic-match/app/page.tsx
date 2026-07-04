import Link from "next/link";
import Image from "next/image";
import type { ReactNode, SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

const heroImage = "/images/statue-of-liberty.png";
const recordImage =
  "https://images.unsplash.com/photo-1541872703-74c5e44368f9?q=80&w=2000&auto=format&fit=crop";
const ctaImage = "/images/statue-of-liberty.png";

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

function MenuIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" {...props}>
      <path
        d="M4 7h16M4 12h16M4 17h16"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="1.5"
      />
    </svg>
  );
}

function ArrowRightIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" {...props}>
      <path
        d="M5 12h14m-6-6 6 6-6 6"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
    </svg>
  );
}

function MapPinIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" {...props}>
      <path
        d="M12 21s7-6.08 7-12A7 7 0 1 0 5 9c0 5.92 7 12 7 12Z"
        stroke="currentColor"
        strokeWidth="1.5"
      />
      <circle cx="12" cy="9" r="2.5" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

function LockIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" {...props}>
      <rect
        x="5"
        y="10"
        width="14"
        height="10"
        rx="2"
        stroke="currentColor"
        strokeWidth="1.5"
      />
      <path
        d="M8 10V7a4 4 0 0 1 8 0v3"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="1.5"
      />
    </svg>
  );
}

function FileSearchIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" {...props}>
      <path
        d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h6"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="1.2"
      />
      <path
        d="M14 3v5h5"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.2"
      />
      <path
        d="M9 12h4M9 8h2M9 16h2"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="1.2"
      />
      <circle cx="16.5" cy="16.5" r="2.8" stroke="currentColor" strokeWidth="1.2" />
      <path
        d="m18.6 18.6 2.4 2.4"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="1.2"
      />
    </svg>
  );
}

function ScaleIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" {...props}>
      <path
        d="M12 4v17M5 7h14M8 7l-4 7h8L8 7Zm8 0-4 7h8l-4-7Z"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.2"
      />
    </svg>
  );
}

function QuoteIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" {...props}>
      <path
        d="M5 6h14a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-7l-5 4v-4H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2Z"
        stroke="currentColor"
        strokeLinejoin="round"
        strokeWidth="1.2"
      />
      <path
        d="M9 10.5h.01M13 10.5h.01M17 10.5h.01"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="2"
      />
    </svg>
  );
}

function TwitterXIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" {...props}>
      <path
        d="M4 4l16 16M20 4 4 20"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="1.6"
      />
    </svg>
  );
}

function LinkedinIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" {...props}>
      <path
        d="M6.5 9.5V19M10.5 19v-9.5M10.5 13.3c.6-2.4 5.5-3.3 5.5 1.2V19M5.8 5.8h.01"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="1.6"
      />
    </svg>
  );
}

function MailIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" {...props}>
      <rect x="4" y="6" width="16" height="12" rx="2" stroke="currentColor" strokeWidth="1.5" />
      <path
        d="m5 8 7 5 7-5"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.5"
      />
    </svg>
  );
}

function CivitasMark({ compact = false }: { compact?: boolean }) {
  return (
    <Link href="/" className="flex items-center gap-3" aria-label="Civitas home">
      <StarIcon className={`${compact ? "h-8 w-8" : "h-8 w-8 lg:h-12 lg:w-12"} text-gold`} />
      <span className="flex flex-col">
        <span
          className={`font-serif ${
            compact ? "text-2xl" : "text-2xl lg:text-4xl"
          } font-semibold leading-none tracking-wider text-white`}
        >
          CIVITAS
        </span>
        <span className="mt-1 text-[0.55rem] uppercase tracking-[0.2em] text-white/60 lg:text-[0.65rem]">
          Data for Democracy
        </span>
      </span>
    </Link>
  );
}

function FeatureCard({
  icon,
  title,
  children,
  divider,
}: {
  icon: ReactNode;
  title: string;
  children: ReactNode;
  divider?: boolean;
}) {
  return (
    <div
      className={`relative flex flex-col lg:items-center lg:text-center ${
        divider ? "lg:border-x lg:border-white/10 lg:px-8" : ""
      }`}
      data-reveal="up"
    >
      {divider && <div className="absolute left-0 top-0 -mt-8 h-px w-full bg-white/10 lg:hidden" />}
      {!divider && title !== "One place for the record" && (
        <div className="absolute left-0 top-0 -mt-8 h-px w-full bg-white/10 lg:hidden" />
      )}
      {icon}
      <h3 className="mb-4 font-serif text-2xl text-white lg:text-3xl">{title}</h3>
      <div className="mb-4 h-0.5 w-10 bg-red lg:mx-auto" />
      <p className="font-light leading-relaxed text-white/70">{children}</p>
    </div>
  );
}

export default function Home() {
  const year = new Date().getFullYear();

  return (
    <div className="min-h-screen w-full overflow-x-hidden font-sans">
      <nav className="absolute left-0 right-0 top-0 z-50 mx-auto flex w-full max-w-[1600px] items-center justify-between px-6 py-6 lg:px-12">
        <CivitasMark />

        <div className="hidden items-center gap-10 text-sm uppercase tracking-widest text-white/90 lg:flex">
          <a href="#features" className="transition-colors hover:text-white">
            Solutions
          </a>
          <a href="#record" className="transition-colors hover:text-white">
            About
          </a>
          <Link href="/future" className="transition-colors hover:text-white">
            Insights
          </Link>
          <div className="mx-2 h-4 w-px bg-white/20" />
          <StarIcon className="h-5 w-5 text-gold" />
        </div>

        <details className="group relative lg:hidden">
          <summary className="list-none text-white/90 marker:hidden [&::-webkit-details-marker]:hidden">
            <span className="sr-only">Open navigation</span>
            <MenuIcon className="h-8 w-8" />
          </summary>
          <div className="absolute right-0 mt-4 grid min-w-48 gap-3 border border-white/10 bg-navy-dark/95 p-4 text-sm uppercase tracking-widest text-white shadow-2xl">
            <a href="#features" className="hover:text-gold">
              Solutions
            </a>
            <a href="#record" className="hover:text-gold">
              About
            </a>
            <Link href="/future" className="hover:text-gold">
              Insights
            </Link>
            <Link href="/ballot" className="hover:text-gold">
              Ballot
            </Link>
          </div>
        </details>
      </nav>

      <main>
        <section className="relative flex min-h-[90vh] items-center pb-16 pt-36 lg:min-h-screen lg:pb-20 lg:pt-44">
          <div className="absolute inset-0 z-0">
            <div className="absolute inset-0 z-10 bg-navy/60 lg:hidden" />
            <div className="absolute inset-0 z-10 hidden w-[66%] bg-gradient-to-r from-navy via-navy/95 to-transparent lg:block" />
            <div className="absolute inset-0 z-10 bg-gradient-to-t from-navy via-transparent to-navy/15" />
            <Image
              src={heroImage}
              alt="Statue of Liberty"
              fill
              loading="eager"
              sizes="100vw"
              className="hero-image-motion object-cover object-[70%_50%] lg:scale-[1.2] lg:translate-x-[7%] lg:object-center"
            />
          </div>

          <div className="relative z-20 mx-auto w-full max-w-[1600px] px-6 lg:px-24">
            <div className="max-w-3xl">
              <h1
                className="font-serif text-5xl font-normal leading-[1.05] text-cream-light lg:text-[6rem] xl:text-[6.25rem]"
                data-hero-reveal="0"
              >
                Know your ballot.
                <br />
                Follow the sources.
              </h1>
              <div className="mb-8 mt-9 h-1 w-24 bg-red" data-hero-reveal="1" />
              <p
                className="max-w-lg text-lg font-light leading-relaxed text-white/75 lg:text-xl"
                data-hero-reveal="2"
              >
                Enter a Texas address to see the races, candidates, records, and citations that
                matter for your election.
              </p>

              <form action="/ballot" method="get" className="mt-10 max-w-xl space-y-3" data-hero-reveal="3">
                <label className="relative flex items-center">
                  <span className="sr-only">Enter Texas address</span>
                  <MapPinIcon className="absolute left-5 h-5 w-5 text-gold" />
                  <input
                    type="text"
                    name="address"
                    placeholder="Enter your Texas address"
                    className="w-full rounded-md border border-gold/50 bg-navy-dark/90 py-4 pl-14 pr-5 text-base text-white placeholder:text-white/45 transition-colors focus:border-gold focus:outline-none"
                  />
                </label>
                <button
                  type="submit"
                  className="inline-flex w-full items-center justify-center gap-3 rounded-md bg-red px-8 py-4 text-sm font-semibold uppercase tracking-wider text-white transition-colors hover:bg-red/90 sm:w-auto"
                >
                  Check My Election
                  <ArrowRightIcon className="h-5 w-5" />
                </button>
                <div className="flex items-center gap-2 text-sm text-white/55">
                  <LockIcon className="h-4 w-4" />
                  <span>Your address is only used to identify your ballot.</span>
                </div>
              </form>
            </div>
          </div>

          <div className="scroll-cue absolute bottom-8 left-1/2 z-20 flex -translate-x-1/2 flex-col items-center gap-2">
            <span className="text-[0.65rem] uppercase tracking-[0.2em] text-gold">Scroll</span>
            <StarIcon className="h-3 w-3 text-gold" />
            <div className="h-12 w-px bg-gold/30" />
          </div>
        </section>

        <section
          id="record"
          className="relative flex min-h-[70vh] items-center overflow-hidden bg-cream text-navy lg:min-h-[80vh] lg:bg-navy lg:text-white"
        >
          <div className="absolute inset-0 z-0 lg:left-1/3">
            <div className="absolute inset-0 z-10 h-full bg-gradient-to-t from-cream via-cream/80 to-transparent lg:hidden" />
            <div className="absolute inset-0 z-10 hidden w-1/2 bg-gradient-to-r from-navy via-navy/90 to-transparent lg:block" />
            <Image
              src={recordImage}
              alt="Civic building pillars"
              fill
              sizes="100vw"
              className="object-cover object-bottom opacity-80 mix-blend-multiply lg:object-right lg:opacity-50 lg:mix-blend-luminosity"
            />
          </div>

          <div className="relative z-20 mx-auto w-full max-w-[1600px] px-6 py-20 lg:px-24 lg:py-0">
            <div className="max-w-xl" data-reveal="left">
              <h2 className="font-serif text-5xl font-normal leading-[1.1] lg:text-[4.5rem]">
                The public record
                <br />
                is scattered.
                <br />
                Civitas makes
                <br />
                it readable.
              </h2>
              <div className="mb-8 mt-8 h-1 w-16 bg-red" />
              <p className="max-w-md text-lg font-light leading-relaxed opacity-90 lg:text-xl lg:text-white/80">
                Elections are decided through thousands of small details. Civitas organizes each
                record around verifiable sources so you can see what is known and what is missing.
              </p>
            </div>
          </div>
        </section>

        <section className="relative border-t border-white/5 bg-navy py-24 lg:py-32">
          <div className="mx-auto max-w-4xl px-6 text-center" data-reveal="up">
            <h2 className="mb-6 font-serif text-4xl text-white lg:text-6xl">Check in on your election.</h2>
            <p className="mx-auto max-w-xl text-sm uppercase leading-relaxed tracking-widest text-white/70 lg:text-base">
              Get a clear view of the races, candidates, and issues on your ballot.
            </p>

            <form action="/ballot" method="get" className="mx-auto mt-12 max-w-2xl space-y-4">
              <label className="relative flex items-center">
                <span className="sr-only">Enter address or ZIP code</span>
                <MapPinIcon className="absolute left-6 h-6 w-6 text-gold" />
                <input
                  type="text"
                  name="address"
                  placeholder="Enter address or ZIP code"
                  className="w-full rounded-md border border-gold/50 bg-navy-dark py-5 pl-16 pr-6 text-lg text-white placeholder:text-white/40 transition-colors focus:border-gold focus:outline-none"
                />
              </label>
              <button
                type="submit"
                className="flex w-full items-center justify-center gap-3 rounded-md bg-red py-5 text-sm font-semibold uppercase tracking-wider text-white transition-colors hover:bg-red/90"
              >
                Check My Election
                <ArrowRightIcon className="h-5 w-5" />
              </button>
              <div className="mt-6 flex items-center justify-center gap-2 text-sm text-white/50">
                <LockIcon className="h-4 w-4" />
                <span>Your location is used only to identify your ballot.</span>
              </div>
            </form>
          </div>
        </section>

        <section id="features" className="border-t border-white/5 bg-navy py-12 lg:py-24">
          <div className="mx-auto grid max-w-[1400px] grid-cols-1 gap-16 px-6 md:grid-cols-3 lg:gap-8 lg:px-12">
            <FeatureCard
              icon={<FileSearchIcon className="mb-6 h-12 w-12 text-gold lg:h-16 lg:w-16" />}
              title="One place for the record"
            >
              Candidate filings, votes, statements, and ballot measures&mdash;organized and source-linked.
            </FeatureCard>

            <FeatureCard
              icon={<ScaleIcon className="mb-6 h-12 w-12 text-gold lg:h-16 lg:w-16" />}
              title="Your priorities, not ours"
              divider
            >
              Build your profile around the issues that matter most to you.
            </FeatureCard>

            <FeatureCard
              icon={<QuoteIcon className="mb-6 h-12 w-12 text-gold lg:h-16 lg:w-16" />}
              title="Ask anything. Get answers."
            >
              Dive deeper with answers drawn from indexed civic records and sources.
            </FeatureCard>
          </div>
        </section>

        <section className="relative overflow-hidden border-t border-white/5 bg-navy py-32">
          <div className="absolute inset-0 z-0">
            <div className="absolute inset-0 z-10 w-full bg-gradient-to-r from-navy via-navy/90 to-transparent lg:w-2/3" />
            <div className="absolute inset-0 z-10 bg-navy/60 lg:hidden" />
            <Image
              src={ctaImage}
              alt="Statue of Liberty detail"
              fill
              sizes="100vw"
              className="object-cover object-right opacity-30 mix-blend-luminosity grayscale"
            />
          </div>

          <div className="relative z-20 mx-auto max-w-4xl px-6 text-center" data-reveal="up">
            <div className="mb-8 flex items-center justify-center gap-4">
              <div className="h-px w-16 bg-gold/50" />
              <StarIcon className="h-5 w-5 text-gold" />
              <div className="h-px w-16 bg-gold/50" />
            </div>
            <h2 className="mb-4 font-serif text-4xl leading-tight text-white lg:text-5xl">
              Democracy runs on information.
              <br />
              <span className="font-normal italic text-gold">Make it count.</span>
            </h2>
            <div className="mx-auto mb-8 mt-8 h-0.5 w-10 bg-red" />
            <p className="mx-auto mb-10 hidden max-w-md font-light text-white/70 lg:block">
              Get a clear view of the races, candidates, and issues on your ballot.
            </p>
            <Link
              href="/ballot"
              className="inline-flex items-center gap-4 rounded-sm bg-red px-8 py-4 text-sm font-semibold uppercase tracking-wider text-white transition-colors hover:bg-red/90"
            >
              Check Your Election
              <ArrowRightIcon className="h-5 w-5" />
            </Link>
          </div>
        </section>
      </main>

      <footer className="border-t border-white/10 bg-navy px-6 pb-8 pt-16 lg:px-12">
        <div className="mx-auto flex max-w-[1600px] flex-col items-start justify-between gap-12 lg:flex-row lg:items-center lg:gap-0">
          <CivitasMark compact />

          <div className="flex w-full flex-col items-start gap-8 lg:w-auto lg:flex-row lg:items-center lg:gap-12">
            <div className="flex flex-wrap gap-6 text-xs uppercase tracking-widest text-white/70 lg:flex-nowrap lg:gap-10">
              <a href="#features" className="transition-colors hover:text-white">
                Solutions
              </a>
              <a href="#record" className="transition-colors hover:text-white">
                About
              </a>
              <Link href="/future" className="transition-colors hover:text-white">
                Insights
              </Link>
              <Link href="/ballot" className="transition-colors hover:text-white lg:ml-8">
                Privacy
              </Link>
              <Link href="/intake" className="transition-colors hover:text-white">
                Terms
              </Link>
            </div>

            <div className="mt-4 flex items-center gap-6 text-white/50 lg:mt-0">
              <a href="mailto:sybatx@gmail.com" aria-label="Email Civitas" className="transition-colors hover:text-white">
                <MailIcon className="h-5 w-5" />
              </a>
              <a href="/future" aria-label="Civitas insights" className="transition-colors hover:text-white">
                <TwitterXIcon className="h-5 w-5" />
              </a>
              <a href="/graph" aria-label="Civitas graph" className="transition-colors hover:text-white">
                <LinkedinIcon className="h-5 w-5" />
              </a>
            </div>
          </div>
        </div>

        <div className="mx-auto mt-16 flex max-w-[1600px] flex-col items-center justify-between border-t border-white/5 pt-8 text-xs text-white/30 lg:flex-row">
          <p>&copy; {year} Civitas. All rights reserved.</p>
        </div>
      </footer>
    </div>
  );
}
