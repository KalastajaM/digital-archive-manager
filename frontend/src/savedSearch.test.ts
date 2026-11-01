import { describe, expect, it } from "vitest";
import { queryToSave, sameSearch, savedSearchHref } from "./savedSearch";

describe("saved searches", () => {
  it("are the same search however they are spelled", () => {
    expect(sameSearch({ query: "tag:a  kela", tag_mode: "all" }, { query: "kela tag:a", tag_mode: "all" })).toBe(true);
    expect(sameSearch({ query: "-from:* id:*", tag_mode: "all" }, { query: "id:* -from:*", tag_mode: "all" })).toBe(true);
    expect(sameSearch({ query: "tag:a kela", tag_mode: "all" }, { query: "tag:b kela", tag_mode: "all" })).toBe(false);
  });

  it("count the tag mode only with two or more tags", () => {
    expect(sameSearch({ query: "tag:a", tag_mode: "any" }, { query: "tag:a", tag_mode: "all" })).toBe(true);
    expect(sameSearch({ query: "tag:a tag:b", tag_mode: "any" }, { query: "tag:a tag:b", tag_mode: "all" })).toBe(false);
  });

  it("open Browse with the query, and Any only where it counts", () => {
    expect(savedSearchHref({ query: 'in:"50. Medical" kela', tag_mode: "all" })).toBe("/browse?q=in%3A%2250.+Medical%22+kela");
    expect(savedSearchHref({ query: "tag:a", tag_mode: "any" })).toBe("/browse?q=tag%3Aa");
    expect(savedSearchHref({ query: "tag:a tag:b", tag_mode: "any" })).toBe("/browse?q=tag%3Aa+tag%3Ab&tag_mode=any");
  });

  it("write This folder as an in: filter", () => {
    const filters = [{ name: "tag" as const, value: "bills", negated: false }];
    expect(queryToSave("kela", filters, "")).toBe("kela tag:bills");
    expect(queryToSave("kela", filters, "50. Medical")).toBe('kela tag:bills in:"50. Medical"');
    expect(queryToSave("", [{ name: "in", value: "50. medical", negated: false }], "50. Medical")).toBe('in:"50. medical"');
  });
});
