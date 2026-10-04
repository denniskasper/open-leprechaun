import { describe, expect, it } from "vitest";
import { groupSecret } from "./security-two-factor";

describe("groupSecret", () => {
  it("sets a base32 secret in groups of four", () => {
    expect(groupSecret("JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP")).toBe(
      "JBSW Y3DP EHPK 3PXP JBSW Y3DP EHPK 3PXP",
    );
  });

  it("leaves a short last group as it is", () => {
    expect(groupSecret("JBSWY3")).toBe("JBSW Y3");
  });
});
