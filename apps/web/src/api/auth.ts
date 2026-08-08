import { z } from "zod";

export const SETUP_URL = "/api/auth/setup";
export const LOGIN_URL = "/api/auth/login";
export const SESSION_URL = "/api/auth/session";

export const setupStatusSchema = z.object({ required: z.boolean() });
export type SetupStatus = z.infer<typeof setupStatusSchema>;

export const sessionSchema = z.object({ subject: z.string() });
export type Session = z.infer<typeof sessionSchema>;

/** An answer the API gave on purpose, carrying its own words for what went wrong. */
export class ApiRefusal extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiRefusal";
  }
}

export async function fetchSetupStatus(): Promise<SetupStatus> {
  const response = await fetch(SETUP_URL);
  if (!response.ok) {
    throw new Error(`The API answered ${response.status} instead of a setup status.`);
  }
  return setupStatusSchema.parse(await response.json());
}

export async function runSetup(password: string): Promise<void> {
  const response = await postJson(SETUP_URL, { password });
  if (!response.ok) {
    throw await refusal(response, "Setup failed.");
  }
}

/**
 * The browser's half of the session is the httpOnly cookie this response
 * sets; the bearer copy in the body is for non-browser clients, so it is
 * deliberately not read here — nothing token-shaped ever touches page state.
 */
export async function logIn(password: string): Promise<void> {
  const response = await postJson(LOGIN_URL, { password });
  if (!response.ok) {
    throw await refusal(response, "Login failed.");
  }
}

/** Who the cookie says we are; null means nobody, which is not an error. */
export async function fetchSession(): Promise<Session | null> {
  const response = await fetch(SESSION_URL);
  if (response.status === 401) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`The API answered ${response.status} instead of naming the session.`);
  }
  return sessionSchema.parse(await response.json());
}

function postJson(url: string, body: unknown): Promise<Response> {
  return fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function refusal(response: Response, fallback: string): Promise<ApiRefusal> {
  let message = fallback;
  try {
    const { detail } = (await response.json()) as { detail?: unknown };
    if (typeof detail === "string") {
      message = detail;
    }
  } catch {
    // The body was not JSON; the fallback already says what failed.
  }
  return new ApiRefusal(response.status, message);
}
