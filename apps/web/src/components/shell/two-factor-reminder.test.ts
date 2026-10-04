import { describe, expect, it } from "vitest";
import { remindsOfTwoFactor } from "./two-factor-reminder";

const production = { environment: "production", version: "1.2.3" } as const;
const development = { environment: "development", version: "abc1234" } as const;

describe("remindsOfTwoFactor", () => {
  it("reminds a production instance whose two-factor is off", () => {
    expect(remindsOfTwoFactor(production, false)).toBe(true);
  });

  it("goes once two-factor is on", () => {
    expect(remindsOfTwoFactor(production, true)).toBe(false);
  });

  it("stays quiet in development, which authenticates nobody", () => {
    expect(remindsOfTwoFactor(development, false)).toBe(false);
  });

  it("never warns on a state it does not know", () => {
    expect(remindsOfTwoFactor(production, undefined)).toBe(false);
    expect(remindsOfTwoFactor(undefined, false)).toBe(false);
  });
});
