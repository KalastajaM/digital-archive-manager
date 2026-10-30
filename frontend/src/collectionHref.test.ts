import { describe, expect, it } from "vitest";
import { collectionHref } from "./collectionHref";

const q = (href: string) => new URLSearchParams(href.split("?")[1]);

describe("collectionHref", () => {
  it("opens an ordinary collection in Browse, as a search of it with the Collections tree", () => {
    const href = collectionHref({ id: 3, name: "House sale" });
    expect(href.startsWith("/browse?")).toBe(true);
    expect(q(href).get("tree")).toBe("collections");
    expect(q(href).get("q")).toBe('collection:"House sale"');
    expect(q(collectionHref({ id: 4, name: "Car" })).get("q")).toBe("collection:Car");
  });
  it("drops the quote marks a filter value cannot carry", () => {
    expect(q(collectionHref({ id: 5, name: 'The "big" move' })).get("q")).toBe('collection:"The big move"');
  });
  it("Starred is its search; Important keeps its page", () => {
    expect(q(collectionHref({ id: 1, name: "★ Ongoing", kind: "starred" })).get("q")).toBe("is:starred");
    expect(collectionHref({ id: 2, name: "! Important", kind: "important" })).toBe("/important");
  });
});
