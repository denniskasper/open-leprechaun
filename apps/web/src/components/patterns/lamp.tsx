export type Tone = "signal" | "caution" | "alarm" | "idle";

/** The text and lamp colour each tone wears — the one place they are paired. */
export const TONE: Record<Tone, { text: string; lamp: string }> = {
  signal: { text: "text-signal", lamp: "bg-signal" },
  caution: { text: "text-caution", lamp: "bg-caution" },
  alarm: { text: "text-alarm", lamp: "bg-alarm" },
  idle: { text: "text-muted-foreground", lamp: "bg-muted-foreground" },
};

const SIZE = { sm: "size-2.5", md: "size-3" };

/**
 * The status lamp: a dot in the tone's colour, with a breathing halo while
 * `pulsing` — motion that says something is live, so a settled state on a
 * list stays still.
 */
export function Lamp({
  tone,
  size = "md",
  pulsing = true,
}: {
  tone: Tone;
  size?: keyof typeof SIZE;
  pulsing?: boolean;
}) {
  return (
    <span className={`relative flex shrink-0 ${SIZE[size]}`} aria-hidden="true">
      {pulsing && <span className={`lamp-halo absolute inset-0 rounded-full ${TONE[tone].lamp}`} />}
      <span className={`relative rounded-full ${SIZE[size]} ${TONE[tone].lamp}`} />
    </span>
  );
}
