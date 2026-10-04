import { z } from "zod";
import { postJson, putJson, refusal, request } from "@/api/http";

/** Relative, because the dev server proxies /api to the API on the same origin. */
export const SCHEDULED_TASKS_URL = "/api/scheduled-tasks";

/**
 * One scheduled task: the schedule the Admin controls, and what its last run
 * did. A run the API did not survive arrives as `failed` with an error saying
 * so; `next_due_at` is null while the task is disabled, and in the past while
 * a fire is still waiting to be answered.
 */
export const scheduledTaskSchema = z.object({
  key: z.string(),
  name: z.string(),
  description: z.string(),
  cron: z.string(),
  enabled: z.boolean(),
  running: z.boolean(),
  last_started_at: z.string().nullable(),
  last_finished_at: z.string().nullable(),
  duration_seconds: z.number().nullable(),
  outcome: z.enum(["ok", "failed"]).nullable(),
  error: z.string().nullable(),
  detail: z.string().nullable(),
  next_due_at: z.string().nullable(),
});

export type ScheduledTask = z.infer<typeof scheduledTaskSchema>;

export interface Schedule {
  cron: string;
  enabled: boolean;
}

export async function fetchScheduledTasks(): Promise<ScheduledTask[]> {
  const response = await request(SCHEDULED_TASKS_URL);
  if (!response.ok) {
    throw new Error(`The API answered ${response.status} instead of listing scheduled tasks.`);
  }
  return z.array(scheduledTaskSchema).parse(await response.json());
}

export async function setSchedule(key: string, schedule: Schedule): Promise<ScheduledTask> {
  const response = await putJson(`${SCHEDULED_TASKS_URL}/${encodeURIComponent(key)}`, schedule);
  if (!response.ok) {
    throw await refusal(response, "The schedule could not be saved.");
  }
  return scheduledTaskSchema.parse(await response.json());
}

/** Runs the task and answers once the run has ended — however it ended. */
export async function runScheduledTask(key: string): Promise<ScheduledTask> {
  const response = await postJson(`${SCHEDULED_TASKS_URL}/${encodeURIComponent(key)}/run`, {});
  if (!response.ok) {
    throw await refusal(response, "The scheduled task could not be run.");
  }
  return scheduledTaskSchema.parse(await response.json());
}
