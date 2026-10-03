import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Play } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import {
  fetchScheduledTasks,
  runScheduledTask,
  setSchedule,
  type ScheduledTask,
} from "@/api/scheduled-tasks";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { Lamp, TONE, type Tone } from "@/components/patterns/lamp";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatNumber, formatTimestamp } from "@/lib/format";

/** How often the list is re-read: closely while a run is in flight. */
const WATCHING_MS = 3_000;
const RESTING_MS = 30_000;

/**
 * The colour a task wears: a run in flight first, then how the last one
 * ended. Disabling a task does not quiet a failure — it stays in alarm until
 * a run succeeds.
 */
export function taskTone(task: ScheduledTask): Tone {
  if (task.running) {
    return "caution";
  }
  if (task.outcome === "failed") {
    return "alarm";
  }
  return task.outcome === "ok" ? "signal" : "idle";
}

export function describeStatus(task: ScheduledTask): string {
  if (task.running) {
    return "Running";
  }
  if (task.outcome === "failed") {
    return "Failed";
  }
  return task.outcome === "ok" ? "Succeeded" : "Never run";
}

/** "0.04 s", "2 s", "1 min 1 s" — or a dash before any run has finished. */
export function describeDuration(seconds: number | null, locale?: string): string {
  if (seconds === null) {
    return "—";
  }
  if (seconds < 60) {
    const rounded = seconds < 10 ? Math.round(seconds * 100) / 100 : Math.round(seconds);
    return `${formatNumber(rounded, locale)} s`;
  }
  const whole = Math.round(seconds);
  return `${formatNumber(Math.floor(whole / 60), locale)} min ${whole % 60} s`;
}

/** When the schedule next fires, in words where an instant would mislead. */
export function describeNextDue(
  task: ScheduledTask,
  now: number,
  locale?: string,
  timeZone?: string,
): string {
  if (!task.enabled || task.next_due_at === null) {
    return "Not scheduled";
  }
  const due = Date.parse(task.next_due_at);
  return due <= now ? "Due now" : formatTimestamp(due, locale, timeZone);
}

/** The tasks whose last run failed — what the page says before anything else. */
export function failingTasks(tasks: ScheduledTask[]): ScheduledTask[] {
  return tasks.filter((task) => !task.running && task.outcome === "failed");
}

export function ScheduledTasksPage() {
  const { data, error, refetch, dataUpdatedAt } = useQuery({
    queryKey: ["scheduled-tasks"],
    queryFn: fetchScheduledTasks,
    refetchInterval: (query) =>
      query.state.data?.some((task) => task.running) ? WATCHING_MS : RESTING_MS,
  });
  const failing = data ? failingTasks(data) : [];

  return (
    <div className="space-y-10">
      <PageHeader
        eyebrow="Settings"
        title="Scheduled tasks"
        description="Work the application repeats on its own. Each task follows a cron expression read on the Europe/Berlin clock, never overlaps itself, and records how its last run ended."
      />

      {error ? (
        <ErrorState
          title="The scheduled tasks could not be loaded"
          detail="The API did not answer with the task list."
          onRetry={() => void refetch()}
        />
      ) : data && data.length === 0 ? (
        <EmptyState
          icon={CalendarClock}
          title="No scheduled tasks"
          description="This version of the application declares no repeating work, so there is nothing to schedule."
        />
      ) : (
        data && (
          <>
            {failing.length > 0 && (
              <ErrorState
                title={
                  failing.length === 1
                    ? "1 task failed on its last run"
                    : `${failing.length} tasks failed on their last run`
                }
                detail={`${failing.map((task) => task.name).join(", ")}. What failed is stated beside each task below; run it again once the cause is fixed.`}
              />
            )}
            <div className="divide-y divide-border border-y border-border">
              {data.map((task, index) => (
                <TaskRow key={task.key} task={task} now={dataUpdatedAt} index={index} />
              ))}
            </div>
          </>
        )
      )}
    </div>
  );
}

