import Link from "next/link";
import { auth } from "@/auth";
import { AnswerCard } from "@/components/AnswerCard";
import { TabbedWindow } from "@/components/Tabs";
import { btn, Wordmark } from "@/components/ui";
import type { WhyResult } from "@/lib/lore";

const GITHUB = "https://github.com/lorehasit";

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

const FACTS = [
  ["100%", "of claims cited, or the answer is withheld"],
  ["≤ 4", "lookups per question, then Lore stops and answers"],
  ["$0", "to self-host: free and open-source services only"],
];

const STEPS = [
  ["Capture", "When a pull request merges, Lore reads its description, review threads and the ADRs it links to, and keeps the reasoning."],
  ["Connect", "Decisions are linked by fixed rules, never a model: what superseded or reverted what, and which files each one changed."],
  ["Answer", "Ask in plain words. Every claim cites something Lore actually read, or it says it doesn't know."],
];

const ASKERS = [
  ["New engineers", "Why is payments the only service outside the monolith?", "Skip the archaeology. Get the reasoning in a few sentences, with the PRs to read next."],
  ["Reviewers", "Does this change undo an earlier decision?", "Lore's decision check lists the decisions behind the files a PR touches, before anyone approves it."],
  ["Tech leads", "Which of our decisions has the code moved on from?", "Stale-decision warnings show where the code has drifted from what was decided, with the PRs behind it."],
];

const TRUST = [
  ["▣", "Self-hosted", "One docker compose up runs the API, worker, Postgres and Qdrant. No account anywhere, no paid API required."],
  ["⊘", "Guardrailed", "An answer citing anything Lore didn't read never ships. The PR decision check uses no model at all."],
  ["◎", "Observable", "Langfuse traces for every answer, Prometheus metrics, and an eval gate that fails the build if accuracy drops."],
];

const FOOTER: Record<string, [string, string][]> = {
  Product: [["How it works", "#how"], ["Integrations", "#integrations"], ["Self-hosting", "#trust"], ["Sign in", "/login"]],
  Developers: [["CLI", `${GITHUB}/lore-cli`], ["VS Code extension", `${GITHUB}/lore-vscode-extension`], ["Python package", "https://pypi.org/project/lore-backend/"]],
  Project: [["GitHub", GITHUB]],
};

function PrMock() {
  return (
    <div className="p-4 md:p-6">
      <div className="overflow-hidden rounded-lg border border-line bg-bg text-[13px] leading-5">
        <div className="flex items-center gap-2 border-b border-line bg-sunken px-3 py-2">
          <span className="grid size-[18px] place-items-center rounded-sm bg-ink font-serif text-[11px] font-medium text-bg">L</span>
          <strong className="font-semibold">lore</strong>
          <span className="rounded-full border border-line-strong px-1.5 font-mono text-[10px] font-medium text-ink-2">bot</span>
          <span className="text-ink-3">decision check</span>
        </div>
        <div className="px-3 py-2.5">
          This PR edits <code className="font-mono text-xs">src/auth/session.ts</code>, which <span className="font-mono text-xs text-accent">acme/api#482</span> changed when
          the team moved off server sessions. If this reverses that decision, say so in the description.
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
  );
}

function TerminalMock() {
  return (
    <pre className="m-0 bg-[#1C1B19] p-5 font-mono text-[12.5px] leading-5 whitespace-pre-wrap text-[#E4E1D9] md:p-6">
      <span className="text-[#8D897F]">$</span> npx lore why &quot;SQS and not Kafka?&quot;{"\n\n"}Managed SQS fits our volume, and nobody wanted to run Kafka{"\n"}on call. We gave up replay and agreed to revisit for event sourcing.{"\n\n"}
      {"  "}<span className="text-[#80C2CC]">[1]</span> RFC-03 — Job queue{"\n"}
      {"  "}<span className="text-[#80C2CC]">[2]</span> acme/api#233 — Move jobs to SQS{"\n\n"}
      <span className="text-[#8CC898]">✓</span> citations checked · 2 lookups
    </pre>
  );
}

