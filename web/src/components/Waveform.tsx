type Props = {
  levels: number[];
  active?: boolean;
  tone?: "idle" | "listen" | "speak" | "alert";
};

const TONE_CLASS = {
  idle: "bg-ink-200",
  listen: "bg-accent",
  speak: "bg-accent-deep",
  alert: "bg-coral",
};

export function Waveform({ levels, active, tone = "idle" }: Props) {
  const color = active ? TONE_CLASS[tone] : TONE_CLASS.idle;
  return (
    <div className="flex h-11 items-end gap-[3px]" aria-hidden>
      {levels.map((level, idx) => {
        const height = Math.max(5, Math.min(44, level * 44));
        return (
          <span
            key={idx}
            className={`w-[3px] rounded-full transition-[height,background-color] duration-75 ${color} ${
              active && tone === "listen" ? "opacity-90" : ""
            }`}
            style={{
              height: `${height}px`,
              animationDelay: active ? `${idx * 40}ms` : undefined,
            }}
          />
        );
      })}
    </div>
  );
}
