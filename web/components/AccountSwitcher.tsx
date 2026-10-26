"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Avatar } from "./ui";

/** Listbox of linked accounts: arrow keys move, Enter picks, Esc closes. Picking reloads /ask for that account. */
export function AccountSwitcher({ accounts, current }: { accounts: string[]; current: string }) {
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const trigger = useRef<HTMLButtonElement>(null);
  const options = useRef<(HTMLButtonElement | null)[]>([]);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    options.current[Math.max(accounts.indexOf(current), 0)]?.focus();
    const onClick = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open, accounts, current]);

  const close = () => {
    setOpen(false);
    trigger.current?.focus();
  };
  const pick = (login: string) => {
    close();
    if (login !== current) router.push(`/ask?account=${encodeURIComponent(login)}`);
  };
  const onKey = (e: React.KeyboardEvent, i: number) => {
    if (e.key === "Escape") return close();
    const step = e.key === "ArrowDown" ? 1 : e.key === "ArrowUp" ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    options.current[(i + step + accounts.length) % accounts.length]?.focus();
  };

  return (
    <div ref={box} className="relative">
      <button
        ref={trigger}
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`Account to ask: ${current}`}
        onClick={() => setOpen(!open)}
        className="flex h-8 items-center gap-2 rounded-md border border-line bg-bg pr-2.5 pl-1.5 text-[13px] font-medium text-ink"
      >
        <Avatar name={current} size={20} />
        {current}
        <span aria-hidden="true" className="text-[9px] text-ink-3">▾</span>
      </button>
      {open && (
        <div role="listbox" aria-label="Linked GitHub accounts" className="absolute top-[38px] left-0 z-10 w-[280px] rounded-lg border border-line bg-surface p-1.5 shadow-pop">
          <div className="label px-2 pt-1.5 pb-2">Ask within</div>
          {accounts.map((login, i) => (
            <button
              key={login}
              ref={(el) => { options.current[i] = el; }}
              type="button"
              role="option"
              aria-selected={login === current}
              onClick={() => pick(login)}
              onKeyDown={(e) => onKey(e, i)}
              className="flex w-full items-center gap-2.5 rounded-md p-2 text-left hover:bg-sunken"
            >
              <Avatar name={login} size={28} />
              <span className="flex-1 text-sm font-medium">{login}</span>
              <span aria-hidden="true" className="text-[13px] text-accent">{login === current ? "✓" : ""}</span>
            </button>
          ))}
          <Link href="/connect" className="mt-1 block border-t border-line px-2 pt-2.5 pb-1.5 text-[13px] text-ink-2 no-underline">
            Link another account →
          </Link>
        </div>
      )}
    </div>
  );
}
