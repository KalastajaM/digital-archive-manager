import { fireEvent } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { isShortcutIn, noKeysHeld } from "./keyboard";

describe("held keys", () => {
  it("are tracked by physical key, so a keyup with a different key value releases it", () => {
    // Shift pressed between keydown and keyup: the key value changes ("a" → "A").
    fireEvent.keyDown(window, { key: "a", code: "KeyA" });
    expect(noKeysHeld()).toBe(false);
    fireEvent.keyUp(window, { key: "A", code: "KeyA" });
    expect(noKeysHeld()).toBe(true);
  });

  it("are all released with Meta (macOS sends no keyups while Cmd is down)", () => {
    fireEvent.keyDown(window, { key: "Meta", code: "MetaLeft", metaKey: true });
    fireEvent.keyDown(window, { key: "Enter", code: "Enter", metaKey: true });
    fireEvent.keyUp(window, { key: "Meta", code: "MetaLeft" });
    expect(noKeysHeld()).toBe(true);
  });
});

describe("isShortcutIn", () => {
  const key = (target: Element) => {
    const e = new KeyboardEvent("keydown", { key: "+", bubbles: true });
    Object.defineProperty(e, "target", { value: target });
    return e;
  };

  it("takes a key with no dialog open, never behind one", () => {
    const page = document.createElement("div");
    document.body.append(page);
    expect(isShortcutIn(key(document.body), page)).toBe(true);
    const dialog = document.createElement("dialog");
    dialog.setAttribute("open", "");
    document.body.append(dialog);
    expect(isShortcutIn(key(dialog), page)).toBe(false);
    page.remove();
    dialog.remove();
  });

  it("takes a key only in the dialog it was pressed in (the topmost)", () => {
    const lower = document.createElement("dialog");
    const upper = document.createElement("dialog");
    for (const d of [lower, upper]) {
      d.setAttribute("open", "");
      document.body.append(d);
    }
    const inLower = lower.appendChild(document.createElement("figure"));
    const inUpper = upper.appendChild(document.createElement("button"));
    expect(isShortcutIn(key(inUpper), inLower)).toBe(false);
    expect(isShortcutIn(key(lower), inLower)).toBe(true);
    lower.remove();
    upper.remove();
  });
});
