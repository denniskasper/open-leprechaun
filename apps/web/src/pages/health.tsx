import { useQuery } from "@tanstack/react-query";
import { ArrowRight, CalendarClock, KeyRound } from "lucide-react";
import { useId, type ReactNode } from "react";
import { Link } from "react-router";
import { fetchHealth, fetchHealthReport, type HealthReport } from "@/api/health";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { Lamp, TONE, type Tone } from "@/components/patterns/lamp";
import { Button } from "@/components/ui/button";
import { formatBytes, formatNumber, formatTimestamp } from "@/lib/format";
import { describeNextDue, describeStatus, taskTone } from "@/pages/scheduled-tasks";

type Provider = HealthReport["providers"][number];
type Connection = HealthReport["connections"][number];
type Kind = Connection["kinds"][number];
type Instrument = Provider["affected_instruments"][number];

/** How often the report is re-read while the page is open. */
const REFRESH_MS = 30_000;

const FEEDS: Record<Provider["feeds"], string> = {
  crypto_prices: "Crypto prices",
  security_prices: "Security prices",
  reference_rates: "Reference rates",
};

/**
 * One thing that is wrong, stated on its own: what it is, what it holds up,
 * and the screen where the Admin resolves it.
 */
export interface Problem {
  key: string;
  /** Alarm when a figure is stale or a run failed; caution when it only asks for patience. */
  tone: Tone;
  title: string;
  detail: string;
  instruments: Instrument[];
  to: string;
  action: string;
}

/** The word and colour each provider state wears — the one place they are paired. */
const PROVIDER_STATES: Record<Provider["state"], { tone: Tone; word: string }> = {
  ok: { tone: "signal", word: "Answering" },
  rate_limited: { tone: "caution", word: "Rate-limited" },
  outage: { tone: "alarm", word: "Not answering" },
  never_asked: { tone: "idle", word: "Not asked yet" },
};

export function providerTone(provider: Pick<Provider, "state">): Tone {
  return PROVIDER_STATES[provider.state].tone;
}

export function describeProvider(provider: Pick<Provider, "state">): string {
  return PROVIDER_STATES[provider.state].word;
}

function providerProblem(provider: Provider): Problem | null {
  if (provider.state !== "rate_limited" && provider.state !== "outage") {
    return null;
  }
  const limited = provider.state === "rate_limited";
  const affected = provider.affected_instruments;
  // What the failure holds up. The reference-rate source prices no
  // Instrument; what waits on it is every conversion not yet in the store.
  const consequence =
    provider.feeds === "reference_rates"
      ? "A foreign-currency amount whose date is not stored yet cannot be converted until it answers."
      : affected.length === 0
        ? "No Instrument is stale because of it — another provider answered, or nothing depends on it."
        : affected.length === 1
          ? "1 Instrument has no fresh price and shows its last known one, labelled stale:"
          : `${formatNumber(affected.length)} Instruments have no fresh price and show their last known one, labelled stale:`;
  const holdsSomethingUp = provider.feeds === "reference_rates" || affected.length > 0;
  return {
    key: `provider:${provider.name}`,
    tone: limited || !holdsSomethingUp ? "caution" : "alarm",
    title: limited ? `${provider.name} is rate-limiting` : `${provider.name} is not answering`,
    detail: [provider.last_error, consequence].filter(Boolean).join(" "),
    instruments: affected,
    to: "/settings/scheduled-tasks",
    action: limited ? "Run the update again later" : "Run the update again",
  };
}

/**
 * Everything the report says is wrong, each on its own — one provider
 * failing is that provider's problem and the staleness of the Instruments it
 * names, never an outage of everything. A provider nothing has asked yet and
 * a task that has never run are not problems; a task running again is given
 * the chance to succeed.
 */
export function problemsOf(report: HealthReport): Problem[] {
  const providers = report.providers.flatMap((provider) => providerProblem(provider) ?? []);
  const kinds = report.connections.flatMap((connection) =>
    connection.kinds
      .filter((kind) => !kind.ok)
      .map(
        (kind): Problem => ({
          key: `connection:${connection.id}:${kind.adapter_kind}`,
          tone: "alarm",
          title: `${connection.label}: ${kind.adapter_kind} failed`,
          detail: kind.last_error ?? "The venue did not say why.",
          instruments: [],
          to: "/settings/connections",
          action: "Open Connections",
        }),
      ),
  );
  const tasks = report.tasks
    .filter((task) => !task.running && task.outcome === "failed")
    .map(
      (task): Problem => ({
        key: `task:${task.key}`,
        tone: "alarm",
        title: `${task.name} failed on its last run`,
        detail: task.error ?? "The run did not say why.",
        instruments: [],
        to: "/settings/scheduled-tasks",
        action: "Open Scheduled tasks",
      }),
    );
  return [...providers, ...kinds, ...tasks];
}

