import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiRefusal } from "./http";
import { activateTwoFactor, beginEnrollment, disableTwoFactor, fetchTwoFactor } from "./two-factor";

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

describe("fetchTwoFactor", () => {
  it("reads whether two-factor is on", async () => {
    respondWith(200, { enabled: true });

    await expect(fetchTwoFactor()).resolves.toBe(true);
    expect(fetch).toHaveBeenCalledWith("/api/auth/two-factor");
  });

  it("rejects an error status rather than reading it as off", async () => {
    respondWith(503, { detail: "down" });

    await expect(fetchTwoFactor()).rejects.toThrow("503");
  });
});

describe("beginEnrollment", () => {
  it("asks for a secret and hands back what the authenticator needs", async () => {
    const enrollment = {
      secret: "JBSWY3DPEHPK3PXP",
      uri: "otpauth://totp/Open%20Leprechaun%3Aadmin?secret=JBSWY3DPEHPK3PXP&issuer=Open%20Leprechaun",
    };
    respondWith(201, enrollment);

    await expect(beginEnrollment()).resolves.toEqual(enrollment);
    expect(fetch).toHaveBeenCalledWith("/api/auth/two-factor/enrollment", { method: "POST" });
  });

  it("surfaces the API's own words when two-factor is already on", async () => {
    respondWith(409, {
      detail: "Two-factor is already on. Disable it before setting it up again.",
    });

    await expect(beginEnrollment()).rejects.toThrow(
      "Two-factor is already on. Disable it before setting it up again.",
    );
  });
});

describe("activateTwoFactor", () => {
  it("posts the verifying code", async () => {
    respondWithNothing();

    await activateTwoFactor("287082");

    expect(fetch).toHaveBeenCalledWith("/api/auth/two-factor/activation", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code: "287082" }),
    });
  });

  it("surfaces a code that does not verify as the API's refusal", async () => {
    respondWith(403, { detail: "Wrong code, or one already used." });

    const attempt = activateTwoFactor("000000");

    await expect(attempt).rejects.toThrow("Wrong code, or one already used.");
    await expect(attempt).rejects.toBeInstanceOf(ApiRefusal);
  });
});

describe("disableTwoFactor", () => {
  it("posts both factors under the API's field names", async () => {
    respondWithNothing();

    await disableTwoFactor("correct horse battery staple", "287082");

    expect(fetch).toHaveBeenCalledWith("/api/auth/two-factor/disable", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current_password: "correct horse battery staple", code: "287082" }),
    });
  });

  it("surfaces a wrong password as the API's refusal", async () => {
    respondWith(403, { detail: "Wrong current password." });

    await expect(disableTwoFactor("not the password", "287082")).rejects.toThrow(
      "Wrong current password.",
    );
  });
});
