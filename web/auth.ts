import PostgresAdapter from "@auth/pg-adapter";
import NextAuth from "next-auth";
import GitHub from "next-auth/providers/github";
import Google from "next-auth/providers/google";
import Nodemailer from "next-auth/providers/nodemailer";
import { pool } from "@/lib/db";

// A provider shows up only once its credentials are set, so local dev works with any one of them.
export const enabled = {
  github: !!process.env.AUTH_GITHUB_ID,
  google: !!process.env.AUTH_GOOGLE_ID,
  email: !!process.env.EMAIL_SERVER,
};

export const { handlers, auth, signIn, signOut } = NextAuth({
  adapter: PostgresAdapter(pool),
  providers: [
    ...(enabled.github ? [GitHub] : []),
    ...(enabled.google ? [Google] : []),
    ...(enabled.email ? [Nodemailer({ server: process.env.EMAIL_SERVER, from: process.env.EMAIL_FROM, maxAge: 15 * 60 })] : []),
  ],
  pages: { signIn: "/login", verifyRequest: "/login?sent=1", error: "/login" },
  callbacks: {
    session({ session, user }) {
      session.user.id = user.id;
      return session;
    },
  },
});
