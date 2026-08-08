import { useQuery } from "@tanstack/react-query";
import { fetchHealth, HEALTH_URL, type Health } from "@/api/health";
import { PageHeader } from "@/components/page-header";
import { ErrorState } from "@/components/patterns/error-state";
import { formatTimestamp } from "@/lib/format";

type Tone = "signal" | "caution" | "idle";

const TONE: Record<Tone, { text: string; lamp: string }> = {
  signal: { text: "text-signal", lamp: "bg-signal" },
  caution: { text: "text-caution", lamp: "bg-caution" },
  idle: { text: "text-muted-foreground", lamp: "bg-muted-foreground" },
};

interface Reading {
  tone: Tone;
  headline: string;
  detail: string;
}

function toReading(health: Health | undefined): Reading {
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

export function HealthPage() {
  // Fetched once. Keeping this panel current is the health panel's job, and
  // that is a later ticket; this page only has to prove the path.
  const { data, error, refetch, dataUpdatedAt } = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
  });

  return (
    <div className="space-y-10">
      <PageHeader
        eyebrow="System"
        title="Health"
        description="Whether the API answers and can reach its database."
      />

      {error ? (
        <ErrorState
          title="The API is unreachable"
          detail="No health report came back. Is the API running?"
          onRetry={() => void refetch()}
        />
      ) : (
        <Readout reading={toReading(data)} data={data} checkedAt={dataUpdatedAt} />
      )}
    </div>
  );
}

function Readout({
  reading,
  data,
  checkedAt,
}: {
  reading: Reading;
  data: Health | undefined;
  checkedAt: number;
}) {
  const rows: { label: string; value: string; tone?: Tone }[] = [
    { label: "Endpoint", value: HEALTH_URL },
    { label: "Service", value: data?.status ?? "—", tone: data && reading.tone },
    { label: "Database", value: data?.database ?? "—", tone: data && reading.tone },
    { label: "Checked", value: checkedAt ? formatTimestamp(checkedAt) : "—" },
  ];

  return (
    <section aria-labelledby="health-headline">
      <div className="rise flex items-center gap-5" style={{ animationDelay: "60ms" }}>
        <Lamp tone={reading.tone} />
        <h2 id="health-headline" className="text-display font-wide font-semibold uppercase">
          {reading.headline}
        </h2>
      </div>

      <p className="rise mt-5 max-w-md text-pretty text-muted-foreground" style={{ animationDelay: "120ms" }}>
        {reading.detail}
      </p>

      <dl className="mt-10 max-w-2xl border-t border-border">
        {rows.map((row, index) => (
          <div
            key={row.label}
            className="rise grid grid-cols-[7.5rem_1fr] items-baseline gap-4 border-b border-border py-3.5"
            style={{ animationDelay: `${180 + index * 60}ms` }}
          >
            <dt className="microlabel text-muted-foreground">{row.label}</dt>
            <dd className={`font-mono text-sm tabular-nums ${row.tone ? TONE[row.tone].text : ""}`}>
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
