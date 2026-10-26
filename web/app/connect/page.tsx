import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { AppShell } from "@/components/AppShell";
import { Avatar, Banner, btn, Pill } from "@/components/ui";
import { accountsFor, keyFor } from "@/lib/accounts";
import { lore, type BackfillJob } from "@/lib/lore";

const errors: Record<string, [string, string]> = {
  state: ["That GitHub link expired.", "The round trip didn't start here, or took longer than 10 minutes. Try again."],
  code: ["GitHub didn't send an authorization back.", "Use “Link existing installations” to finish linking."],
  github: ["GitHub rejected the request.", "Check the App's client ID and secret, then try again."],
  lore: ["Linked on GitHub, but Lore couldn't create access.", "Check LORE_ADMIN_SECRET is the same on the website and the backend."],
};

type Progress = { repos_total?: number; repos_done?: number; prs_captured?: number };

/** Import status for an account's most recent backfill job (jobs.status: queued / running / done / error). */
function importStatus(job?: BackfillJob) {
  const p = (job?.progress ?? {}) as Progress;
  switch (job?.status) {
    case "queued":
      return { pill: <Pill tone="neutral" glyph="◷">Queued</Pill>, detail: "Waiting to start." };
    case "running": {
      const pct = p.repos_total ? Math.round(((p.repos_done ?? 0) / p.repos_total) * 100) : 0;
      return {
        pill: <Pill tone="accent" glyph="◐">Importing</Pill>,
        detail: `${p.repos_done ?? 0} of ${p.repos_total ?? "?"} repositories · ${p.prs_captured ?? 0} PRs so far`,
        pct,
      };
    }
    case "done":
      return { pill: <Pill tone="ok" glyph="✓">Done</Pill>, detail: `Imported ${p.prs_captured ?? 0} PRs.` };
    case "error":
      return { pill: <Pill tone="danger" glyph="✕">Failed</Pill>, detail: job.error ?? "The import failed.", failed: true };
    default:
      return { pill: <Pill tone="neutral" glyph="○">Not imported</Pill>, detail: "No import has run yet." };
  }
}

async function rerunBackfill(form: FormData) {
  "use server";
  const session = await auth();
  const login = String(form.get("login") ?? "");
  const key = session?.user?.id ? await keyFor(session.user.id, login) : null;
  if (!key) return;
  await lore(`/v1/backfill/run?account=${encodeURIComponent(login)}`, key, { method: "POST" });
  revalidatePath("/connect");
}

