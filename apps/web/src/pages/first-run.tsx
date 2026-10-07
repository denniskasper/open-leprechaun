import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { Link } from "react-router";
import { fetchFirstRunChecklist, type ChecklistItem } from "@/api/first-run";
import { PageHeader } from "@/components/page-header";
import { ErrorState } from "@/components/patterns/error-state";
import { Lamp } from "@/components/patterns/lamp";
import { Button } from "@/components/ui/button";
import { formatNumber } from "@/lib/format";

interface StepCopy {
  title: string;
  /** What the link to the completing screen says. */
  action: string;
  /** A second screen that completes the step as well, where there is one. */
  alternative?: { to: string; label: string };
}

/**
 * The words for each step. The API decides whether a step is done and says
 * why; this only names the step and the way to the screen that completes it.
 */
export const STEPS: Record<ChecklistItem["key"], StepCopy> = {
  password: { title: "Set a password", action: "Set the password" },
  two_factor: { title: "Enable two-factor", action: "Open Security" },
  platforms_and_accounts: { title: "Add Platforms and Accounts", action: "Open Platforms" },
  connect_or_import: {
    title: "Connect or import",
    action: "Go to Imports",
    alternative: { to: "/settings/connections", label: "or add a Connection" },
  },
  reconcile: { title: "Reconcile", action: "Open Connections" },
  blockers: { title: "Resolve blockers", action: "See what blocks each year" },
  report: { title: "Generate a report", action: "Generate a report" },
};

/** How far the walk is: the steps it cannot finish without, and how many hold. */
export function progress(items: Pick<ChecklistItem, "done" | "optional">[]): {
  done: number;
  required: number;
} {
  const required = items.filter((item) => !item.optional);
  return { done: required.filter((item) => item.done).length, required: required.length };
}

/**
 * The step to take now: the first the walk cannot finish without that is
 * still open — null once none is.
 */
export function nextStep(items: ChecklistItem[]): ChecklistItem["key"] | null {
  return items.find((item) => !item.done && !item.optional)?.key ?? null;
}

export function FirstRunPage() {
  const { data, error, isPending, refetch } = useQuery({
    queryKey: ["first-run-checklist"],
    queryFn: fetchFirstRunChecklist,
  });

  return (
    <div className="space-y-10">
      <PageHeader
        eyebrow="System"
        title="First run"
        description="The walk from an empty database to a first tax report. Nothing here is ticked off by hand: each step reads done because what it asks for exists, and reads open again if that goes."
      />

      {error ? (
        <ErrorState
          title="The first-run checklist could not be loaded"
          detail="The API did not answer with the steps. Check that it is running, then try again."
          onRetry={() => void refetch()}
        />
      ) : isPending ? (
        <p role="status" className="microlabel text-muted-foreground">
          reading each step from the database
        </p>
      ) : (
        <>
          <Readout items={data.items} complete={data.complete} />
          <ol aria-label="Steps" className="measure-list divide-y divide-border border-y border-border">
            {data.items.map((item, index) => (
              <Step
                key={item.key}
                item={item}
                position={index + 1}
                next={item.key === nextStep(data.items)}
              />
            ))}
          </ol>
        </>
      )}
    </div>
  );
}

/** How far the walk is, as a figure and a bar — or that it is finished. */
function Readout({ items, complete }: { items: ChecklistItem[]; complete: boolean }) {
  const { done, required } = progress(items);
  return (
    <section aria-label="Progress" className="rise measure-list space-y-3" style={{ animationDelay: "80ms" }}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
        <p role="status" className="flex items-baseline gap-2.5">
          <span className="font-mono text-2xl tabular-nums">
            {formatNumber(done)}
            <span className="text-muted-foreground"> / {formatNumber(required)}</span>
          </span>
          <span className="microlabel text-muted-foreground">steps done</span>
        </p>
        {complete && (
          <p className="microlabel flex items-center gap-2 text-signal">
            <Lamp tone="signal" size="sm" pulsing={false} />
            the walk is complete
          </p>
        )}
      </div>
      <div aria-hidden className="flex gap-1">
        {items
          .filter((item) => !item.optional)
          .map((item) => (
            <span
              key={item.key}
              className={`h-1 flex-1 rounded-full ${item.done ? "bg-foreground" : "bg-muted"}`}
            />
          ))}
      </div>
    </section>
  );
}

function Step({ item, position, next }: { item: ChecklistItem; position: number; next: boolean }) {
  const copy = STEPS[item.key];
  return (
    <li
      className="rise grid grid-cols-[2.25rem_1fr] gap-x-3 gap-y-3 py-5 sm:grid-cols-[2.25rem_1fr_auto] sm:items-center"
      style={{ animationDelay: `${140 + position * 50}ms` }}
    >
      <span
        aria-hidden
        className={`pt-0.5 font-mono text-sm tabular-nums sm:self-start ${
          item.done ? "text-muted-foreground" : "text-foreground"
        }`}
      >
        {String(position).padStart(2, "0")}
      </span>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <h2 className={`text-base font-medium ${item.done ? "text-muted-foreground" : ""}`}>
            {copy.title}
          </h2>
          <p
            className={`microlabel flex items-center gap-1.5 ${
              item.done ? "text-signal" : "text-muted-foreground"
            }`}
          >
            <Lamp tone={item.done ? "signal" : "idle"} size="sm" pulsing={false} />
            {item.done ? "done" : next ? "next" : "open"}
            {item.optional && !item.done && <span>· optional</span>}
          </p>
        </div>
        <p className="mt-1 measure-prose text-sm text-pretty text-muted-foreground">{item.detail}</p>
      </div>
      {!item.done && (
        <div className="col-start-2 flex flex-wrap items-center gap-x-4 gap-y-2 sm:col-start-3 sm:justify-end">
          <Button asChild size="sm" variant={next ? "default" : "outline"}>
            <Link to={item.resolve_path}>
              {copy.action}
              <ArrowRight aria-hidden />
            </Link>
          </Button>
          {copy.alternative && (
            <Link
              to={copy.alternative.to}
              className="text-sm text-muted-foreground underline underline-offset-2"
            >
              {copy.alternative.label}
            </Link>
          )}
        </div>
      )}
    </li>
  );
}
