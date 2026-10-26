// AnswerCard and its states (LORE-DESIGN-SPEC.md §7–8). No hooks, so pages and AskBox can both render it.
import type { Source, WhyResult } from "@/lib/lore";
import { btn, TypeBadge } from "./ui";

export type Failure = "rate" | "error";

type Props = {
  question: string;
  account: string;
  when: string;
  loading?: boolean;
  result?: WhyResult;
  failure?: Failure;
  onRetry?: () => void;
};

/** "acme/api#482 — Move to JWT access tokens" → ref and title. */
const split = (label: string) => {
  const [ref, ...rest] = label.split(" — ");
  return { ref, title: rest.join(" — ") };
};

// Only http(s) links render as anchors; a PR ref like acme/api#482 without a URL still gets one.
function href([kind, label, url]: Source): string | undefined {
  if (url?.startsWith("https://")) return url;
  const pr = kind === "PR" && /^([\w.-]+\/[\w.-]+)#(\d+)$/.exec(split(label).ref);
  return pr ? `https://github.com/${pr[1]}/pull/${pr[2]}` : undefined;
}

/** Turns the agent's inline `[acme/api#482]` citations into numbered `[1]` links to the source list. */
function Prose({ text, refs }: { text: string; refs: string[] }) {
  return text.split(/(\[[^\]\n]+\])/g).map((part, i) => {
    const n = part.startsWith("[") ? refs.indexOf(part.slice(1, -1)) + 1 : 0;
    return n ? (
      <a key={i} href={`#src-${n}`} aria-label={`Source ${n}`} className="relative -top-[0.5em] px-px font-mono text-[11px] leading-none font-medium text-accent no-underline">
        [{n}]
      </a>
    ) : (
      part
    );
  });
}

const lookups = (hops?: number) => (hops ? <span>{hops} lookup{hops === 1 ? "" : "s"}</span> : null);

function Footer({ children }: { children: React.ReactNode }) {
  return (
    <footer className="flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-line bg-sunken px-6 py-[11px] text-[13px] leading-5 text-ink-2">
      {children}
    </footer>
  );
}

function StateHead({ glyph, glyphCls, title, children }: { glyph: string; glyphCls: string; title: string; children?: React.ReactNode }) {
  return (
    <div className="flex items-start gap-3.5">
      <span aria-hidden="true" className={`grid size-[30px] flex-none place-items-center rounded-full font-mono text-sm font-semibold ${glyphCls}`}>
        {glyph}
      </span>
      <div className="flex flex-col gap-1.5">
        <p className="m-0 font-serif text-[19px] leading-[27px] font-medium">{title}</p>
        {children && <div className="m-0 max-w-[62ch] text-[14.5px] leading-[23px] text-ink-2">{children}</div>}
      </div>
    </div>
  );
}

function Loading({ account }: { account: string }) {
  const sheen = "h-2.5 rounded-[3px] bg-[linear-gradient(90deg,var(--color-sunken)_0%,var(--color-line)_50%,var(--color-sunken)_100%)] bg-[length:480px_100%] animate-sheen";
  // shortcut: no step-by-step LookupTrace — /v1/why doesn't stream progress; add SSE to the backend to show it.
  return (
    <div className="flex flex-col gap-[18px] px-6 pt-[18px] pb-6">
      <div className="flex items-center gap-2.5 text-sm text-ink-2">
        <span aria-hidden="true" className="size-2 flex-none animate-pulse-dot rounded-full bg-accent" />
        Looking through {account}&apos;s decisions
      </div>
      <div aria-hidden="true" className="flex flex-col gap-2.5 pt-1">
        <div className={`${sheen} w-[94%]`} />
        <div className={`${sheen} w-[82%]`} />
        <div className={`${sheen} w-[48%]`} />
      </div>
      <p className="m-0 text-[13px] text-ink-3">The answer appears once every citation has been checked against what Lore read.</p>
    </div>
  );
}

