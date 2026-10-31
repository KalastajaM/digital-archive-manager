import { describe, expect, it, vi } from "vitest";
import { fileMenuEntries } from "./FileActionBar";
import type { MenuEntry } from "./ui/Menu";

const run = () => vi.fn();

describe("fileMenuEntries", () => {
  const label = (e: MenuEntry) => (e === "separator" ? "—" : e.label);
  it("lists the header's actions for a right-click menu, with the trays named and the off ones saying why", () => {
    const entries = fileMenuEntries(
      {
        tray: {
          label: "Put in tray",
          entries: [{ label: "To pay", checked: true, onSelect: run() }, { label: "To read", onSelect: run() }, "separator", { label: "Remove from To pay", onSelect: run() }],
        },
        backToInbox: { run: run(), reason: "Already in the inbox" },
        moveTo: { run: run() },
        sender: { run: run() },
        person: { run: run() },
        ask: { run: run(), disabled: true, reason: "Select one file to ask AI" },
        star: { on: true, run: run() },
        important: { on: false, run: run() },
        trash: { run: run(), count: 2 },
      },
      { addTag: run(), addTo: run(), reason: null },
    );
    expect(entries.map(label)).toEqual([
      "Put in To pay",
      "Put in To read",
      "Remove from To pay",
      "—",
      "Move to…",
      "Back to inbox",
      "—",
      "From…",
      "For…",
      "Ask AI",
      "—",
      "Add tag…",
      "Add to collection…",
      "—",
      "Remove the star",
      "Mark Important",
      "—",
      "Move 2 to To Delete",
    ]);
    const find = (name: string) => entries.find((e) => e !== "separator" && e.label === name) as Exclude<MenuEntry, "separator">;
    expect(find("Put in To pay").checked).toBe(true);
    expect(find("Back to inbox")).toMatchObject({ disabled: true, reason: "Already in the inbox" });
    expect(find("Ask AI")).toMatchObject({ disabled: true, reason: "Select one file to ask AI" });
  });

  it("an off tray pull-down is one entry with its reason; Restore comes before the bin", () => {
    const entries = fileMenuEntries(
      {
        tray: { label: "Put in tray", entries: [], disabled: true, reason: "Marked for deletion: restore it first" },
        restore: { entries: [{ label: "Restore to where it was", onSelect: run() }] },
        trash: { run: run(), reason: "Already in To Delete" },
      },
      { addTag: run(), addTo: run(), reason: "Marked for deletion: restore it first" },
    );
    expect(entries.map(label)).toEqual(["Put in tray", "—", "Add tag…", "Add to collection…", "—", "Restore to where it was", "Move to To Delete"]);
    expect(entries[0]).toMatchObject({ disabled: true, reason: "Marked for deletion: restore it first" });
    expect(entries.at(-1)).toMatchObject({ disabled: true, reason: "Already in To Delete" });
  });
});
