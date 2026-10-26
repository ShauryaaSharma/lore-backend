// Design-system primitives (LORE-DESIGN-SPEC.md §7). Server-safe: no hooks.
import Link from "next/link";

const base = "inline-flex items-center justify-center gap-2 rounded-md font-medium whitespace-nowrap no-underline";

export const btn = {
  primary: `${base} bg-ink text-bg hover:opacity-90 disabled:border disabled:border-line disabled:bg-sunken disabled:text-ink-3`,
  secondary: `${base} border border-line-strong bg-surface text-ink hover:bg-sunken`,
  quiet: "text-ink-2 underline decoration-line-strong underline-offset-3 hover:text-ink",
  sm: "h-8 px-3 text-[13px]",
  md: "h-9 px-3.5 text-sm",
  lg: "h-11 px-[18px] text-[15px]",
};

export const field =
  "h-11 w-full rounded-md border border-line-strong bg-surface px-3 text-[15px] text-ink outline-none placeholder:text-ink-3 focus:border-accent focus:shadow-[0_0_0_3px_var(--color-accent-soft)]";

export function Wordmark({ size = 25, href = "/" }: { size?: number; href?: string }) {
  return (
    <Link href={href} aria-label="Lore home" className="flex items-start text-ink no-underline">
      <span className="font-serif leading-none font-medium tracking-[-0.02em]" style={{ fontSize: size }}>Lore</span>
      <span className="font-mono text-[10px] leading-none font-medium text-accent">[1]</span>
    </Link>
  );
}

const bannerTone = {
  success: { glyph: "✓", cls: "border-ok bg-ok-soft", glyphCls: "text-ok", role: "status" },
  info: { glyph: "i", cls: "border-line-strong bg-sunken", glyphCls: "text-ink-2", role: "status" },
  warn: { glyph: "△", cls: "border-warn bg-warn-soft", glyphCls: "text-warn", role: "alert" },
  danger: { glyph: "!", cls: "border-danger bg-danger-soft", glyphCls: "text-danger", role: "alert" },
} as const;

export function Banner({ tone, title, children }: { tone: keyof typeof bannerTone; title: string; children?: React.ReactNode }) {
  const t = bannerTone[tone];
  return (
    <div role={t.role} className={`flex gap-3 rounded-lg border px-3.5 py-3 text-sm leading-[21px] text-ink ${t.cls}`}>
      <span aria-hidden="true" className={`font-mono text-[13px] leading-[21px] font-semibold ${t.glyphCls}`}>{t.glyph}</span>
      <div>
        <strong className="font-semibold">{title}</strong> {children}
      </div>
    </div>
  );
}

const pillTone = {
  ok: "bg-ok-soft text-ok border-transparent",
  accent: "bg-accent-soft text-accent border-transparent",
  neutral: "bg-sunken text-ink-2 border-line",
  warn: "bg-warn-soft text-warn border-transparent",
  danger: "bg-danger-soft text-danger border-transparent",
};

/** Status always pairs a glyph with a word, never color alone. */
export function Pill({ tone, glyph, children }: { tone: keyof typeof pillTone; glyph: string; children: React.ReactNode }) {
  return (
    <span className={`inline-flex h-[22px] items-center gap-1.5 rounded-full border px-2 text-xs font-medium whitespace-nowrap ${pillTone[tone]}`}>
      <span aria-hidden="true">{glyph}</span>
      {children}
    </span>
  );
}

export function TypeBadge({ type, compact = false }: { type: string; compact?: boolean }) {
  return (
    <span
      className={`flex-none rounded-sm border border-line bg-sunken text-center font-mono text-[10px] leading-3 font-medium tracking-[.06em] text-ink-2 uppercase ${compact ? "px-[5px] py-[3px] text-[9.5px]" : "mt-0.5 w-[72px] py-1"}`}
    >
      {type}
    </span>
  );
}

export function Avatar({ name, size = 40 }: { name: string; size?: number }) {
  return (
    <span
      aria-hidden="true"
      className="grid flex-none place-items-center rounded-lg border border-line-strong bg-sunken font-mono font-medium text-ink"
      style={{ width: size, height: size, fontSize: size * 0.35, borderRadius: size >= 28 ? 8 : 4 }}
    >
      {name[0]}
    </span>
  );
}
