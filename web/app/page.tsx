import Link from "next/link";
import { auth } from "@/auth";
import { AnswerCard } from "@/components/AnswerCard";
import { btn, Wordmark } from "@/components/ui";
import type { WhyResult } from "@/lib/lore";

const DOCS = "https://github.com/lorehasit";

const SAMPLE: WhyResult = {
  answer:
    "We moved off server-side sessions in March 2025 after a Redis failover logged every user out at once.[#incidents] Short-lived JWTs plus refresh tokens removed that single point of failure and let auth scale without shared session state.[acme/api#482] Priya pushed back on refresh-token rotation complexity; we accepted that cost for the availability win.[acme/api#482][RFC-07]",
  sources: [
    ["PR", "acme/api#482 — Move to JWT access tokens"],
    ["Incident", "#incidents — Session-store outage"],
    ["RFC", "RFC-07 — Token lifetime"],
  ],
  hops: 2,
  guardrail: { status: "ok", ok: true, reason: "", matched: [], unknown: [] },
};

const STEPS = [
  ["Install the GitHub App", "Pick the org and repositories. Lore imports their merged PRs, review threads and linked ADRs, then keeps up as new PRs merge."],
  ["Sign in", "With GitHub, Google or an email link. Everyone on the team asks against the same memory."],
  ["Ask why", "Ask in plain words. You get a few sentences and the sources behind them, or a straight “I don't know.”"],
];

const card = "flex min-w-0 flex-[1_1_340px] flex-col rounded-lg border border-line bg-surface";
const code = "font-mono text-[12.5px]";