function EditorMock() {
  return (
    <div className="bg-[#1C1B19] py-4 font-mono text-[12.5px] leading-5 text-[#CFCBC0]">
      <div className="px-5"><span className="text-[#6E6A61]">12</span>{"  "}export function isOn(flag: Flag) {"{"}</div>
      <div className="bg-[rgba(128,194,204,.12)] px-5"><span className="text-[#6E6A61]">13</span>{"    "}return localEval(flag, ctx);</div>
      <div className="px-5"><span className="text-[#6E6A61]">14</span>{"  "}{"}"}</div>
      <div className="mx-5 mt-3 flex max-w-md flex-col gap-1.5 rounded-md border border-[#433F39] bg-[#22211E] px-3 py-2.5 font-sans text-[13px] leading-[19px] text-[#ECE9E2]">
        <span className="font-mono text-[10.5px] font-medium tracking-[.06em] text-[#928D82] uppercase">Lore · why is this here?</span>
        <span>Flags are evaluated in-process so checks never add a network hop.<sup className="font-mono text-[10px] font-medium text-[#80C2CC]">[1]</sup></span>
        <span className="font-mono text-xs text-[#ABA69B]">[1] acme/api#301 — In-house flag evaluator</span>
      </div>
    </div>
  );
}

/** One feature panel in the dark band: copy on the left, a light mock on the right. */
function Feature({ title, body, children }: { title: string; body: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-8 p-6 md:p-8">
      <div className="flex min-w-0 flex-[1_1_260px] flex-col gap-3">
        <h3 className="m-0 font-serif text-2xl font-medium text-[#ECE9E2]">{title}</h3>
        <p className="m-0 max-w-[44ch] text-[15px] leading-6 text-[#ABA69B]">{body}</p>
      </div>
      <div className="min-w-0 flex-[1.2_1_320px] rounded-lg bg-[#FAF9F6] p-4 text-[13px] leading-5 text-[#1C1B19]">{children}</div>
    </div>
  );
}

