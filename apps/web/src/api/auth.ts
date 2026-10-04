import { z } from "zod";
import { ApiRefusal, postJson, refusal } from "@/api/http";

export const SETUP_URL = "/api/auth/setup";
export const LOGIN_URL = "/api/auth/login";
export const LOGOUT_URL = "/api/auth/logout";
export const SESSION_URL = "/api/auth/session";
export const SESSIONS_URL = "/api/auth/sessions";
export const PASSWORD_URL = "/api/auth/password";

/** The floor the API enforces wherever a password is set; forms state it up front. */
export const MINIMUM_PASSWORD_LENGTH = 12;

export const setupStatusSchema = z.object({ required: z.boolean() });
export type SetupStatus = z.infer<typeof setupStatusSchema>;

export const sessionSchema = z.object({ subject: z.string() });
export type Session = z.infer<typeof sessionSchema>;

const sessionCountSchema = z.object({ active: z.number().int().nonnegative() });

// Re-exported so the auth screens keep one import; it is defined in http.ts
// because every resource's client refuses the same way.
export { ApiRefusal };

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


/** Revoke the session this browser holds. The cookie is cleared by the response. */
export async function logOut(): Promise<void> {
  const response = await fetch(LOGOUT_URL, { method: "POST" });
  if (!response.ok) {
    throw await refusal(response, "Signing out failed.");
  }
}

/**
 * Revoke every session, this browser's included. A 401 means this browser's
 * session was already dead, so it is signed out all the same — but nothing
 * was revoked elsewhere, and logging in again is what it takes to do that.
 */
export async function logOutEverywhere(): Promise<void> {
  const response = await fetch(SESSIONS_URL, { method: "DELETE" });
  if (!response.ok && response.status !== 401) {
    throw await refusal(response, "Signing out everywhere failed.");
  }
}

/** Every other session is revoked by the API; this browser's stays alive. */
export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  const response = await postJson(PASSWORD_URL, {
    current_password: currentPassword,
    new_password: newPassword,
  });
  if (!response.ok) {
    throw await refusal(response, "Changing the password failed.");
  }
}

/** How many sessions are open right now, this one among them. */
export async function fetchSessionCount(): Promise<number> {
  const response = await fetch(SESSIONS_URL);
  if (!response.ok) {
    throw new Error(`The API answered ${response.status} instead of a session count.`);
  }
  return sessionCountSchema.parse(await response.json()).active;
}