interface Verdict {
  tone: Tone;
  headline: string;
  detail: string;
}

/** The page's one-line answer — `undefined` while no report has arrived. */
export function toVerdict(problems: Problem[] | undefined): Verdict {
  if (!problems) {
    return { tone: "idle", headline: "Checking", detail: "Asking the API for its health report." };
  }
  if (problems.length === 0) {
    return {
      tone: "signal",
      headline: "Operational",
      detail:
        "No data provider, Connection or scheduled task reports a failure. The figures are as fresh as their last update below.",
    };
  }
  return {
    tone: problems.some((problem) => problem.tone === "alarm") ? "alarm" : "caution",
    headline: problems.length === 1 ? "1 problem" : `${formatNumber(problems.length)} problems`,
    detail: "Everything not named below answered on its last attempt and is unaffected.",
  };
}

export function HealthPage() {
  const { data, error, refetch } = useQuery({
    queryKey: ["health", "report"],
    queryFn: fetchHealthReport,
    refetchInterval: REFRESH_MS,
  });

  return (
    <div className="space-y-10">
      <PageHeader
        eyebrow="System"
        title="Health"
        description="Whether the numbers on every other page are fresh — and when something is not, exactly what."
      />

      {error ? (
        <ReportUnavailable onRetry={() => void refetch()} />
      ) : (
        <Report report={data} />
      )}
    </div>
  );
}

/**
 * No report came back. The readiness probe needs no database and no login,
 * so it can still say which of the two it was.
 */
function ReportUnavailable({ onRetry }: { onRetry: () => void }) {
  const probe = useQuery({ queryKey: ["health"], queryFn: fetchHealth, retry: false });

  if (probe.data?.database === "down") {
    return (
      <ErrorState
        title="The database is unreachable"
        detail="The API answered, but it cannot reach its database — so it cannot say anything else about itself. Nothing on this page resolves that; check that Postgres is running."
        onRetry={onRetry}
      />
    );
  }
  if (probe.error) {
    return (
      <ErrorState
        title="The API is unreachable"
        detail="No health report came back. Is the API running?"
        onRetry={onRetry}
      />
    );
  }
  return (
    <ErrorState
      title="The health report could not be loaded"
      detail="The API is answering and reaches its database, but did not produce the report."
      onRetry={onRetry}
    />
  );
}

