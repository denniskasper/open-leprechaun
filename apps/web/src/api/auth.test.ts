import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiRefusal,
  changePassword,
  fetchSession,
  fetchSessionCount,
  fetchSetupStatus,
  logIn,
  logOut,
  logOutEverywhere,
  runSetup,
} from "./auth";

function respondWith(status: number, body: unknown): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(body), { status })),
  );
}

/** A 204 carries no body, and Response refuses to be built with one. */
function respondWithNothing(): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(null, { status: 204 })),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchSetupStatus", () => {
  it("reports that a fresh instance still needs its admin", async () => {
    respondWith(200, { required: true });

    await expect(fetchSetupStatus()).resolves.toEqual({ required: true });
    // The literal, not the module's own constant: asserting against the value
    // under test would pass whatever path the module chose.
    expect(fetch).toHaveBeenCalledWith("/api/auth/setup");
  });

  it("rejects an error status", async () => {
    respondWith(500, { detail: "boom" });

    await expect(fetchSetupStatus()).rejects.toThrow("500");
  });
});

describe("runSetup", () => {
  it("posts the password as JSON to the setup endpoint", async () => {
    respondWith(201, null);

    await runSetup("correct horse battery staple");

    expect(fetch).toHaveBeenCalledWith("/api/auth/setup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: "correct horse battery staple" }),
    });
  });

  it("surfaces the API's own words when setup is refused", async () => {
    respondWith(409, { detail: "Setup has already run; this instance has its admin." });

    await expect(runSetup("correct horse battery staple")).rejects.toThrow(
      "Setup has already run; this instance has its admin.",
    );
  });
});

describe("logIn", () => {
  it("resolves without exposing the token to the caller", async () => {
    respondWith(200, { token: "should-never-surface", expires_at: "2026-09-07T00:00:00Z" });

    await expect(logIn("correct horse battery staple")).resolves.toBeUndefined();
  });

  it("surfaces a wrong password as the API's refusal", async () => {
    respondWith(401, { detail: "Wrong password." });

    const attempt = logIn("not the password");

    await expect(attempt).rejects.toThrow("Wrong password.");
    await expect(attempt).rejects.toBeInstanceOf(ApiRefusal);
  });
});

describe("fetchSession", () => {
  it("names the caller when a session is live", async () => {
    respondWith(200, { subject: "admin" });

    await expect(fetchSession()).resolves.toEqual({ subject: "admin" });
  });

  it("answers null, not an error, when nobody is logged in", async () => {
    respondWith(401, { detail: "Authentication required." });

    await expect(fetchSession()).resolves.toBeNull();
  });

  it("rejects an unexpected status", async () => {
    respondWith(503, { detail: "down" });

    await expect(fetchSession()).rejects.toThrow("503");
  });
});

describe("logOut", () => {
  it("asks the API to revoke the session the cookie names", async () => {
    respondWithNothing();

    await expect(logOut()).resolves.toBeUndefined();
    expect(fetch).toHaveBeenCalledWith("/api/auth/logout", { method: "POST" });
  });

  it("rejects when the API could not revoke it", async () => {
    respondWith(500, {});

    await expect(logOut()).rejects.toThrow(
      "Signing out failed. The API answered 500 without a reason — check that it is running, then try again.",
    );
  });
});

describe("logOutEverywhere", () => {
  it("deletes every session", async () => {
    respondWithNothing();

    await expect(logOutEverywhere()).resolves.toBeUndefined();
    expect(fetch).toHaveBeenCalledWith("/api/auth/sessions", { method: "DELETE" });
  });

  it("rejects when the API fails", async () => {
    respondWith(503, { detail: "The database is unreachable." });

    await expect(logOutEverywhere()).rejects.toThrow("The database is unreachable.");
  });

  it("counts an already-dead session as signed out, so the browser reaches login", async () => {
    respondWith(401, { detail: "Authentication required." });

    await expect(logOutEverywhere()).resolves.toBeUndefined();
  });
});

describe("changePassword", () => {
  it("posts the current and the new password under the API's field names", async () => {
    respondWithNothing();

    await changePassword("correct horse battery staple", "a rather different passphrase");

    expect(fetch).toHaveBeenCalledWith("/api/auth/password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        current_password: "correct horse battery staple",
        new_password: "a rather different passphrase",
      }),
    });
  });

  it("surfaces a wrong current password as the API's refusal", async () => {
    respondWith(403, { detail: "Wrong current password." });

    const attempt = changePassword("not the password", "a rather different passphrase");

    await expect(attempt).rejects.toThrow("Wrong current password.");
    await expect(attempt).rejects.toBeInstanceOf(ApiRefusal);
  });
});

describe("fetchSessionCount", () => {
  it("reads how many sessions are open", async () => {
    respondWith(200, { active: 3 });

    await expect(fetchSessionCount()).resolves.toBe(3);
    expect(fetch).toHaveBeenCalledWith("/api/auth/sessions");
  });

  it("rejects an error status", async () => {
    respondWith(503, { detail: "down" });

    await expect(fetchSessionCount()).rejects.toThrow("503");
  });
});
