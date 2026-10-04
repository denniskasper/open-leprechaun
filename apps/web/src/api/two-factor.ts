import { z } from "zod";
import { postJson, refusal, request } from "@/api/http";

export const TWO_FACTOR_URL = "/api/auth/two-factor";
export const ENROLLMENT_URL = "/api/auth/two-factor/enrollment";
export const ACTIVATION_URL = "/api/auth/two-factor/activation";
export const DISABLE_URL = "/api/auth/two-factor/disable";

const twoFactorSchema = z.object({ enabled: z.boolean() });

export const enrollmentSchema = z.object({ secret: z.string().min(1), uri: z.string().min(1) });
/** What goes into the authenticator. The API sends it once and never again. */
export type Enrollment = z.infer<typeof enrollmentSchema>;

/** Whether login asks for a code on top of the password. */
export async function fetchTwoFactor(): Promise<boolean> {
  const response = await request(TWO_FACTOR_URL);
  if (!response.ok) {
    throw new Error(`The API answered ${response.status} instead of the two-factor state.`);
  }
  return twoFactorSchema.parse(await response.json()).enabled;
}

/** The one query every reader of the two-factor state shares. */
export const TWO_FACTOR_QUERY = { queryKey: ["auth", "two-factor"], queryFn: fetchTwoFactor };

/**
 * Ask for a fresh secret. Nothing is enforced yet: the API holds it as
 * pending until `activateTwoFactor` proves an authenticator has it.
 */
export async function beginEnrollment(): Promise<Enrollment> {
  const response = await request(ENROLLMENT_URL, { method: "POST" });
  if (!response.ok) {
    throw await refusal(response, "Starting two-factor setup failed.");
  }
  return enrollmentSchema.parse(await response.json());
}

/** Turn two-factor on. Every other session is revoked by the API. */
export async function activateTwoFactor(code: string): Promise<void> {
  const response = await postJson(ACTIVATION_URL, { code });
  if (!response.ok) {
    throw await refusal(response, "Activating two-factor failed.");
  }
}

/** Turn two-factor off from inside the app, which takes both factors. */
export async function disableTwoFactor(currentPassword: string, code: string): Promise<void> {
  const response = await postJson(DISABLE_URL, { current_password: currentPassword, code });
  if (!response.ok) {
    throw await refusal(response, "Disabling two-factor failed.");
  }
}
