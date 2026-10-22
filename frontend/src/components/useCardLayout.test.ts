import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LAYOUT_KEY, useCardLayout } from "./useCardLayout";

const DEFAULTS = [
  ["tray:to-pay", "tray:to-action"],
  ["inbox", "tray:to-read", "collections", "reminders"],
];

const stored = () => JSON.parse(localStorage.getItem(LAYOUT_KEY) ?? "null");
const save = (value: unknown) => localStorage.setItem(LAYOUT_KEY, JSON.stringify(value));

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("useCardLayout", () => {
  it("starts from the default columns, nothing collapsed unless the defaults say so", () => {
    const { result } = renderHook(() => useCardLayout(DEFAULTS, { inbox: true }));
    expect(result.current.columns).toEqual(DEFAULTS);
    expect(result.current.collapsed("inbox")).toBe(true);
    expect(result.current.collapsed("tray:to-pay")).toBe(false);
    expect(localStorage.getItem(LAYOUT_KEY)).toBeNull();
  });

  it("stores the order and the folded cards under dam.today.layout.v1, and reads them back", () => {
    expect(LAYOUT_KEY).toBe("dam.today.layout.v1");
    const first = renderHook(() => useCardLayout(DEFAULTS, { inbox: true }));
    act(() => first.result.current.toggle("tray:to-pay"));
    act(() => first.result.current.toggle("inbox"));
    act(() => first.result.current.move("tray:to-action", -1));
    expect(stored()).toEqual({
      order: ["tray:to-action", "tray:to-pay", "|", "inbox", "tray:to-read", "collections", "reminders"],
      collapsed: { "tray:to-pay": true, inbox: false },
    });
    first.unmount();
    const again = renderHook(() => useCardLayout(DEFAULTS, { inbox: true }));
    expect(again.result.current.columns[0]).toEqual(["tray:to-action", "tray:to-pay"]);
    expect(again.result.current.collapsed("tray:to-pay")).toBe(true);
    expect(again.result.current.collapsed("inbox")).toBe(false);
  });

  it("folding a card does not freeze the default order: a new card still lands in its default place", () => {
    const first = renderHook(() => useCardLayout(DEFAULTS));
    act(() => first.result.current.toggle("inbox"));
    expect(stored()).toEqual({ order: null, collapsed: { inbox: true } });
    first.unmount();
    const withNew = [["tray:to-pay", "tray:new", "tray:to-action"], DEFAULTS[1]];
    const again = renderHook(() => useCardLayout(withNew));
    expect(again.result.current.columns).toEqual(withNew);
    expect(again.result.current.collapsed("inbox")).toBe(true);
  });

  it("folding keeps a saved order as it is", () => {
    save({ order: ["tray:to-action", "tray:to-pay"], collapsed: {} });
    const { result } = renderHook(() => useCardLayout(DEFAULTS));
    act(() => result.current.toggle("tray:to-pay"));
    expect(stored().order).toEqual(["tray:to-action", "tray:to-pay"]);
  });

  it("forgets the folds of cards that no longer exist when it saves", () => {
    save({ order: null, collapsed: { "tray:gone": true, inbox: true } });
    const { result } = renderHook(() => useCardLayout(DEFAULTS));
    act(() => result.current.toggle("reminders"));
    expect(stored().collapsed).toEqual({ inbox: true, reminders: true });
    act(() => result.current.move("reminders", -1));
    expect(Object.keys(stored().collapsed).sort()).toEqual(["inbox", "reminders"]);
  });

  it("ignores a saved card that no longer exists (a removed tray)", () => {
    save({ order: ["tray:gone", "tray:to-action", "tray:to-pay", "|", "reminders", "inbox"], collapsed: { "tray:gone": true } });
    const { result } = renderHook(() => useCardLayout(DEFAULTS));
    expect(result.current.columns).toEqual([
      ["tray:to-action", "tray:to-pay"],
      ["reminders", "inbox", "tray:to-read", "collections"],
    ]);
    expect(result.current.columns.flat()).not.toContain("tray:gone");
  });

  it("appends a new card at the end of its default column", () => {
    save({ order: ["tray:to-pay", "|", "reminders", "inbox", "tray:to-read", "collections"], collapsed: {} });
    const { result } = renderHook(() => useCardLayout(DEFAULTS));
    expect(result.current.columns).toEqual([
      ["tray:to-pay", "tray:to-action"],
      ["reminders", "inbox", "tray:to-read", "collections"],
    ]);
  });

  it("Move up and down go through both columns, top to bottom; the ends cannot move further", () => {
    const { result } = renderHook(() => useCardLayout(DEFAULTS));
    expect(result.current.canMove("tray:to-pay", -1)).toBe(false);
    expect(result.current.canMove("reminders", 1)).toBe(false);
    act(() => result.current.move("tray:to-action", 1)); // past the column break
    expect(result.current.columns).toEqual([["tray:to-pay"], ["tray:to-action", "inbox", "tray:to-read", "collections", "reminders"]]);
    act(() => result.current.move("inbox", -1));
    expect(result.current.columns[1].slice(0, 2)).toEqual(["inbox", "tray:to-action"]);
  });

  it("places a dragged card before or after another, or at the end of a column", () => {
    const { result } = renderHook(() => useCardLayout(DEFAULTS));
    act(() => result.current.place("reminders", { before: "tray:to-pay" }));
    expect(result.current.columns[0]).toEqual(["reminders", "tray:to-pay", "tray:to-action"]);
    act(() => result.current.place("tray:to-pay", { after: "collections" }));
    expect(result.current.columns[1]).toEqual(["inbox", "tray:to-read", "collections", "tray:to-pay"]);
    act(() => result.current.place("inbox", { column: 0 }));
    expect(result.current.columns[0]).toEqual(["reminders", "tray:to-action", "inbox"]);
    act(() => result.current.place("nobody", { column: 0 }));
    act(() => result.current.place("inbox", { before: "nobody" }));
    expect(result.current.columns[0]).toEqual(["reminders", "tray:to-action", "inbox"]);
  });

  it("Reset layout goes back to the defaults and forgets the saved layout", () => {
    const { result } = renderHook(() => useCardLayout(DEFAULTS));
    act(() => result.current.move("tray:to-action", -1));
    act(() => result.current.toggle("collections"));
    act(() => result.current.reset());
    expect(result.current.columns).toEqual(DEFAULTS);
    expect(result.current.collapsed("collections")).toBe(false);
    expect(localStorage.getItem(LAYOUT_KEY)).toBeNull();
  });

  it("a broken or foreign saved value is ignored", () => {
    localStorage.setItem(LAYOUT_KEY, "{not json");
    expect(renderHook(() => useCardLayout(DEFAULTS)).result.current.columns).toEqual(DEFAULTS);
    save({ order: "inbox", collapsed: [] });
    expect(renderHook(() => useCardLayout(DEFAULTS)).result.current.columns).toEqual(DEFAULTS);
    save({ order: ["inbox", 3, "inbox"], collapsed: { inbox: "yes" } });
    const { result } = renderHook(() => useCardLayout(DEFAULTS, { inbox: true }));
    expect(result.current.columns.flat().filter((id) => id === "inbox")).toHaveLength(1);
    expect(result.current.collapsed("inbox")).toBe(true);
  });

  it("still works when the storage throws (private mode, blocked site data)", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
      throw new Error("denied");
    });
    const { result } = renderHook(() => useCardLayout(DEFAULTS));
    act(() => result.current.toggle("inbox"));
    act(() => result.current.move("tray:to-action", -1));
    expect(result.current.collapsed("inbox")).toBe(true);
    expect(result.current.columns[0]).toEqual(["tray:to-action", "tray:to-pay"]);
    act(() => result.current.reset());
    expect(result.current.columns).toEqual(DEFAULTS);
  });

  it("Move up and down step over hidden cards, which keep their place among the others", () => {
    const up = renderHook(() => useCardLayout(DEFAULTS, {}, ["collections"]));
    expect(up.result.current.canMove("reminders", -1)).toBe(true);
    act(() => up.result.current.move("reminders", -1)); // past the hidden Collections, before To read
    expect(up.result.current.columns[1]).toEqual(["inbox", "reminders", "tray:to-read", "collections"]);
    up.unmount();
    localStorage.clear();
    const down = renderHook(() => useCardLayout(DEFAULTS, {}, ["collections"]));
    act(() => down.result.current.move("tray:to-read", 1)); // past the hidden Collections, after Reminders
    expect(down.result.current.columns[1]).toEqual(["inbox", "collections", "reminders", "tray:to-read"]);
  });

  it("a card with only hidden cards beyond it cannot move that way", () => {
    const { result } = renderHook(() => useCardLayout(DEFAULTS, {}, ["collections", "reminders"]));
    expect(result.current.canMove("tray:to-read", 1)).toBe(false);
    act(() => result.current.move("tray:to-read", 1));
    expect(result.current.columns).toEqual(DEFAULTS);
  });
});