function Report({ report }: { report: HealthReport | undefined }) {
  const problems = report && problemsOf(report);
  const verdict = toVerdict(problems);

  return (
    <>
      <section aria-labelledby="health-headline">
        <div className="rise flex items-center gap-5" style={{ animationDelay: "60ms" }}>
          <Lamp tone={verdict.tone} />
          <h2 id="health-headline" className="text-display font-wide font-semibold uppercase">
            {verdict.headline}
          </h2>
        </div>
        <p
          className="rise mt-5 measure-prose text-pretty text-muted-foreground"
          style={{ animationDelay: "120ms" }}
        >
          {verdict.detail}
        </p>
        {report && (
          <p
            className="rise microlabel mt-4 text-muted-foreground"
            style={{ animationDelay: "160ms" }}
          >
            Checked {formatTimestamp(Date.parse(report.checked_at))}
          </p>
        )}

        {problems && problems.length > 0 && (
          <ul
            aria-label="Problems"
            className="rise mt-8 measure-list divide-y divide-border border-y border-border"
            style={{ animationDelay: "200ms" }}
          >
            {problems.map((problem) => (
              <ProblemRow key={problem.key} problem={problem} />
            ))}
          </ul>
        )}
      </section>

      {report && (
        <div className="divide-y divide-border border-y border-border">
          <Section
            index={0}
            title="Data providers"
            description="Where prices and reference rates come from. Each is asked on its own, so one failing says nothing about the others."
          >
            <Rows>
              {report.providers.map((provider) => (
                <ProviderRow key={`${provider.feeds}:${provider.name}`} provider={provider} />
              ))}
            </Rows>
          </Section>

          <Section
            index={1}
            title="Connections"
            description="Each venue account, and what every adapter kind of it last recorded — one kind failing never hides another succeeding."
          >
            {report.connections.length === 0 ? (
              <EmptyState
                icon={KeyRound}
                title="No Connections"
                description="No venue account is registered, so nothing syncs on its own. History arrives through imports until one is."
                action={
                  <Button asChild variant="outline" size="sm">
                    <Link to="/settings/connections">Add a Connection</Link>
                  </Button>
                }
              />
            ) : (
              <Rows>
                {report.connections.map((connection) => (
                  <ConnectionRow key={connection.id} connection={connection} />
                ))}
              </Rows>
            )}
          </Section>

          <Section
            index={2}
            title="Scheduled tasks"
            description="The work that keeps the figures current, when each last ran and when it is next due."
          >
            {!report.scheduler_enabled && (
              <Quiet>
                This instance does not answer schedules — a task runs only when started by hand
                under{" "}
                <Link to="/settings/scheduled-tasks" className="underline underline-offset-2">
                  Scheduled tasks
                </Link>
                , so a due time below is when a run is owed, not when one will happen.
              </Quiet>
            )}
            {report.tasks.length === 0 ? (
              <EmptyState
                icon={CalendarClock}
                title="No scheduled tasks"
                description="This version of the application declares no repeating work, so nothing keeps the figures current on its own."
              />
            ) : (
              <Rows>
                {report.tasks.map((task) => (
                  <TaskRow key={task.key} task={task} now={Date.parse(report.checked_at)} />
                ))}
              </Rows>
            )}
          </Section>

          <Section
            index={3}
            title="Storage"
            description="How large the database is, and how much price history it holds."
          >
            <dl className="grid grid-cols-2 gap-x-8 gap-y-6 sm:grid-cols-4">
              <Figure label="Database" value={formatBytes(report.storage.database_bytes)} />
              <Figure
                label="Crypto closes"
                value={formatNumber(report.storage.crypto_daily_closes)}
              />
              <Figure
                label="Security closes"
                value={formatNumber(report.storage.security_daily_closes)}
              />
              <Figure label="Reference rates" value={formatNumber(report.storage.reference_rates)} />
            </dl>
          </Section>
        </div>
      )}
    </>
  );
}

