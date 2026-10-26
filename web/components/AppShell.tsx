import Link from "next/link";
import { signOut } from "@/auth";
import { MobileMenu, UserMenu } from "./NavMenus";
import { Wordmark } from "./ui";

// shortcut: Decisions and Settings are left out of the nav until those pages exist (next phase).
const LINKS = [
  { key: "ask", href: "/ask", label: "Ask" },
  { key: "connect", href: "/connect", label: "Connect GitHub" },
] as const;

type Props = {
  active: (typeof LINKS)[number]["key"];
  user: { name?: string | null; email?: string | null };
  width?: string;
  children: React.ReactNode;
};

export function AppShell({ active, user, width = "max-w-[1160px]", children }: Props) {
  const links = LINKS.map((l) => ({ href: l.href, label: l.label, current: l.key === active }));
  const doSignOut = async () => {
    "use server";
    await signOut({ redirectTo: "/" });
  };

  return (
    <>
      <header className="relative flex h-14 items-center gap-7 border-b border-line bg-bg px-4 md:px-6">
        <Wordmark />
        <span className="text-sm text-ink-2 md:hidden">{links.find((l) => l.current)?.label}</span>
        <nav aria-label="Main" className="hidden h-full gap-0.5 md:flex">
          {links.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              aria-current={l.current ? "page" : undefined}
              className={`flex h-full items-center px-2.5 text-sm font-medium no-underline hover:text-ink ${l.current ? "text-ink shadow-[inset_0_-2px_0_var(--color-ink)]" : "text-ink-2"}`}
            >
              {l.label}
            </Link>
          ))}
        </nav>
        <div className="ml-auto hidden md:block">
          <UserMenu name={user.name} email={user.email} signOut={doSignOut} />
        </div>
        <div className="ml-auto md:hidden">
          <MobileMenu links={links} email={user.email} signOut={doSignOut} />
        </div>
      </header>
      <main className={`mx-auto box-border ${width} px-4 pt-6 pb-12 md:px-8 md:pt-10 md:pb-16`}>{children}</main>
    </>
  );
}
