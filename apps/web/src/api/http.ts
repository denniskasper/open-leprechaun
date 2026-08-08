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

export function postJson(url: string, body: unknown): Promise<Response> {
  return fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function putJson(url: string, body: unknown): Promise<Response> {
  return fetch(url, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function refusal(response: Response, fallback: string): Promise<ApiRefusal> {
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
