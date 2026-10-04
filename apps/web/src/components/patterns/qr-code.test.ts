import { describe, expect, it } from "vitest";
import { qrPath } from "./qr-code";

const URI =
  "otpauth://totp/Open%20Leprechaun%3Aadmin?secret=JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP&issuer=Open%20Leprechaun";

describe("qrPath", () => {
  it("leaves the four-module quiet zone a scanner needs around the symbol", () => {
    const { size, path } = qrPath(URI);
    const modules = [...path.matchAll(/M(\d+) (\d+)/g)].map(([, x, y]) => [Number(x), Number(y)]);

    const coordinates = modules.flat();
    expect(Math.min(...coordinates)).toBe(4);
    expect(Math.max(...coordinates)).toBe(size - 5);
  });

  it("opens with a finder pattern: seven dark modules along the top-left edge", () => {
    const { path } = qrPath(URI);

    for (let x = 4; x < 11; x += 1) {
      expect(path).toContain(`M${x} 4h`);
    }
    // The separator beside the finder is always light.
    expect(path).not.toContain("M11 4h");
  });

  it("draws a different symbol for a different secret", () => {
    expect(qrPath(URI).path).not.toBe(qrPath(URI.replace("JBSW", "KBSW")).path);
  });
});
