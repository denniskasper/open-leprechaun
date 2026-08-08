import { useQuery } from "@tanstack/react-query";
import { fetchHealth, HEALTH_URL, type Health } from "../api/health";

type Tone = "signal" | "caution" | "alarm" | "idle";

const TONE: Record<Tone, { lamp: string; text: string }> = {
  signal: { lamp: "bg-signal", text: "text-signal" },
  caution: { lamp: "bg-caution", text: "text-caution" },
  alarm: { lamp: "bg-alarm", text: "text-alarm" },
  idle: { lamp: "bg-bone-faint", text: "text-bone-faint" },
};

interface Reading {
  tone: Tone;
  headline: string;
  detail: string;
}

function toReading(health: Health | undefined, error: Error | null): Reading {
  if (error) {
    return {
      tone: "alarm",
      headline: "Unreachable",
      detail: "The API did not answer. Is it running?",
    };
  }
  if (!health) {
    return {
      tone: "idle",
      headline: "Checking",
      detail: "Asking the API for its health report.",
    };
  }
  if (health.status === "ok") {
    return {
      tone: "signal",
      headline: "Operational",
      detail: "The API answered and its database is reachable.",
    };
  }
  return {
    tone: "caution",
    headline: "Degraded",
    detail: "The API answered, but it cannot reach its database.",
  };
}

export function HealthPanel() {
  // Fetched once. Keeping this panel current is the health panel's job, and that
  // is a later ticket; the skeleton only has to prove the path.
  const { data, error, dataUpdatedAt } = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
  });

  const reading = toReading(data, error);
  const rows: { label: string; value: string; tone?: Tone }[] = [
    { label: "Endpoint", value: HEALTH_URL },
    { label: "Service", value: data?.status ?? "—", tone: data ? reading.tone : undefined },
    { label: "Database", value: data?.database ?? "—", tone: data ? reading.tone : undefined },
    { label: "Checked", value: dataUpdatedAt ? formatTime(dataUpdatedAt) : "—" },
  ];

  return (
    <section aria-labelledby="health-headline" className="w-full">
      <div className="rise flex items-center gap-5">
        <Lamp tone={reading.tone} />
        <h1
          id="health-headline"
          className="text-[clamp(2.75rem,9vw,4.75rem)] leading-[0.9] tracking-[-0.03em] uppercase"
          style={{ fontVariationSettings: '"wdth" 112, "wght" 640' }}
        >
          {reading.headline}
        </h1>
      </div>

      <p
        className="rise mt-6 max-w-md text-pretty text-bone-dim"
        style={{ animationDelay: "80ms" }}
      >
        {reading.detail}
      </p>

      <dl className="mt-12 border-t border-hairline">
        {rows.map((row, index) => (
          <div
            key={row.label}
            className="rise grid grid-cols-[7.5rem_1fr] items-baseline gap-4 border-b border-hairline py-3.5"
            style={{ animationDelay: `${160 + index * 60}ms` }}
          >
            <dt className="font-mono text-[0.6rem] tracking-[0.18em] text-bone-faint uppercase">
              {row.label}
            </dt>
            <dd
              className={`font-mono text-sm tabular-nums ${row.tone ? TONE[row.tone].text : "text-bone"}`}
            >
              {row.value}
            </dd>
          </div>
        ))}
      </dl>

    </section>
  );
}

function Lamp({ tone }: { tone: Tone }) {
  return (
    <span className="relative flex size-3 shrink-0" aria-hidden="true">
      <span className={`lamp-halo absolute inset-0 rounded-full ${TONE[tone].lamp}`} />
      <span className={`relative size-3 rounded-full ${TONE[tone].lamp}`} />
    </span>
  );
}

function formatTime(timestamp: number): string {
  return new Date(timestamp).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}