function Answered({ result }: { result: WhyResult }) {
  const refs = result.sources.map((s) => split(s[1]).ref);
  const n = result.sources.length;
  return (
    <div className="animate-fade">
      <div className="px-6 pt-3.5 pb-5">
        <p className="m-0 max-w-[64ch] font-serif text-lg leading-[29px] whitespace-pre-wrap">
          <Prose text={result.answer} refs={refs} />
        </p>
      </div>
      <section aria-label="Sources" className="px-6 pb-1.5">
        <div className="flex items-baseline gap-2 pb-2">
          <h3 className="label m-0">Sources</h3>
          <span className="font-mono text-[11px] text-ink-3">{n}</span>
        </div>
        <ol className="m-0 list-none p-0">
          {result.sources.map((s, i) => {
            const { ref, title } = split(s[1]);
            const link = href(s);
            return (
              <li key={s[1]} id={`src-${i + 1}`} className="flex flex-wrap items-start gap-3 border-t border-line py-3 sm:flex-nowrap">
                <span className="w-4 flex-none font-mono text-xs leading-5 font-medium text-accent">{i + 1}</span>
                <TypeBadge type={s[0]} />
                <div className="min-w-0 flex-1 basis-48 text-sm leading-5">
                  <span className="font-mono text-[13px] font-medium">{ref}</span>
                  {title && (
                    <>
                      <span className="text-ink-3"> — </span>
                      {title}
                    </>
                  )}
                </div>
                {link ? (
                  <a href={link} target="_blank" rel="noreferrer" className="flex-none text-[13px] leading-5 text-accent underline-offset-2">
                    GitHub ↗
                  </a>
                ) : (
                  <span className="flex-none text-[12.5px] leading-5 text-ink-3">No link</span>
                )}
              </li>
            );
          })}
        </ol>
      </section>
      <Footer>
        {result.guardrail?.ok ? (
          <span className="inline-flex items-center gap-1.5">
            <span aria-hidden="true" className="font-semibold text-ok">✓</span>Citations checked · {n} of {n} sources read
          </span>
        ) : (
          <span>{n} source{n === 1 ? "" : "s"}</span>
        )}
        {lookups(result.hops)}
      </Footer>
    </div>
  );
}

function Unknown({ result }: { result: WhyResult }) {
  return (
    <>
      <div className="flex flex-col gap-[18px] px-6 pt-4 pb-[22px]">
        <StateHead glyph="?" glyphCls="border border-dashed border-line-strong font-serif font-medium text-ink-2" title="I don't know. Nothing Lore can cite explains this.">
          <p className="m-0">{result.answer}</p>
        </StateHead>
        <div className="flex flex-col sm:pl-11">
          <div className="label pb-1.5">What you can do</div>
          {[
            "Ask whoever last changed the code in question; the PR that introduced it is the best lead.",
            <>Once you know, write it down: a <code className="font-mono text-[13px]">Why:</code> trailer on a commit or a line in the PR description becomes something Lore can cite next time.</>,
            "Try a narrower question, for example name the file or the PR that introduced it.",
          ].map((step, i) => (
            <div key={i} className="flex gap-2.5 border-t border-line py-2.5 text-sm leading-[21px]">
              <span className="font-mono text-xs leading-[21px] font-medium text-ink-3">{i + 1}</span>
              <span>{step}</span>
            </div>
          ))}
        </div>
      </div>
      <Footer>
        <span>Nothing cited, so nothing to check</span>
        {lookups(result.hops)}
      </Footer>
    </>
  );
}

