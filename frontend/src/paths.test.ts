import { describe, expect, it } from "vitest";
import { baseName, extOf, parentOf } from "./paths";

describe("baseName", () => {
  it("returns the last segment", () => {
    expect(baseName("a/b/c.pdf")).toBe("c.pdf");
  });
  it("returns a path without a slash unchanged", () => {
    expect(baseName("c.pdf")).toBe("c.pdf");
    expect(baseName("")).toBe("");
  });
  it("gives an empty string for a trailing slash", () => {
    expect(baseName("a/b/")).toBe("");
  });
});

describe("parentOf", () => {
  it("returns the folder part", () => {
    expect(parentOf("a/b/c.pdf")).toBe("a/b");
    expect(parentOf("a/c.pdf")).toBe("a");
  });
  it("gives an empty string at the top level", () => {
    expect(parentOf("c.pdf")).toBe("");
    expect(parentOf("")).toBe("");
    expect(parentOf("/a")).toBe("");
  });
  it("cuts at a trailing slash", () => {
    expect(parentOf("a/b/")).toBe("a/b");
  });
});

describe("extOf", () => {
  it("returns the lowercase extension", () => {
    expect(extOf("a/b/Scan.PDF")).toBe("pdf");
    expect(extOf("archive.tar.gz")).toBe("gz");
  });
  it("gives null without an extension", () => {
    expect(extOf("a/b/readme")).toBeNull();
    expect(extOf("")).toBeNull();
    expect(extOf("a/b/")).toBeNull();
  });
  it("ignores dots in folder names", () => {
    expect(extOf("v1.2/readme")).toBeNull();
  });
  it("treats a dotfile's name as its extension and a trailing dot as empty", () => {
    expect(extOf(".bashrc")).toBe("bashrc");
    expect(extOf("file.")).toBe("");
  });
});