function TaskRow({ task, now, index }: { task: ScheduledTask; now: number; index: number }) {
  const queryClient = useQueryClient();

  function adopt(updated: ScheduledTask) {
    queryClient.setQueryData<ScheduledTask[]>(["scheduled-tasks"], (tasks) =>
      tasks?.map((entry) => (entry.key === updated.key ? updated : entry)),
    );
  }

  const run = useMutation({
    mutationFn: () => runScheduledTask(task.key),
    onSuccess: adopt,
    // A refusal — already running — means the list is behind; catch it up.
    onError: () => queryClient.invalidateQueries({ queryKey: ["scheduled-tasks"] }),
  });
  // A run this screen started is in flight before the list has heard of it.
  const inFlight = task.running || run.isPending;
  const shown = inFlight ? { ...task, running: true } : task;

  return (
    <article
      aria-label={task.name}
      className="rise grid gap-x-10 gap-y-5 py-6 lg:grid-cols-[minmax(0,1fr)_19rem]"
      style={{ animationDelay: `${60 + index * 60}ms` }}
    >
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <Lamp tone={taskTone(shown)} size="sm" pulsing={inFlight} />
          <h2 className="text-base font-medium">{task.name}</h2>
          <span className={`microlabel ${TONE[taskTone(shown)].text}`}>
            {describeStatus(shown)}
          </span>
          {!task.enabled && <span className="microlabel text-muted-foreground">· Disabled</span>}
        </div>
        <p className="mt-1.5 max-w-xl text-sm text-pretty text-muted-foreground">
          {task.description}
        </p>

        <dl className="mt-5 grid max-w-xl grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3">
          <Reading
            label="Last run"
            value={
              task.last_started_at ? formatTimestamp(Date.parse(task.last_started_at)) : "Never"
            }
          />
          <Reading label="Duration" value={describeDuration(task.duration_seconds)} />
          <Reading label="Next due" value={describeNextDue(task, now)} />
        </dl>

        {!inFlight && task.error && (
          <p
            role="alert"
            className="mt-4 max-w-xl rounded-md border border-alarm/40 bg-alarm/5 px-3 py-2 text-sm text-pretty text-alarm"
          >
            {task.error}
          </p>
        )}
        {!inFlight && !task.error && task.detail && (
          <p className="mt-4 max-w-xl font-mono text-xs tabular-nums text-muted-foreground">
            {task.detail}
          </p>
        )}
        {run.error && (
          <p role="alert" className="mt-3 text-sm text-alarm">
            {run.error.message}
          </p>
        )}
      </div>

      <div className="space-y-4">
        <ScheduleForm task={task} onSaved={adopt} />
        <Button
          variant="outline"
          size="sm"
          disabled={inFlight}
          title="Run this task once, now — whatever its schedule says, enabled or not."
          onClick={() => run.mutate()}
        >
          <Play aria-hidden />
          {inFlight ? "Running…" : "Run now"}
        </Button>
      </div>
    </article>
  );
}

function ScheduleForm({
  task,
  onSaved,
}: {
  task: ScheduledTask;
  onSaved: (task: ScheduledTask) => void;
}) {
  const cronId = useId();
  const hintId = useId();
  // The draft is only what the Admin has typed; where they have typed
  // nothing, the stored schedule shows through and follows a refetch.
  const [draft, setDraft] = useState<{ cron?: string; enabled?: boolean }>({});
  const cron = draft.cron ?? task.cron;
  const enabled = draft.enabled ?? task.enabled;
  const dirty = cron.trim() !== task.cron || enabled !== task.enabled;

  const save = useMutation({
    mutationFn: () => setSchedule(task.key, { cron: cron.trim(), enabled }),
    onSuccess: (saved) => {
      onSaved(saved);
      setDraft({});
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (dirty) {
      save.mutate();
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <div>
        <label htmlFor={cronId} className="microlabel mb-1.5 block text-muted-foreground">
          Schedule
        </label>
        <Input
          id={cronId}
          value={cron}
          spellCheck={false}
          autoComplete="off"
          aria-describedby={hintId}
          aria-invalid={save.isError || undefined}
          className="font-mono tabular-nums"
          onChange={(event) => {
            save.reset();
            setDraft((current) => ({ ...current, cron: event.target.value }));
          }}
        />
        <p id={hintId} className="mt-1.5 text-xs text-muted-foreground">
          minute · hour · day of month · month · day of week
        </p>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(event) => {
              save.reset();
              setDraft((current) => ({ ...current, enabled: event.target.checked }));
            }}
          />
          Run on this schedule
        </label>
        {dirty && (
          <span className="flex gap-2">
            <Button type="submit" size="sm" disabled={save.isPending || cron.trim() === ""}>
              {save.isPending ? "Saving…" : "Save"}
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                save.reset();
                setDraft({});
              }}
            >
              Discard
            </Button>
          </span>
        )}
      </div>
      {save.error && (
        <p role="alert" className="text-sm text-alarm">
          {save.error.message}
        </p>
      )}
    </form>
  );
}

function Reading({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="microlabel text-muted-foreground">{label}</dt>
      <dd className="mt-1 font-mono text-sm tabular-nums">{value}</dd>
    </div>
  );
}
