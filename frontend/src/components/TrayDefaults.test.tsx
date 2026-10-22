import { describe, expect, it } from "vitest";
import { visibleText } from "../text";
import { lineDiff, settingList, settingName } from "./TrayDefaults";

describe("tray setting names", () => {
  it("reads key paths as words", () => {
    expect(settingName("fields.payee")).toBe("Payee field");
    expect(settingName("fields.amount.copy")).toBe("copy button on Amount");
    expect(settingName("fields.iban")).toBe("IBAN field");
    expect(settingName("fields.due_date.prefill")).toBe("prefill for Due date");
    expect(settingName("done.fields")).toBe("fields asked when done");
    expect(settingName("done.fields.paid_on")).toBe("Paid on field when done");
    expect(settingName("summary")).toBe("total on Today");
    expect(settingName("odd.key_x")).toBe("odd key x");
    expect(settingList(["fields.payee", "fields.amount.copy"])).toBe("Payee field, copy button on Amount");
    expect(settingList(["fields.amount.copy"])).toBe("Copy button on Amount");
  });
});

describe("lineDiff", () => {
  it("marks added and removed lines around the kept ones", () => {
    expect(lineDiff("a\nb\nc", "a\nx\nb\nd")).toEqual([
      { kind: "same", text: "a" },
      { kind: "add", text: "x" },
      { kind: "same", text: "b" },
      { kind: "add", text: "d" },
      { kind: "remove", text: "c" },
    ]);
  });
});

describe("visibleText", () => {
  it("keeps line breaks and tabs, marks other hidden characters", () => {
    expect(visibleText("a\tb\nc‮d\u0000")).toBe("a\tb\nc⟨U+202E⟩d⟨U+0000⟩");
  });
});
