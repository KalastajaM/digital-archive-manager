import { afterEach, describe, expect, it } from "vitest";
import { fileManagerName, inFileManager, showInLabel } from "./fileManager";

const agent = navigator.userAgent;
const set = (platform: string, userAgent = "") => {
  Object.defineProperty(navigator, "platform", { value: platform, configurable: true });
  Object.defineProperty(navigator, "userAgent", { value: userAgent, configurable: true });
};

afterEach(() => set("MacIntel", agent)); // test-setup's default

describe("fileManager", () => {
  it("names Finder on a Mac and Explorer on Windows", () => {
    set("MacIntel");
    expect(showInLabel()).toBe("Show in Finder");
    set("Win32");
    expect(fileManagerName()).toBe("Explorer");
    expect(inFileManager()).toBe("in Explorer");
  });

  it("uses plain words elsewhere", () => {
    set("Linux x86_64", "Mozilla/5.0 (X11; Linux x86_64)");
    expect(fileManagerName()).toBeNull();
    expect(showInLabel()).toBe("Show in file manager");
    expect(inFileManager()).toBe("in your file manager");
  });
});
