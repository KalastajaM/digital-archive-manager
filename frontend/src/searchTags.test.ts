import { describe, expect, it } from "vitest";
import { splitTagQuery, tagToken } from "./searchTags";

describe("splitTagQuery", () => {
  it("leaves plain words alone", () => {
    expect(splitTagQuery("Kela decision")).toEqual({ rest: "Kela decision", kept: "Kela decision", tags: [], partial: null });
  });

  it("takes a complete tag out of the words", () => {
    expect(splitTagQuery("Kela tag:medical ")).toEqual({ rest: "Kela ", kept: "Kela ", tags: ["medical"], partial: null });
    expect(splitTagQuery("tag:medical Kela")).toEqual({ rest: "Kela", kept: "Kela", tags: ["medical"], partial: null });
  });

  it("keeps a tag being typed apart as partial", () => {
    expect(splitTagQuery("Kela tag:med")).toEqual({ rest: "Kela ", kept: "Kela tag:med", tags: [], partial: "med" });
    expect(splitTagQuery("tag:")).toEqual({ rest: "", kept: "tag:", tags: [], partial: "" });
  });

  it("reads quoted names with spaces", () => {
    expect(splitTagQuery('tag:"tax return" x')).toEqual({ rest: "x", kept: "x", tags: ["tax return"], partial: null });
    expect(splitTagQuery('tag:"tax re')).toEqual({ rest: "", kept: 'tag:"tax re', tags: [], partial: "tax re" });
    expect(splitTagQuery('tag:"tax return"')).toEqual({ rest: "", kept: "", tags: ["tax return"], partial: null });
  });

  it("takes several tags and ignores the prefix's case", () => {
    expect(splitTagQuery("TAG:a tag:b ")).toEqual({ rest: "", kept: "", tags: ["a", "b"], partial: null });
  });

  it("does not take tag: inside a word", () => {
    expect(splitTagQuery("sautag:x ")).toEqual({ rest: "sautag:x ", kept: "sautag:x ", tags: [], partial: null });
  });

  it("drops an empty token", () => {
    expect(splitTagQuery("tag: x")).toEqual({ rest: "x", kept: "x", tags: [], partial: null });
  });
});

describe("tagToken", () => {
  it("quotes names with spaces", () => {
    expect(tagToken("medical")).toBe("tag:medical");
    expect(tagToken("tax return")).toBe('tag:"tax return"');
  });
});
