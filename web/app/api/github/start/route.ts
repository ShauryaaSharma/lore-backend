import { randomBytes } from "node:crypto";
import { NextResponse, type NextRequest } from "next/server";
import { auth } from "@/auth";

// ?to=install opens the App install page; anything else re-links installations the user already has.
export async function GET(req: NextRequest) {
  const base = process.env.AUTH_URL ?? req.url;
  if (!(await auth())) return NextResponse.redirect(new URL("/login", base));

  const state = randomBytes(16).toString("hex");
  const target =
    req.nextUrl.searchParams.get("to") === "install"
      ? `https://github.com/apps/${process.env.GITHUB_APP_SLUG}/installations/new?state=${state}`
      : `https://github.com/login/oauth/authorize?${new URLSearchParams({
          client_id: process.env.AUTH_GITHUB_ID ?? "",
          redirect_uri: new URL("/api/github/callback", base).toString(),
          state,
        })}`;

  const res = NextResponse.redirect(target);
  res.cookies.set("gh_state", state, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    maxAge: 600,
    path: "/",
  });
  return res;
}
