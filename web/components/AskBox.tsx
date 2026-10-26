"use client";

import { useState, useTransition } from "react";
import { ask, type AskResult } from "@/app/ask/actions";
import { AccountSwitcher } from "./AccountSwitcher";
import { AnswerCard } from "./AnswerCard";
import { Banner } from "./ui";

type Props = { account: string; accounts: string[]; starters: string[] };

export function AskBox({ account, accounts, starters }: Props) {
  const [q, setQ] = useState("");
  const [asked, setAsked] = useState("");
  const [outcome, setOutcome] = useState<AskResult | null>(null);
  const [pending, start] = useTransition();

  // The question stays in the box (controlled) so error and rate-limit states can retry it.
  const submit = (text = q) => {
    const question = text.trim();
    if (!question || pending) return;
    setQ(question);
    setAsked(question);
    start(async () => setOutcome(await ask(account, question)));
  };
  const idle = !asked;

  return (
    <div className="flex min-w-0 flex-col gap-[18px]">
      {idle && !q && (
        <div className="flex flex-col gap-1.5 pt-2">
          <h1 className="m-0 font-serif text-[32px] leading-[38px] font-medium tracking-[-0.02em]">Ask why.</h1>
          <p className="m-0 max-w-[56ch] text-[15px] leading-[23px] text-ink-2">
            Answers come only from merged PRs, ADRs and threads Lore has read, and always show where they came from.
          </p>
        </div>
      )}

      <form
        onSubmit={(e) => { e.preventDefault(); submit(); }}
        className="rounded-lg border border-line-strong bg-surface shadow-pop focus-within:border-accent focus-within:shadow-[0_0_0_3px_var(--color-accent-soft)]"
      >
        <label htmlFor="question" className="sr-only">Your question</label>
        <textarea
          id="question"
          rows={2}
          maxLength={2000}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); submit(); }
          }}
          placeholder="Why do we use JWTs instead of server sessions?"
          className="block min-h-[76px] w-full resize-none border-0 bg-transparent px-[18px] pt-4 pb-1.5 font-serif text-xl leading-[30px] text-ink outline-none placeholder:text-ink-3 focus-visible:outline-none"
        />
        <div className="flex flex-wrap items-center gap-x-2.5 gap-y-2 pt-2 pr-2.5 pb-2.5 pl-3">
          {accounts.length > 1 && <AccountSwitcher accounts={accounts} current={account} />}
          <span className="ml-auto flex items-center gap-2.5">
            <kbd className="hidden rounded-sm border border-line px-[5px] py-0.5 font-mono text-[11.5px] whitespace-nowrap text-ink-3 md:inline">⌘ ↵</kbd>
            <button
              type="submit"
              disabled={pending}
              className="h-9 min-w-16 rounded-md bg-ink px-4 text-sm font-medium text-bg hover:opacity-90 disabled:opacity-50"
            >
              {pending ? "Asking…" : "Ask"}
            </button>
          </span>
        </div>
      </form>

      {idle && starters.length > 0 && (
        <div className="flex flex-col gap-2.5">
          <div className="label">Others on {account} have asked</div>
          <div className="flex flex-wrap gap-2">
            {starters.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => submit(s)}
                className="min-h-9 rounded-lg border border-line bg-surface px-3 py-[7px] text-left text-[13.5px] leading-5 text-ink hover:border-line-strong hover:bg-sunken"
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      )}

      {outcome?.message && !pending && <Banner tone="danger" title={outcome.message} />}
      {asked && (pending || !outcome?.message) && (
        <AnswerCard
          question={asked}
          account={account}
          when={pending ? "asking now…" : "just now"}
          loading={pending}
          result={outcome?.result}
          failure={outcome?.failure}
          onRetry={() => submit()}
        />
      )}
    </div>
  );
}