function Blocked({ result, onRetry }: { result: WhyResult; onRetry?: () => void }) {
  const read = result.guardrail?.matched ?? [];
  const unread = result.guardrail?.unknown ?? [];
  return (
    <>
      <div className="flex flex-col gap-[18px] px-6 pt-4 pb-[22px]">
        <StateHead
          glyph="⊘"
          glyphCls="border border-line-strong bg-sunken text-[13px] text-ink"
          title={unread.length ? "Answer withheld. The draft cited something Lore didn't read." : "Answer withheld. The draft didn't back up its claims."}
        >
          <p className="m-0">
            {unread.length
              ? "The draft referred to sources that weren't among the ones Lore opened for this question. Rather than show a claim it can't back up, Lore discarded the draft."
              : "The draft made claims without citing anything Lore read, so Lore discarded it rather than show an unsourced answer."}
          </p>
        </StateHead>
        {(read.length > 0 || unread.length > 0) && (
          <div className="flex flex-wrap gap-3 sm:pl-11">
            {read.length > 0 && (
              <div className="flex flex-[1_1_220px] flex-col gap-2 rounded-lg border border-line px-3.5 py-3">
                <div className="label">Cited and read · {read.length}</div>
                {read.map((r) => (
                  <div key={r} className="flex gap-2 font-mono text-[13px]"><span aria-hidden="true" className="text-ok">✓</span>{r}</div>
                ))}
              </div>
            )}
            {unread.length > 0 && (
              <div className="flex flex-[1_1_220px] flex-col gap-2 rounded-lg border border-danger bg-danger-soft px-3.5 py-3">
                <div className="label !text-danger">Cited, never read · {unread.length}</div>
                {unread.map((r) => (
                  <div key={r} className="flex gap-2 font-mono text-[13px]"><span aria-hidden="true" className="text-danger">✕</span>{r}</div>
                ))}
              </div>
            )}
          </div>
        )}
        {onRetry && (
          <div className="sm:pl-11">
            <button type="button" onClick={onRetry} className={`${btn.primary} ${btn.md}`}>Ask again</button>
          </div>
        )}
      </div>
      <Footer>
        <span className="inline-flex gap-1.5"><span aria-hidden="true" className="font-semibold text-danger">✕</span>Citation check failed · draft discarded</span>
        {lookups(result.hops)}
      </Footer>
    </>
  );
}

function Failed({ failure, onRetry }: { failure: Failure; onRetry?: () => void }) {
  const rate = failure === "rate";
  return (
    <div className="flex flex-col gap-3 px-6 pt-4 pb-[22px]">
      <StateHead
        glyph={rate ? "◷" : "!"}
        glyphCls={rate ? "border border-line-strong font-medium text-ink-2" : "border border-danger bg-danger-soft text-danger"}
        title={rate ? "You've hit the question limit for now." : "Lore couldn't finish this answer."}
      >
        <p className="m-0">
          {rate
            ? "Wait a minute, then ask again. Your question is kept in the box, and team history still works."
            : "Lore didn't respond. Nothing was saved to history, and your question is still in the box."}
        </p>
      </StateHead>
      {onRetry && (
        <div className="sm:pl-11">
          <button type="button" onClick={onRetry} className={`${rate ? btn.secondary : btn.primary} ${btn.md}`}>Try again</button>
        </div>
      )}
    </div>
  );
}

export function AnswerCard({ question, account, when, loading, result, failure, onRetry }: Props) {
  const blocked = result?.guardrail?.status === "violation";
  return (
    <article aria-live="polite" aria-busy={!!loading} className="overflow-hidden rounded-lg border border-line bg-surface text-left">
      <header className="flex flex-col gap-1.5 px-6 pt-5">
        <div className="flex flex-wrap items-center gap-1.5 font-mono text-xs text-ink-3">
          <span>{account}</span>
          <span aria-hidden="true">·</span>
          <span>{when}</span>
        </div>
        <h2 className="m-0 font-serif text-[22px] leading-[30px] font-medium tracking-[-0.01em]">{question}</h2>
      </header>
      {loading ? (
        <Loading account={account} />
      ) : failure ? (
        <Failed failure={failure} onRetry={onRetry} />
      ) : result && blocked ? (
        <Blocked result={result} onRetry={onRetry} />
      ) : result && result.sources.length === 0 ? (
        <Unknown result={result} />
      ) : result ? (
        <Answered result={result} />
      ) : null}
    </article>
  );
}
