import { z } from "zod";
import { request } from "@/api/http";

/** Relative, because the dev server proxies /api to the API on the same origin. */
export const FIRST_RUN_CHECKLIST_URL = "/api/first-run-checklist";

/**
 * One step of the walk from an empty database to a first tax report
 * (ticket 58). `done` is derived by the API from what the database holds —
 * there is nothing to tick and nothing to dismiss. `optional` marks a step
 * the walk can finish without; `detail` says what the state was read from,
 * and `resolve_path` is the screen that completes the step.
 */
export const checklistItemSchema = z.object({
  key: z.enum([
    "password",
    "two_factor",
    "platforms_and_accounts",
    "connect_or_import",
    "reconcile",
    "blockers",
    "report",
  ]),
  done: z.boolean(),
  optional: z.boolean(),
  detail: z.string(),
  resolve_path: z.string(),
});

export const checklistSchema = z.object({
  complete: z.boolean(),
  items: z.array(checklistItemSchema),
});

export type ChecklistItem = z.infer<typeof checklistItemSchema>;
export type Checklist = z.infer<typeof checklistSchema>;

export async function fetchFirstRunChecklist(): Promise<Checklist> {
  const response = await request(FIRST_RUN_CHECKLIST_URL);
  if (!response.ok) {
    throw new Error(`The API answered ${response.status} instead of the first-run checklist.`);
  }
  return checklistSchema.parse(await response.json());
}