export default async function Connect({ searchParams }: { searchParams: Promise<{ linked?: string; error?: string }> }) {
  const session = await auth();
  if (!session?.user?.id) redirect("/login");
  const userId = session.user.id;
  const { linked, error } = await searchParams;
  const accounts = await accountsFor(userId);
  const jobs = await Promise.all(
    accounts.map(async (a) => {
      const key = await keyFor(userId, a.login);
      return lore<{ jobs: BackfillJob[] }>(`/v1/backfill/status?installation_id=${a.installation_id}`, key!)
        .then((r) => r.jobs[0])
        .catch(() => undefined);
    }),
  );

  return (
    <AppShell active="connect" user={session.user} width="max-w-[920px]">
      <div className="flex flex-col gap-7">
        {linked && linked !== "0" && (
          <Banner tone="success" title={`Linked ${linked} account${linked === "1" ? "" : "s"}.`}>
            Lore is importing their merged PRs. You can ask as soon as the first import finishes.
          </Banner>
        )}
        {linked === "0" && (
          <Banner tone="info" title="GitHub found no installations you can reach.">Install the App first, or ask whoever installed it to add you.</Banner>
        )}
        {error && (
          <Banner tone="danger" title={(errors[error] ?? ["Something went wrong."])[0]}>{(errors[error] ?? ["", "Try again."])[1]}</Banner>
        )}

        <div className="flex flex-col gap-3">
          <h1 className="m-0 font-serif text-[28px] leading-[34px] font-medium tracking-[-0.02em] md:text-[34px] md:leading-10">Connect GitHub</h1>
          <p className="m-0 max-w-[64ch] text-[15.5px] leading-[25px] text-ink-2">
            Lore learns from the merged pull requests of every account where its GitHub App is installed: PR descriptions, review
            threads, and the ADRs and RFCs they link to. You choose the repositories during install and can change them on GitHub at
            any time.
          </p>
          <div className="flex flex-wrap items-center gap-2.5 pt-1.5">
            <a href="/api/github/start?to=install" className={`${btn.primary} ${btn.lg}`}>Install the GitHub App <span aria-hidden="true">↗</span></a>
            <a href="/api/github/start" className={`${btn.secondary} ${btn.lg}`}>Link existing installations</a>
          </div>
        </div>

        {accounts.length === 0 ? (
          <div className="flex flex-col gap-5 rounded-lg border border-dashed border-line-strong bg-surface p-5 md:px-8 md:py-7">
            <div className="flex flex-col gap-1.5">
              <h2 className="m-0 font-serif text-[22px] leading-[30px] font-medium">No accounts linked yet</h2>
              <p className="m-0 max-w-[56ch] text-[14.5px] leading-[23px] text-ink-2">Lore has nothing to remember until it can read your PRs. Linking takes a minute:</p>
            </div>
            <ol className="m-0 flex list-none flex-col p-0">
              {[
                ["Install the GitHub App", "on your org or personal account, and pick repositories."],
                ["Come back here.", "GitHub sends you back and the account links itself."],
                ["Ask your first question", "once the import finishes."],
              ].map(([lead, rest], i) => (
                <li key={lead} className="flex gap-3.5 border-t border-line py-3 text-[14.5px] leading-[22px]">
                  <span className="font-mono text-xs leading-[22px] font-medium text-ink-3">0{i + 1}</span>
                  <span><strong className="font-semibold">{lead}</strong> {rest}</span>
                </li>
              ))}
            </ol>
            <p className="m-0 text-[13.5px] leading-5 text-ink-3">
              Someone on your team already installed it? Use <a href="/api/github/start" className="text-ink">Link existing installations</a>.
            </p>
          </div>
        ) : (
          <section aria-labelledby="linked" className="flex flex-col gap-3">
            <div className="flex items-baseline gap-2.5">
              <h2 id="linked" className="m-0 text-[15px] leading-[22px] font-semibold">Linked accounts</h2>
              <span className="font-mono text-xs text-ink-3">{accounts.length}</span>
            </div>
            <ul className="m-0 list-none overflow-hidden rounded-lg border border-line bg-surface p-0">
              {accounts.map((a, i) => {
                const s = importStatus(jobs[i]);
                return (
                  <li key={a.login} className="flex flex-wrap items-start gap-x-4 gap-y-3 border-t border-line px-[18px] py-4 first:border-t-0">
                    <Avatar name={a.login} />
                    <div className="flex min-w-0 flex-[1_1_220px] flex-col gap-1">
                      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5">
                        <span className="font-mono text-[15px] font-medium">{a.login}</span>
                        {s.pill}
                      </div>
                      <span className={`text-[13.5px] leading-5 ${s.failed ? "text-ink" : "text-ink-2"}`}>{s.detail}</span>
                      {s.pct !== undefined && (
                        <div
                          role="progressbar"
                          aria-valuenow={s.pct}
                          aria-valuemin={0}
                          aria-valuemax={100}
                          aria-label={`Import progress for ${a.login}`}
                          className="mt-1 h-1 max-w-[360px] overflow-hidden rounded-xs bg-sunken"
                        >
                          <div className="h-full bg-accent" style={{ width: `${s.pct}%` }} />
                        </div>
                      )}
                    </div>
                    <form action={rerunBackfill}>
                      <input type="hidden" name="login" value={a.login} />
                      <button className={`${btn.secondary} ${btn.sm}`}>Re-run import</button>
                    </form>
                  </li>
                );
              })}
            </ul>
            <p className="m-0 text-[13px] leading-5 text-ink-3">Re-running re-reads every merged PR. Answers keep working from the current import while it runs.</p>
          </section>
        )}
      </div>
    </AppShell>
  );
}
