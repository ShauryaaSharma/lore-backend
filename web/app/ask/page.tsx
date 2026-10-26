import Link from "next/link";
import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { AppShell } from "@/components/AppShell";
import { AskBox } from "@/components/AskBox";
import { HistoryList } from "@/components/HistoryList";
import { btn } from "@/components/ui";
import { accountsFor, keyFor } from "@/lib/accounts";
import { lore, type HistoryItem } from "@/lib/lore";

const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

/** "2 hours ago", formatted on the server so it can't differ between server and browser renders. */
function ago(iso: string): string {
  const s = (new Date(iso).getTime() - Date.now()) / 1000;
  if (s > -60) return "just now";
  for (const [unit, size] of [["year", 31536000], ["month", 2592000], ["week", 604800], ["day", 86400], ["hour", 3600], ["minute", 60]] as const) {
    if (Math.abs(s) >= size) return rtf.format(Math.round(s / size), unit);
  }
  return "just now";
}

export default async function Ask({ searchParams }: { searchParams: Promise<{ account?: string }> }) {
  const session = await auth();
  if (!session?.user?.id) redirect("/login");
  const accounts = await accountsFor(session.user.id);

  if (accounts.length === 0) {
    return (
      <AppShell active="ask" user={session.user} width="max-w-[920px]">
        <div className="flex flex-col gap-4 rounded-lg border border-dashed border-line-strong bg-surface p-5 md:px-8 md:py-7">
          <h1 className="m-0 font-serif text-[22px] leading-[30px] font-medium">Connect GitHub first</h1>
          <p className="m-0 max-w-[56ch] text-[14.5px] leading-[23px] text-ink-2">
            Lore answers only from your team&apos;s pull requests, so it needs a GitHub account with the App installed.
          </p>
          <Link href="/connect" className={`${btn.primary} ${btn.lg} self-start`}>Connect GitHub</Link>
        </div>
      </AppShell>
    );
  }

  const { account } = await searchParams;
  const current = accounts.find((a) => a.login === account)?.login ?? accounts[0].login;
  const key = await keyFor(session.user.id, current);
  const history = await lore<{ queries: HistoryItem[] }>("/v1/why/history?limit=20", key!)
    .then((r) => r.queries.map((q) => ({ ...q, when: ago(q.created_at) })))
    .catch(() => null);
  const starters = [...new Set((history ?? []).filter((h) => h.sources?.length).map((h) => h.question))].slice(0, 4);

  return (
    <AppShell active="ask" user={session.user}>
      <div className="flex flex-wrap items-start gap-x-14 gap-y-10">
        <div className="min-w-0 flex-[3_1_520px]">
          <AskBox key={current} account={current} accounts={accounts.map((a) => a.login)} starters={starters} />
        </div>
        <aside aria-labelledby="history" className="min-w-0 flex-[1_1_300px] md:max-w-[340px] md:pt-3.5">
          <div className="flex items-baseline gap-2 pb-2.5">
            <h2 id="history" className="m-0 text-sm leading-5 font-semibold">Team history</h2>
            <span className="text-[12.5px] text-ink-3">recent questions in {current}</span>
          </div>
          {history === null ? (
            <p className="m-0 border-t border-line pt-3 text-[13px] text-ink-3">History is unavailable right now.</p>
          ) : history.length === 0 ? (
            <p className="m-0 border-t border-line pt-3 text-[13px] text-ink-3">Nothing asked yet. Questions your team asks show up here.</p>
          ) : (
            <HistoryList items={history} />
          )}
        </aside>
      </div>
    </AppShell>
  );
}