function ProblemRow({ problem }: { problem: Problem }) {
  return (
    <li className="grid gap-x-8 gap-y-3 py-5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start">
      <div className="min-w-0">
        <div className="flex items-center gap-3">
          <Lamp tone={problem.tone} size="sm" pulsing={false} />
          <h3 className={`font-medium ${TONE[problem.tone].text}`}>{problem.title}</h3>
        </div>
        <p className="mt-1.5 measure-prose pl-5.5 text-sm text-pretty text-muted-foreground">
          {problem.detail}
        </p>
        {problem.instruments.length > 0 && (
          <ul
            aria-label="Affected Instruments"
            className="mt-2 flex flex-wrap gap-x-4 gap-y-1 pl-5.5"
          >
            {problem.instruments.map((instrument) => (
              <li key={instrument.id} className="text-sm">
                <span className="font-mono tabular-nums">{instrument.symbol}</span>{" "}
                <span className="text-muted-foreground">{instrument.name}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <Button asChild variant="outline" size="sm" className="ml-5.5 justify-self-start sm:ml-0">
        <Link to={problem.to}>
          {problem.action}
          <ArrowRight aria-hidden />
        </Link>
      </Button>
    </li>
  );
}

function ProviderRow({ provider }: { provider: Provider }) {
  const tone = providerTone(provider);
  const failing = tone === "caution" || tone === "alarm";

  return (
    <Row
      tone={tone}
      name={<span className="font-mono">{provider.name}</span>}
      status={describeProvider(provider)}
      note={FEEDS[provider.feeds]}
    >
      <Readings>
        <Reading label="Last answer" value={at(provider.last_success_at, "Never")} />
        <Reading label="Last error" value={at(provider.last_error_at, "None")} />
      </Readings>
      {provider.last_error && (
        <Sentence tone={failing ? tone : "idle"}>{provider.last_error}</Sentence>
      )}
    </Row>
  );
}

function ConnectionRow({ connection }: { connection: Connection }) {
  const failing = connection.kinds.some((kind) => !kind.ok);
  const tone: Tone = connection.kinds.length === 0 ? "idle" : failing ? "alarm" : "signal";

  return (
    <Row
      tone={tone}
      name={connection.label}
      status={connection.kinds.length === 0 ? "Never synced" : failing ? "Failing" : "Synced"}
      note={connection.venue}
    >
      <Readings>
        <Reading label="Last sync" value={at(connection.last_sync_at, "Never")} />
      </Readings>
      {connection.kinds.length > 0 && (
        <ul className="mt-4 space-y-3">
          {connection.kinds.map((kind) => (
            <KindLine key={kind.adapter_kind} kind={kind} />
          ))}
        </ul>
      )}
    </Row>
  );
}

function KindLine({ kind }: { kind: Kind }) {
  const tone: Tone = kind.ok ? "signal" : "alarm";

  return (
    <li>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-sm">
        <span className="font-mono">{kind.adapter_kind}</span>
        <span className={`microlabel ${TONE[tone].text}`}>{kind.ok ? "OK" : "Failed"}</span>
        <span className="font-mono text-xs tabular-nums text-muted-foreground">
          {kind.ok
            ? at(kind.last_success_at, "")
            : `${at(kind.last_error_at, "")} · last good ${at(kind.last_success_at, "never")}`}
        </span>
      </div>
      {kind.last_error && <Sentence tone="alarm">{kind.last_error}</Sentence>}
    </li>
  );
}

function TaskRow({ task, now }: { task: HealthReport["tasks"][number]; now: number }) {
  const tone = taskTone(task);

  return (
    <Row
      tone={tone}
      pulsing={task.running}
      name={task.name}
      status={describeStatus(task)}
      note={task.enabled ? undefined : "Disabled"}
    >
      <Readings>
        <Reading label="Last run" value={at(task.last_started_at, "Never")} />
        <Reading label="Next due" value={describeNextDue(task, now)} />
      </Readings>
      {!task.running && task.error && <Sentence tone="alarm">{task.error}</Sentence>}
    </Row>
  );
}

/** A timestamp off the API, or the words for its absence. */
function at(instant: string | null, absent: string): string {
  return instant ? formatTimestamp(Date.parse(instant)) : absent;
}

function Section({
  index,
  title,
  description,
  children,
}: {
  index: number;
  title: string;
  description: string;
  children: ReactNode;
}) {
  const headingId = useId();

  return (
    <section
      aria-labelledby={headingId}
      className="rise grid measure-list gap-x-10 gap-y-5 py-8 md:grid-cols-[15rem_minmax(0,1fr)]"
      style={{ animationDelay: `${260 + index * 60}ms` }}
    >
      <div>
        <h2 id={headingId} className="text-base font-medium">
          {title}
        </h2>
        <p className="mt-1.5 text-sm text-pretty text-muted-foreground">{description}</p>
      </div>
      <div className="min-w-0 space-y-4">{children}</div>
    </section>
  );
}

function Rows({ children }: { children: ReactNode }) {
  return <ul className="divide-y divide-border">{children}</ul>;
}

function Row({
  tone,
  pulsing = false,
  name,
  status,
  note,
  children,
}: {
  tone: Tone;
  pulsing?: boolean;
  name: ReactNode;
  status: string;
  note?: string;
  children: ReactNode;
}) {
  return (
    <li className="py-4 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Lamp tone={tone} size="sm" pulsing={pulsing} />
        <h3 className="font-medium">{name}</h3>
        <span className={`microlabel ${TONE[tone].text}`}>{status}</span>
        {note && <span className="microlabel text-muted-foreground">· {note}</span>}
      </div>
      <div className="pl-5.5">{children}</div>
    </li>
  );
}

function Readings({ children }: { children: ReactNode }) {
  return <dl className="mt-3 flex flex-wrap gap-x-10 gap-y-3">{children}</dl>;
}

function Reading({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="microlabel text-muted-foreground">{label}</dt>
      <dd className="mt-1 font-mono text-sm tabular-nums">{value}</dd>
    </div>
  );
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="microlabel text-muted-foreground">{label}</dt>
      <dd className="mt-1.5 font-mono text-xl tabular-nums">{value}</dd>
    </div>
  );
}

/** What a provider, venue or run said went wrong, in its own words. */
function Sentence({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <p className={`mt-3 measure-prose text-sm text-pretty ${TONE[tone].text}`}>{children}</p>;
}

function Quiet({ children }: { children: ReactNode }) {
  return <p className="measure-prose text-sm text-pretty text-muted-foreground">{children}</p>;
}
