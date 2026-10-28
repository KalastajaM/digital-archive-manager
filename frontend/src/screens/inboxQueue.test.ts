import { describe, expect, it } from "vitest";
import type { InboxEntry } from "../api/client";
import { counts, isBill, isNewKind, matches, pillOf, ruleIdOf, suggestingRule, titleOf } from "./inboxQueue";

function entry(over: {
  name?: string;
  suggested?: string;
  ext?: string;
  prefill?: Record<string, string>;
  suggestion?: Partial<InboxEntry["suggestion"]>;
}): InboxEntry {
  const name = over.name ?? "scan.pdf";
  return {
    record: { drive_id: name, path: `##. Organize/${name}`, name, ext: over.ext ?? "pdf", marks: [] },
    suggestion: {
      name: over.suggested ?? name,
      folder: null,
      tags: [],
      sources: [],
      name_source: "scan",
      folder_source: null,
      tag_sources: {},
      tray_source: null,
      collection_sources: {},
      codes: [],
      waiting_for_page1: false,
      ...over.suggestion,
    },
    prefill: over.prefill ?? {},
  } as unknown as InboxEntry;
}

const TODAY = "2026-10-28";

describe("suggestingRule", () => {
  it("is the rule that gave the folder, else the name, a tag or the first one that matched", () => {
    expect(suggestingRule(entry({ suggestion: { folder_source: "rule:water", name_source: "rule:other" } }).suggestion)).toBe("water");
    expect(suggestingRule(entry({ suggestion: { name_source: "rule:other" } }).suggestion)).toBe("other");
    expect(suggestingRule(entry({ suggestion: { tag_sources: { home: "rule:tagger" } } }).suggestion)).toBe("tagger");
    expect(suggestingRule(entry({ suggestion: { sources: ["mtime", "rule:first (template error)"] } }).suggestion)).toBe("first");
  });

  it("is null when no rule suggests anything (a code, the scan or similar files do not count)", () => {
    expect(suggestingRule(entry({ suggestion: { sources: ["text-date", "similar files"], tray_source: "code:P" } }).suggestion)).toBeNull();
  });

  it("reads the id out of a source tag", () => {
    expect(ruleIdOf("rule:x")).toBe("x");
    expect(ruleIdOf("scan")).toBeNull();
    expect(ruleIdOf(null)).toBeNull();
  });
});

describe("the filter", () => {
  const water = entry({ name: "water.pdf", prefill: { due_date: "2026-11-05", total: "47.90" }, suggestion: { folder_source: "rule:water" } });
  const receipt = entry({ name: "receipt.pdf", prefill: { total: "23.40" } });
  const letter = entry({ name: "letter.pdf", suggestion: { name_source: "rule:tax" } });
  const all = [water, receipt, letter];

  it("calls a file a bill when the scan found a due date or an amount, and new when no rule suggests anything", () => {
    expect([water, receipt, letter].map(isBill)).toEqual([true, true, false]);
    expect([water, receipt, letter].map(isNewKind)).toEqual([false, true, false]);
  });

  it("counts and filters", () => {
    expect(counts(all)).toEqual({ all: 3, bills: 2, new: 1 });
    expect(all.filter((e) => matches(e, "bills"))).toEqual([water, receipt]);
    expect(all.filter((e) => matches(e, "new"))).toEqual([receipt]);
    expect(all.filter((e) => matches(e, "all"))).toHaveLength(3);
  });
});

describe("the status pill", () => {
  it("is orange for a due date to come, red once it is past, with the amount", () => {
    expect(pillOf(entry({ prefill: { due_date: "2026-11-05", total: "47.90" } }), TODAY)).toEqual({ text: "Due 5 Nov · 47,90 €", tone: "orange" });
    expect(pillOf(entry({ prefill: { due_date: "2026-10-18", total: "84.20" } }), TODAY)).toEqual({ text: "Overdue 10 days · 84,20 €", tone: "red" });
    expect(pillOf(entry({ prefill: { due_date: "2026-10-27" } }), TODAY)).toEqual({ text: "Overdue 1 day", tone: "red" });
  });

  it("is grey for an amount alone, the rule, reading, or a file nothing was found in", () => {
    expect(pillOf(entry({ prefill: { total: "23.40" } }), TODAY)).toEqual({ text: "23,40 €", tone: "grey" });
    expect(pillOf(entry({ suggestion: { folder_source: "rule:taxes" } }), TODAY)?.text).toBe("Rule: taxes");
    expect(pillOf(entry({ suggestion: { waiting_for_page1: true } }), TODAY)?.text).toBe("Reading page 1…");
    expect(pillOf(entry({ name: "photo.png", ext: "png" }), TODAY)).toEqual({ text: "Not recognised", tone: "grey" });
  });

  it("is none for a plain text file", () => {
    expect(pillOf(entry({ name: "notes.txt", ext: "txt" }), TODAY)).toBeNull();
  });
});

describe("the title", () => {
  it("is the suggested name without its date prefix and extension, else the file's name", () => {
    expect(titleOf(entry({ name: "scan.pdf", suggested: "20261105 Vesilaitos water bill.pdf" }))).toBe("Vesilaitos water bill");
    expect(titleOf(entry({ name: "scan.pdf", suggested: "scan.pdf" }))).toBe("scan.pdf");
  });
});
