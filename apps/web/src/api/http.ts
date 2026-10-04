/**
 * The shape every API client shares: how a request body is posted, and how a
 * refusal the API meant is turned into an error carrying the API's own words.
 * Lives apart from any one resource so adding a screen does not edit auth.
 */

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

/**
 * What a request that never got an answer says: there is no status and no
 * body to quote, so it names what could not be reached and what to do.
 */
export const UNREACHABLE =
  "The API could not be reached, so the request went unanswered. Check that the API is running and this device is online, then try again.";

/**
 * `fetch`, except that a request the network dropped fails in words an Admin
 * can act on instead of the browser's own "Failed to fetch".
 */
export async function request(...args: Parameters<typeof fetch>): Promise<Response> {
  try {
    return await fetch(...args);
  } catch (cause) {
    throw new Error(UNREACHABLE, { cause });
  }
}

/**
 * What to do about a refusal that came without the API's own sentence. A
 * server-side failure is not the Admin's entry, a lapsed Session or a vanished
 * record is not either; anything else usually is.
 */
export function remedy(status: number): string {
  if (status >= 500) {
    return `The API answered ${status} without a reason — check that it is running, then try again.`;
  }
  if (status === 401) {
    return "The Session is no longer open — sign in again.";
  }
  if (status === 404) {
    return "It is no longer there — reload the page to see what is.";
  }
  return `The API answered ${status} without a reason — check what was entered, then try again.`;
}

export function postJson(url: string, body: unknown): Promise<Response> {
  return request(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function putJson(url: string, body: unknown): Promise<Response> {
  return request(url, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/**
 * `fallback` names what failed. It is shown only when the API sent no
 * sentence of its own, and then with what to do about it appended.
 */
export async function refusal(response: Response, fallback: string): Promise<ApiRefusal> {
  let message = `${fallback} ${remedy(response.status)}`;
  try {
    const { detail } = (await response.json()) as { detail?: unknown };
    if (typeof detail === "string") {
      message = detail;
    }
  } catch {
    // The body was not JSON; the fallback already says what failed and what to do.
  }
  return new ApiRefusal(response.status, message);
}
