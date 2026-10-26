"use client";

import { useState } from "react";
import type { HistoryItem } from "@/lib/lore";
import { TypeBadge } from "./ui";

/** Team history disclosure list; only one item is open at a time. */
export function HistoryList({ items }: { items: (HistoryItem & { when: string })[] }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <ul className="m-0 list-none border-b border-line p-0">
      {items.map((h, i) => {
        const isOpen = open === i;
        const n = h.sources?.length ?? 0;
        return (
          <li key={h.created_at + h.question} className="border-t border-line">
            <button
              type="button"
              aria-expanded={isOpen}
              onClick={() => setOpen(isOpen ? null : i)}
              className="flex w-full gap-3 py-3 text-left"
            >
              <span className="flex min-w-0 flex-1 flex-col gap-[3px]">
                <span className="text-sm leading-5 font-medium text-ink">{h.question}</span>
                <span className="flex flex-wrap gap-x-2 gap-y-1 text-[12.5px] leading-[18px] text-ink-3">
                  <span>{h.when}{n > 0 && ` · ${n} source${n === 1 ? "" : "s"}`}</span>
                  {n === 0 && <span className="text-ink-2">No answer on record</span>}
                </span>
              </span>
              <span aria-hidden="true" className="font-mono text-xs leading-5 text-ink-3">{isOpen ? "−" : "+"}</span>
            </button>
            {isOpen && (
              <div className="flex flex-col gap-2.5 pb-3.5">
                <p className="m-0 font-serif text-[15px] leading-6 text-ink">{h.answer}</p>
                {n > 0 && (
                  <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
                    {h.sources.map((s) => {
                      const [ref, ...title] = s[1].split(" — ");
                      return (
                        <li key={s[1]} className="flex items-baseline gap-2 text-[13px] leading-[19px]">
                          <TypeBadge type={s[0]} compact />
                          <span>
                            <span className="font-mono text-[12.5px]">{ref}</span>
                            {title.length > 0 && <><span className="text-ink-3"> — </span>{title.join(" — ")}</>}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