export default async function Landing() {
  const signedIn = !!(await auth());
  const slug = process.env.GITHUB_APP_SLUG;
  const install = slug ? `https://github.com/apps/${slug}` : "/login";

  return (
    <>
      <header className="flex h-16 items-center gap-5 px-4 md:px-10">
        <Wordmark size={26} />
        <nav aria-label="Site" className="ml-4 hidden gap-5 text-sm md:flex">
          <a href="#how" className="text-ink-2 no-underline hover:text-ink">How it works</a>
          <a href="#where" className="text-ink-2 no-underline hover:text-ink">Integrations</a>
          <a href={DOCS} className="text-ink-2 no-underline hover:text-ink">Docs</a>
        </nav>
        <Link href={signedIn ? "/ask" : "/login"} className={`${btn.primary} ${btn.md} ml-auto`}>
          {signedIn ? "Ask Lore" : "Sign in"}
        </Link>
      </header>

      <section className="mx-auto box-border flex max-w-[1200px] flex-wrap items-center gap-x-16 gap-y-12 px-4 pt-8 pb-12 md:px-10 md:pt-[72px] md:pb-24">
        <div className="flex min-w-0 flex-[1_1_400px] flex-col gap-[22px]">
          <div className="label !text-xs">Decision memory for engineering teams</div>
          <h1 className="m-0 font-serif text-5xl leading-[1.02] font-medium tracking-[-0.025em] md:text-[76px]">Lore remembers why.</h1>
          <p className="m-0 max-w-[40ch] text-base leading-[1.55] text-ink-2 md:text-lg">
            Lore reads your team&apos;s merged pull requests and keeps the reasoning behind each change. Ask why something is built
            the way it is, and get a short answer that cites the PRs, ADRs and threads it came from.
          </p>
          <div className="flex flex-wrap gap-2.5">
            <Link href={signedIn ? "/ask" : "/login"} className={`${btn.primary} ${btn.lg} px-5`}>{signedIn ? "Ask Lore" : "Sign in"}</Link>
            <a href={install} className={`${btn.secondary} ${btn.lg}`}>Install the GitHub App</a>
          </div>
        </div>
        <div className="flex min-w-0 flex-[1.25_1_480px] flex-col gap-2.5">
          <AnswerCard question="Why do we use short-lived JWTs instead of server sessions?" account="acme" when="asked by Priya · just now" result={SAMPLE} />
          <p className="m-0 flex gap-2 text-[13px] leading-5 text-ink-3">
            <span aria-hidden="true" className="text-ok">✓</span>
            If Lore can&apos;t cite it, it doesn&apos;t say it. Drafts citing anything Lore didn&apos;t read are blocked.
          </p>
        </div>
      </section>

      <section id="how" className="mx-auto box-border max-w-[1200px] px-4 py-8 md:px-10 md:py-12">
        <h2 className="m-0 mb-7 font-serif text-[30px] leading-[1.2] font-medium tracking-[-0.015em]">How it works</h2>
        <ol className="m-0 flex list-none flex-wrap gap-8 p-0">
          {STEPS.map(([title, body], i) => (
            <li key={title} className="flex flex-[1_1_260px] flex-col gap-2 border-t border-ink pt-4">
              <span className="font-mono text-xs font-medium text-ink-3">0{i + 1}</span>
              <h3 className="m-0 text-[17px] leading-6 font-semibold">{title}</h3>
              <p className="m-0 text-[15px] leading-6 text-ink-2">{body}</p>
            </li>
          ))}
        </ol>
      </section>

      <section id="where" className="mx-auto box-border max-w-[1200px] px-4 py-8 md:px-10 md:py-12">
        <h2 className="m-0 mb-2 font-serif text-[30px] leading-[1.2] font-medium tracking-[-0.015em]">Where you already work</h2>
        <p className="m-0 mb-7 max-w-[60ch] text-[15px] leading-6 text-ink-2">The same memory answers in pull requests, in your terminal and in your editor.</p>
        <div className="flex flex-wrap items-stretch gap-5">
          <div className={card}>
            <CardHead title="In GitHub pull requests">
              A decision check on new PRs, and answers to <code className={code}>@lore why…?</code> in threads.
            </CardHead>
            <div className="mx-3 mb-3 overflow-hidden rounded-lg border border-line bg-bg text-[13px] leading-5">
              <div className="flex items-center gap-2 border-b border-line bg-sunken px-3 py-2">
                <span className="grid size-[18px] place-items-center rounded-sm bg-ink font-serif text-[11px] font-medium text-bg">L</span>
                <strong className="font-semibold">lore</strong>
                <span className="rounded-full border border-line-strong px-1.5 font-mono text-[10px] font-medium text-ink-2">bot</span>
                <span className="text-ink-3">decision check</span>
              </div>
              <div className="px-3 py-2.5">
                This PR edits <code className="font-mono text-xs">src/auth/session.ts</code>, which <span className="font-mono text-xs text-accent">acme/api#482</span> changed
                when the team moved off server sessions. If this reverses that decision, say so in the description.
              </div>
              <div className="flex flex-col gap-1.5 border-t border-line px-3 py-2.5">
                <span><strong className="font-semibold">dana-k</strong> <span className="font-mono text-xs text-accent">@lore</span> why are refresh tokens in a cookie?</span>
                <span className="text-ink-2">
                  <strong className="font-semibold text-ink">lore</strong> To keep them out of JS after the XSS review.
                  <sup className="font-mono text-[10px] font-medium text-accent">[1]</sup> <span className="font-mono text-xs">acme/api#497</span>
                </span>
              </div>
            </div>
          </div>

          <div className={card}>
            <CardHead title="In your terminal">
              Run <code className={code}>npx lore</code> with your Lore API key.
            </CardHead>
            <pre className="mx-3 mb-3 flex-1 rounded-lg bg-[#1C1B19] p-3.5 font-mono text-[12.5px] leading-5 whitespace-pre-wrap text-[#E4E1D9]">
              <span className="text-[#8D897F]">$</span> npx lore why &quot;SQS and not Kafka?&quot;{"\n\n"}Managed SQS fits our volume, and nobody{"\n"}wanted to run Kafka on call. We gave up{"\n"}replay and agreed to revisit for event{"\n"}sourcing.{"\n\n"}
              {"  "}<span className="text-[#80C2CC]">[1]</span> RFC-03 — Job queue{"\n"}
              {"  "}<span className="text-[#80C2CC]">[2]</span> acme/api#233 — Move jobs to SQS{"\n\n"}
              <span className="text-[#8CC898]">✓</span> citations checked · 2 lookups
            </pre>
          </div>

          <div className={card}>
            <CardHead title="In VS Code">Ask about the file or selection you&apos;re looking at.</CardHead>
            <div className="relative mx-3 mb-3 min-h-[200px] flex-1 rounded-lg bg-[#1C1B19] py-3 font-mono text-[12.5px] leading-5 text-[#CFCBC0]">
              <div className="px-3.5"><span className="text-[#6E6A61]">12</span>{"  "}export function isOn(flag: Flag) {"{"}</div>
              <div className="bg-[rgba(128,194,204,.12)] px-3.5"><span className="text-[#6E6A61]">13</span>{"    "}return localEval(flag, ctx);</div>
              <div className="px-3.5"><span className="text-[#6E6A61]">14</span>{"  "}{"}"}</div>
              <div className="mx-3.5 mt-2.5 flex flex-col gap-1.5 rounded-md border border-[#433F39] bg-[#22211E] px-3 py-2.5 font-sans text-[13px] leading-[19px] text-[#ECE9E2]">
                <span className="font-mono text-[10.5px] font-medium tracking-[.06em] text-[#928D82] uppercase">Lore · why is this here?</span>
                <span>Flags are evaluated in-process so checks never add a network hop.<sup className="font-mono text-[10px] font-medium text-[#80C2CC]">[1]</sup></span>
                <span className="font-mono text-xs text-[#ABA69B]">[1] acme/api#301 — In-house flag evaluator</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <footer className="mt-6 border-t border-line">
        <div className="mx-auto box-border flex max-w-[1200px] flex-wrap items-baseline gap-x-10 gap-y-5 px-4 pt-6 pb-8 md:px-10 md:pt-8 md:pb-10">
          <div className="flex items-baseline gap-3">
            <Wordmark size={22} />
            <span className="font-serif text-[15px] text-ink-2 italic">Lore remembers why.</span>
          </div>
          <nav aria-label="Footer" className="flex gap-5 text-[13.5px]">
            <a href={DOCS} className="text-ink-2">Docs</a>
          </nav>
          <span className="ml-auto font-mono text-xs text-ink-3">© 2026 Lore</span>
        </div>
      </footer>
    </>
  );
}

function CardHead({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1 px-[18px] pt-4 pb-3">
      <h3 className="m-0 text-[15px] leading-[22px] font-semibold">{title}</h3>
      <p className="m-0 text-[13.5px] leading-5 text-ink-2">{children}</p>
    </div>
  );
}
