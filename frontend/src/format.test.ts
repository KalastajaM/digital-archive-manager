import { describe, expect, it } from "vitest";
import { copyText, dayWord, euro, formatField, formatSize, longDate, plural, shortCalendarDate } from "./format";

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

describe("money and dates", () => {
  it("euro writes a decimal comma and keeps four decimals under a cent", () => {
    expect(euro(1.25)).toBe("1,25 €");
    expect(euro(0.0042)).toBe("0,0042 €");
    expect(euro(0.00001)).toBe("< 0,0001 €");
  });

  it("dayWord says today and yesterday, across a month end", () => {
    expect(dayWord("2026-11-01", "2026-11-01")).toBe("today");
    expect(dayWord("2026-10-31", "2026-11-01")).toBe("yesterday");
    expect(dayWord("2026-10-30", "2026-11-01")).toBeNull();
  });

  it("calendar dates read the same in every time zone", () => {
    expect(longDate("2026-10-20")).toBe("Tuesday 20 October");
    expect(shortCalendarDate("2026-11-12", "2026-10-23")).toBe("12 Nov");
    expect(shortCalendarDate("2027-01-05", "2026-10-23")).toBe("5 Jan 2027");
    expect(longDate("soon")).toBe("soon");
  });
});

describe("formatField", () => {
  it("shows a days field as a number of days and a choice as it is", () => {
    expect(formatField("days", 180)).toBe("180 days");
    expect(formatField("days", "1")).toBe("1 day");
    expect(formatField("choice", "Passport")).toBe("Passport");
  });
});