export default async function Landing() {
  const signedIn = !!(await auth());
  const slug = process.env.GITHUB_APP_SLUG;
  const install = slug ? `https://github.com/apps/${slug}` : "/login";
  const primary = signedIn ? { href: "/ask", label: "Ask Lore" } : { href: "/login", label: "Sign in" };
  const section = "mx-auto box-border max-w-[1200px] px-4 md:px-10";
  const h2 = "m-0 font-serif text-[34px] leading-[1.15] font-medium tracking-[-0.02em] md:text-[44px]";

  return (
    <>
      <a href="#features" className="block bg-accent-soft px-4 py-2.5 text-center text-[13.5px] text-ink no-underline hover:underline">
        <span className="mr-2 rounded-full border border-accent px-2 py-0.5 font-mono text-[10.5px] font-medium tracking-[.06em] text-accent uppercase">New</span>
        Lore now flags decisions the code has probably moved on from. <span className="font-medium">See how →</span>
      </a>

      <header className="flex h-16 items-center gap-5 border-b border-line px-4 md:px-10">
        <Wordmark size={26} />
        <nav aria-label="Site" className="ml-4 hidden gap-6 text-sm md:flex">
          <a href="#how" className="text-ink-2 no-underline hover:text-ink">How it works</a>
          <a href="#integrations" className="text-ink-2 no-underline hover:text-ink">Integrations</a>
          <a href="#trust" className="text-ink-2 no-underline hover:text-ink">Self-hosting</a>
          <a href={GITHUB} className="text-ink-2 no-underline hover:text-ink">GitHub ↗</a>
        </nav>
        <Link href={primary.href} className={`${btn.primary} ${btn.md} ml-auto`}>{primary.label}</Link>
      </header>

      {/* Hero */}
      <section className={`${section} flex flex-col items-center pt-16 pb-10 text-center md:pt-24`}>
        <a href={GITHUB} className="inline-flex items-center gap-2 rounded-full border border-line-strong bg-surface px-3 py-1 text-[13px] text-ink-2 no-underline hover:text-ink">
          <span aria-hidden="true" className="text-accent">●</span> Open source · MIT licensed
        </a>
        <h1 className="m-0 mt-7 max-w-[14ch] font-serif text-[52px] leading-[1.02] font-medium tracking-[-0.03em] md:text-[88px]">
          Lore remembers <em className="text-accent">why</em>.
        </h1>
        <p className="m-0 mt-6 max-w-[52ch] text-[17px] leading-[1.6] text-ink-2 md:text-lg">
          Decision memory for engineering teams. Ask why the code is built the way it is, and get a short answer cited from the pull
          requests where it was decided.
        </p>
        <div className="mt-8 flex flex-wrap justify-center gap-2.5">
          <Link href={primary.href} className={`${btn.primary} ${btn.lg} px-6`}>{primary.label} <span aria-hidden="true">→</span></Link>
          <a href={install} className={`${btn.secondary} ${btn.lg}`}>Install the GitHub App</a>
        </div>
      </section>

      {/* Product window */}
      <section id="integrations" className={`${section} scroll-mt-6 pb-16`}>
        <div className="mx-auto max-w-[980px]">
          <TabbedWindow
            label="Where Lore answers"
            tabs={[
              { label: "Web app", panel: <div className="bg-bg p-4 md:p-6"><AnswerCard question="Why do we use short-lived JWTs instead of server sessions?" account="acme" when="asked by Priya · just now" result={SAMPLE} /></div> },
              { label: "Pull requests", panel: <PrMock /> },
              { label: "Terminal", panel: <TerminalMock /> },
              { label: "VS Code", panel: <EditorMock /> },
            ]}
          />
          <p className="m-0 mt-3 flex justify-center gap-2 text-[13px] leading-5 text-ink-3">
            <span aria-hidden="true" className="text-ok">✓</span> If Lore can&apos;t cite it, it doesn&apos;t say it.
          </p>
        </div>
      </section>

      {/* Facts */}
      <section className={`${section} pb-20`}>
        <dl className="m-0 grid gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-3">
          {FACTS.map(([value, label]) => (
            <div key={label} className="flex flex-col items-center gap-1 bg-surface px-6 py-7 text-center">
              <dt className="sr-only">{label}</dt>
              <dd className="m-0 font-mono text-[34px] leading-none font-medium tracking-[-0.02em]">{value}</dd>
              <dd className="m-0 max-w-[26ch] text-sm leading-5 text-ink-2">{label}</dd>
            </div>
          ))}
        </dl>
      </section>

      {/* Dark feature band */}
      <section id="features" className="scroll-mt-6 border-y border-[#2D2B27] bg-[#131311] py-20 text-[#ECE9E2] md:py-24">
        <div className={section}>
          <div className="mb-10 flex flex-wrap items-end justify-between gap-6">
            <h2 className={`${h2} max-w-[16ch] text-[#ECE9E2]`}>
              Built for <span className="font-mono text-[0.8em] tracking-normal text-[#80C2CC]">&lt;reviewers&gt;</span> who want sources, not summaries
            </h2>
            <p className="m-0 max-w-[44ch] text-base leading-[1.6] text-[#ABA69B]">
              Lore isn&apos;t a chatbot over your repo. It is a record of decisions, with the receipts, that answers where the questions
              come up.
            </p>
          </div>
          <TabbedWindow
            dark
            title="lore"
            label="What Lore does"
            tabs={[
              {
                label: "Cited answers",
                panel: (
                  <Feature title="Every claim, sourced" body="Before an answer reaches you, a citation check compares every source it cites against what Lore actually read. A draft that cites anything else is discarded.">
                    <div className="label mb-2">Citation check</div>
                    {[["✓", "acme/api#482", "read and cited"], ["✓", "RFC-07", "read and cited"], ["✕", "acme/api#391", "cited, never read: draft withheld"]].map(([g, ref, note]) => (
                      <div key={ref} className="flex gap-2 border-t border-[#E5E2DA] py-2 font-mono text-[12.5px]">
                        <span aria-hidden="true" className={g === "✓" ? "text-[#2E6A3A]" : "text-[#A2372A]"}>{g}</span>
                        <span className="font-medium">{ref}</span>
                        <span className="text-[#6E6A61]">{note}</span>
                      </div>
                    ))}
                  </Feature>
                ),
              },
              {
                label: "Decision check",
                panel: (
                  <Feature title="Reaches the reviewer who didn't ask" body="When a PR opens, Lore comments with the decisions still in force behind the files it changes, with the reasoning for each. No model in that path.">
                    <div className="label mb-2">Decisions behind this PR · 2</div>
                    {[["acme/api#482", "Short-lived JWTs over server sessions", "src/auth/session.ts"], ["ADR-004", "Postgres over MongoDB", "src/db/"]].map(([ref, title, file]) => (
                      <div key={ref} className="flex flex-col gap-0.5 border-t border-[#E5E2DA] py-2">
                        <span><span className="font-mono text-[12.5px] font-medium">{ref}</span> — {title}</span>
                        <span className="font-mono text-xs text-[#6E6A61]">changed {file} · ● in force</span>
                      </div>
                    ))}
                  </Feature>
                ),
              },
              {
                label: "Stale warnings",
                panel: (
                  <Feature title="Knows when history has moved on" body="A decision nobody formally replaced, whose files later PRs rewrote, is flagged as possibly outdated, with the PRs behind the flag, instead of being presented as current.">
                    <div className="rounded-lg border border-[#845400] bg-[#F8EED8] p-3">
                      <strong className="font-semibold"><span aria-hidden="true" className="text-[#845400]">△ </span>Possibly outdated.</strong> acme/api#482 changed 4 files in{" "}
                      <span className="font-mono text-xs">src/auth/</span>. Since then, 3 of them were rewritten by:
                      <div className="mt-2 flex flex-col gap-1 font-mono text-xs">
                        <span>acme/api#611 · Opaque session tokens for the admin console</span>
                        <span>acme/api#640 · Turn off refresh-token rotation for service clients</span>
                      </div>
                    </div>
                  </Feature>
                ),
              },
            ]}
          />
        </div>
      </section>

      {/* How it works */}
      <section id="how" className={`${section} scroll-mt-6 py-20 md:py-24`}>
        <p className="m-0 font-serif text-[26px] text-ink-3 md:text-[30px]">How it works</p>
        <h2 className={`${h2} mt-1`}>Merge a PR. Lore keeps the why.</h2>
        <div className="mt-12 flex flex-wrap gap-10 rounded-xl border border-line bg-surface p-6 md:p-10">
          <ol className="m-0 flex flex-[1_1_300px] list-none flex-col p-0">
            {STEPS.map(([title, body], i) => (
              <li key={title} className="relative flex gap-5 pb-8 last:pb-0">
                {i < STEPS.length - 1 && <span aria-hidden="true" className="absolute top-8 bottom-0 left-[15px] w-px bg-line" />}
                <span className="grid size-8 flex-none place-items-center rounded-full border border-accent bg-accent-soft font-mono text-xs font-medium text-accent">0{i + 1}</span>
                <div className="flex flex-col gap-1.5 pt-1">
                  <h3 className="m-0 text-[17px] leading-6 font-semibold">{title}</h3>
                  <p className="m-0 max-w-[46ch] text-[15px] leading-6 text-ink-2">{body}</p>
                </div>
              </li>
            ))}
          </ol>
          <div className="flex min-w-0 flex-[1_1_340px] flex-col gap-3 rounded-lg bg-bg p-5">
            <div className="label">Lineage · src/auth/</div>
            {[
              ["acme/api#120", "Server-side sessions in Redis", "→ Superseded", "text-ink-2"],
              ["acme/api#482", "Short-lived JWTs over server sessions", "● In force", "text-ok"],
            ].map(([ref, title, status, tone], i) => (
              <div key={ref}>
                {i > 0 && (
                  <blockquote className="m-0 mb-3 border-l-2 border-ok bg-ok-soft px-3 py-2 font-serif text-[15px] leading-6 italic">
                    “Supersedes #120: a Redis failover shouldn&apos;t log everyone out.”
                  </blockquote>
                )}
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-line bg-surface px-3.5 py-3 text-sm">
                  <span className="font-mono text-[13px] font-medium">{ref}</span>
                  <span className="text-ink-2">{title}</span>
                  <span className={`ml-auto text-xs font-medium ${tone}`}>{status}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Who asks */}
      <section className={`${section} pb-20 md:pb-24`}>
        <h2 className={`${h2} text-center`}>Who asks Lore</h2>
        <p className="m-0 mx-auto mt-3 max-w-[52ch] text-center text-base leading-[1.6] text-ink-2">The same memory, from three directions.</p>
        <div className="mt-10 grid gap-5 md:grid-cols-3">
          {ASKERS.map(([who, q, body]) => (
            <div key={who} className="flex flex-col gap-4 rounded-xl border border-line bg-surface p-6">
              <div className="label">{who}</div>
              <p className="m-0 font-serif text-[21px] leading-[1.35]">“{q}”</p>
              <p className="m-0 mt-auto text-sm leading-[22px] text-ink-2">{body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Trust */}
      <section id="trust" className="scroll-mt-6 border-y border-line bg-sunken py-20 md:py-24">
        <div className={section}>
          <h2 className={`${h2} text-center`}>Yours to run. Built to be checked.</h2>
          <p className="m-0 mx-auto mt-3 max-w-[58ch] text-center text-base leading-[1.6] text-ink-2">
            Your decisions are your team&apos;s history. Lore runs on your own infrastructure and shows its work at every step.
          </p>
          <div className="mt-10 grid gap-5 md:grid-cols-3">
            {TRUST.map(([glyph, title, body]) => (
              <div key={title} className="flex flex-col gap-3 rounded-xl border border-line bg-surface p-6">
                <span aria-hidden="true" className="grid size-9 place-items-center rounded-lg bg-accent-soft font-mono text-base text-accent">{glyph}</span>
                <h3 className="m-0 text-base font-semibold">{title}</h3>
                <p className="m-0 text-sm leading-[22px] text-ink-2">{body}</p>
              </div>
            ))}
          </div>
          <pre className="mx-auto mt-10 max-w-[560px] overflow-x-auto rounded-lg bg-[#1C1B19] px-5 py-4 font-mono text-[13px] leading-6 text-[#E4E1D9]">
            <span className="text-[#8D897F]">$</span> cp .env.example .env{"\n"}<span className="text-[#8D897F]">$</span> docker compose up{"\n"}<span className="text-[#8CC898]">✓</span> api, worker, web, postgres, qdrant
          </pre>
        </div>
      </section>

      {/* Final call to action */}
      <section className={`${section} flex flex-col items-center py-24 text-center md:py-32`}>
        <h2 className="m-0 max-w-[16ch] font-serif text-[44px] leading-[1.05] font-medium tracking-[-0.03em] md:text-[72px]">
          Give your codebase a <em className="text-accent">memory</em>.
        </h2>
        <div className="mt-9 flex flex-wrap justify-center gap-2.5">
          <Link href={primary.href} className={`${btn.primary} ${btn.lg} px-6`}>{primary.label} <span aria-hidden="true">→</span></Link>
          <a href={install} className={`${btn.secondary} ${btn.lg}`}>Install the GitHub App</a>
        </div>
      </section>

      <footer className="border-t border-line bg-sunken">
        <div className={`${section} grid gap-10 py-12 md:grid-cols-[1.5fr_1fr_1fr_1fr]`}>
          <div className="flex flex-col gap-3">
            <Wordmark size={24} />
            <p className="m-0 font-serif text-[15px] text-ink-2 italic">Lore remembers why.</p>
            <p className="m-0 max-w-[34ch] text-[13.5px] leading-5 text-ink-3">Decision memory for engineering teams. Open source, MIT licensed.</p>
          </div>
          {Object.entries(FOOTER).map(([heading, links]) => (
            <nav key={heading} aria-label={heading} className="flex flex-col gap-2.5 text-[13.5px]">
              <h3 className="m-0 mb-1 text-sm font-semibold">{heading}</h3>
              {links.map(([label, href]) => <a key={label} href={href} className="text-ink-2 no-underline hover:text-ink">{label}</a>)}
            </nav>
          ))}
        </div>
        <div className={`${section} border-t border-line py-5 font-mono text-xs text-ink-3`}>© 2026 Lore</div>
      </footer>
    </>
  );
}
