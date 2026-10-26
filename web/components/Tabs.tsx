"use client";

import { useId, useRef, useState } from "react";

type Tab = { label: string; panel: React.ReactNode };

/** Tabs inside a window frame; arrow keys move between tabs. `dark` is for the always-dark band. */
export function TabbedWindow({ label, tabs, dark = false, title }: { label: string; tabs: Tab[]; dark?: boolean; title?: string }) {
  const [active, setActive] = useState(0);
  const id = useId();
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKey = (e: React.KeyboardEvent) => {
    const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    const next = (active + step + tabs.length) % tabs.length;
    setActive(next);
    refs.current[next]?.focus();
  };
  const frame = dark ? "border-[#433F39] bg-[#22211E] text-[#ECE9E2]" : "border-line bg-surface";
  const rule = dark ? "border-[#433F39]" : "border-line";

  return (
    <div className={`overflow-hidden rounded-xl border ${frame} ${dark ? "" : "shadow-pop"}`}>
      <div className={`flex items-center gap-3 border-b px-4 py-2.5 ${rule}`}>
        <span aria-hidden="true" className="flex gap-1.5">
          {[0, 1, 2].map((i) => <span key={i} className={`size-2.5 rounded-full ${dark ? "bg-[#433F39]" : "bg-line-strong"}`} />)}
        </span>
        {title && <span className="mx-auto font-mono text-xs text-[#928D82]">{title}</span>}
      </div>
      <div role="tablist" aria-label={label} onKeyDown={onKey} className={`flex overflow-x-auto border-b ${rule}`}>
        {tabs.map((t, i) => (
          <button
            key={t.label}
            ref={(el) => { refs.current[i] = el; }}
            role="tab"
            id={`${id}-tab-${i}`}
            aria-selected={i === active}
            aria-controls={`${id}-panel-${i}`}
            tabIndex={i === active ? 0 : -1}
            onClick={() => setActive(i)}
            className={`min-h-11 flex-1 border-r px-4 text-left text-sm font-medium whitespace-nowrap last:border-r-0 ${rule} ${
              i === active
                ? dark ? "bg-[#2A2925] text-[#ECE9E2] shadow-[inset_0_-2px_0_#80C2CC]" : "bg-surface text-ink shadow-[inset_0_-2px_0_var(--color-accent)]"
                : dark ? "text-[#928D82] hover:text-[#ECE9E2]" : "bg-sunken text-ink-2 hover:text-ink"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tabs.map((t, i) => (
        <div key={t.label} role="tabpanel" id={`${id}-panel-${i}`} aria-labelledby={`${id}-tab-${i}`} hidden={i !== active} className="animate-fade">
          {t.panel}
        </div>
      ))}
    </div>
  );
}
