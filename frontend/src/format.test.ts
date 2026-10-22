import { describe, expect, it } from "vitest";
import { copyText, formatSize, plural } from "./format";

describe("formatSize", () => {
  it("uses bytes, then one decimal below 10, whole numbers above", () => {
    expect(formatSize(640)).toBe("640 bytes");
    expect(formatSize(1536)).toBe("1,5 KB");
    expect(formatSize(312 * 1024 * 1024)).toBe("312 MB");
  });

  it("never shows 1024 of a unit or 10,0", () => {
    expect(formatSize(1024 * 1024 - 1)).toBe("1,0 MB");
    expect(formatSize(1023.7 * 1024)).toBe("1,0 MB");
    expect(formatSize(1023.4 * 1024)).toBe("1023 KB");
    expect(formatSize(9.97 * 1024)).toBe("10 KB");
    expect(formatSize(1024 ** 3)).toBe("1,0 GB");
  });
});

describe("plural", () => {
  it("counts", () => {
    expect(plural(1, "file")).toBe("1 file");
    expect(plural(3, "open check")).toBe("3 open checks");
  });
});

describe("copyText", () => {
  it("copies a date in bank form (d.m.yyyy, as formatDate), IBANs compact, amounts with a comma", () => {
    expect(copyText("date", "2026-10-15")).toBe("15.10.2026");
    expect(copyText("date", "2026-01-05")).toBe("5.1.2026");
    expect(copyText("iban", "FI21 1234 5600 0007 85")).toBe("FI2112345600000785");
    expect(copyText("money", "1234.50")).toBe("1234,50");
  });
});
