"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

export type NavLink = { href: string; label: string; current: boolean };

// Close on Escape or a click outside the menu.
function useDismiss(open: boolean, close: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    const onClick = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && close();
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onClick);
    };
  }, [open, close]);
  return ref;
}

const initials = (s: string) => s.split(/[\s@._-]+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("");

export function UserMenu({ name, email, signOut }: { name?: string | null; email?: string | null; signOut: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const ref = useDismiss(open, () => setOpen(false));
  const who = name || email || "";
  return (
    <div ref={ref} className="relative ml-auto">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex h-8 items-center gap-2 rounded-full border border-line bg-surface pr-2 pl-1 text-[13px] font-medium text-ink-2"
      >
        <span className="grid size-6 place-items-center rounded-full border border-line-strong bg-sunken font-mono text-[11px] font-medium text-ink">
          {initials(who)}
        </span>
        <span>{email}</span>
        <span aria-hidden="true" className="text-[10px]">▾</span>
      </button>
      {open && (
        <div role="menu" className="absolute top-10 right-0 z-20 w-60 rounded-lg border border-line bg-surface p-1.5 shadow-pop">
          <div className="mb-1 border-b border-line px-2.5 pt-2 pb-2.5">
            {name && <div className="text-[13px] font-medium">{name}</div>}
            <div className="font-mono text-xs text-ink-3">{email}</div>
          </div>
          <form action={signOut}>
            <button role="menuitem" className="block w-full rounded-md px-2.5 py-2 text-left text-sm hover:bg-sunken">Sign out</button>
          </form>
        </div>
      )}
    </div>
  );
}

export function MobileMenu({ links, email, signOut }: { links: NavLink[]; email?: string | null; signOut: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const ref = useDismiss(open, () => setOpen(false));
  return (
    <div ref={ref} className="ml-auto">
      <button
        type="button"
        aria-expanded={open}
        aria-controls="mobile-nav"
        onClick={() => setOpen(!open)}
        className="flex h-11 min-w-11 items-center gap-2 rounded-lg border border-line bg-surface px-3 text-sm font-medium"
      >
        <span aria-hidden="true" className="text-base leading-none">{open ? "×" : "≡"}</span>
        Menu
      </button>
      {open && (
        <nav id="mobile-nav" aria-label="Main" className="absolute inset-x-0 top-14 z-20 flex flex-col border-y border-line bg-bg px-4 pt-2 pb-4">
          {links.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              aria-current={l.current ? "page" : undefined}
              onClick={() => setOpen(false)}
              className={`flex min-h-12 items-center gap-2.5 border-b border-line text-[17px] font-medium no-underline ${l.current ? "text-ink" : "text-ink-2"}`}
            >
              <span aria-hidden="true" className={`h-[18px] w-[3px] rounded-sm ${l.current ? "bg-accent" : ""}`} />
              {l.label}
            </Link>
          ))}
          <form action={signOut} className="flex items-center gap-2.5 pt-3.5">
            <span className="font-mono text-[13px] text-ink-3">{email}</span>
            <button className="ml-auto flex min-h-11 items-center text-sm text-ink">Sign out</button>
          </form>
        </nav>
      )}
    </div>
  );
}
