import { describe, expect, it } from "vitest";
import { describeOtherSessions, describeSessionCount } from "./security";

describe("describeSessionCount", () => {
  it("counts one in the singular and any other number in the plural", () => {
    expect(describeSessionCount(1)).toBe("session open");
    expect(describeSessionCount(0)).toBe("sessions open");
    expect(describeSessionCount(4)).toBe("sessions open");
  });
});

describe("describeOtherSessions", () => {
  it("says this browser is alone when it is", () => {
    expect(describeOtherSessions(1)).toBe("This browser holds the only one.");
  });

  it("names a single other session in the singular", () => {
    expect(describeOtherSessions(2)).toBe(
      "This browser holds one of them; 1 other is open elsewhere.",
    );
  });

  it("subtracts this browser from the count of the others", () => {
    expect(describeOtherSessions(5, "en-GB")).toBe(
      "This browser holds one of them; 4 others are open elsewhere.",
    );
  });
});
