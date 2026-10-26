import { NextResponse, type NextRequest } from "next/server";
import { auth } from "@/auth";
import { link } from "@/lib/accounts";

type Installations = { installations: { id: number; account: { login: string } }[] };

// GitHub sends users here after installing the App (with "Request user authorization during
// installation" on) or after /api/github/start's OAuth authorize. Both carry a code and our state.
export async function GET(req: NextRequest) {
  const base = process.env.AUTH_URL ?? req.url;
  const back = (query: string) => NextResponse.redirect(new URL(`/connect?${query}`, base));
  const session = await auth();
  if (!session?.user?.id) return NextResponse.redirect(new URL("/login", base));

  const params = req.nextUrl.searchParams;
  const state = params.get("state");
  if (!state || state !== req.cookies.get("gh_state")?.value) return back("error=state");
  const code = params.get("code");
  if (!code) return back("error=code");

  const tokenRes = await fetch("https://github.com/login/oauth/access_token", {
    method: "POST",
    headers: { accept: "application/json", "content-type": "application/json" },
    body: JSON.stringify({
      client_id: process.env.AUTH_GITHUB_ID,
      client_secret: process.env.AUTH_GITHUB_SECRET,
      code,
    }),
  });
  const { access_token } = (await tokenRes.json()) as { access_token?: string };
  if (!access_token) return back("error=github");

  // Never trust installation_id from the query string: ask GitHub which installations this user can reach.
  const res = await fetch("https://api.github.com/user/installations?per_page=100", {
    headers: { authorization: `Bearer ${access_token}`, accept: "application/vnd.github+json" },
  });
  if (!res.ok) return back("error=github");
  const { installations } = (await res.json()) as Installations;

  try {
    for (const i of installations) await link(session.user.id, i.account.login.toLowerCase(), i.id);
  } catch (err) {
    console.error("linking GitHub installations failed", err);
    return back("error=lore");
  }

  const out = back(`linked=${installations.length}`);
  out.cookies.delete("gh_state");
  return out;
}
