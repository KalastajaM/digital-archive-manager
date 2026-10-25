import { describe, expect, it } from "vitest";
import { type FilterName, filterToken, readQuery, sameFilter, serializeQuery, splitSearch, tagFilter, withFilter } from "./searchFilters";

const f = (name: FilterName, value: string, negated = false) => ({ name, value, negated });

describe("splitSearch", () => {
  it("leaves plain words alone", () => {
    expect(splitSearch("Kela decision")).toEqual({ rest: "Kela decision", kept: "Kela decision", filters: [], partial: null });
  });

  it("takes a complete filter out of the words, wherever it stands", () => {
    expect(splitSearch("Kela tag:medical ")).toMatchObject({ rest: "Kela ", kept: "Kela ", filters: [f("tag", "medical")] });
    expect(splitSearch("type:pdf Kela")).toMatchObject({ rest: "Kela", filters: [f("type", "pdf")] });
  });

  it("knows every filter name, in any case, and a leading dash", () => {
    const text = "name:*a* in:x tag:t collection:c from:f for:p type:y date:2026 before:2027 after:2025 tray:to-pay is:locked -tag:paid TAG:Up ";
    const names = splitSearch(text).filters.map((x) => `${x.negated ? "-" : ""}${x.name}`);
    expect(names).toEqual(["name", "in", "tag", "collection", "from", "for", "type", "date", "before", "after", "tray", "is", "-tag", "tag"]);
  });

  it("keeps a filter being typed apart as partial", () => {
    expect(splitSearch("Kela tag:med")).toMatchObject({ rest: "Kela ", kept: "Kela tag:med", filters: [], partial: { name: "tag", value: "med", negated: false } });
    expect(splitSearch("-in:")).toMatchObject({ rest: "", partial: { name: "in", value: "", negated: true } });
  });

  it("reads quoted values with spaces", () => {
    expect(splitSearch('in:"50. Medical" x')).toMatchObject({ rest: "x", filters: [f("in", "50. Medical")] });
    expect(splitSearch('tag:"tax re')).toMatchObject({ rest: "", kept: 'tag:"tax re', partial: { name: "tag", value: "tax re", quoted: true } });
    expect(splitSearch('collection:"House sale"')).toMatchObject({ filters: [f("collection", "House sale")], partial: null });
  });

  it("treats an unknown name and a name inside a word as plain words", () => {
    expect(splitSearch("http://x.org foo:bar ")).toMatchObject({ rest: "http://x.org foo:bar ", filters: [] });
    expect(splitSearch("sautag:x ")).toMatchObject({ rest: "sautag:x ", filters: [] });
    expect(splitSearch("-5 e-mail ")).toMatchObject({ rest: "-5 e-mail ", filters: [] });
  });
});

describe("tokens and queries", () => {
  it("writes a filter as it is typed, quoting a value with spaces", () => {
    expect(filterToken(f("tag", "kela"))).toBe("tag:kela");
    expect(filterToken(f("in", "50. Medical", true))).toBe('-in:"50. Medical"');
    expect(tagFilter("tax return")).toBe('tag:"tax return"');
  });

  it("serializes the words first, then the filters, and reads them back", () => {
    const filters = [f("tag", "a b"), f("is", "locked", true)];
    const text = serializeQuery("kela  letter", filters);
    expect(text).toBe('kela  letter tag:"a b" -is:locked');
    expect(readQuery(text)).toEqual({ words: "kela letter", filters });
    expect(serializeQuery("", [])).toBe("");
    expect(readQuery(null)).toEqual({ words: "", filters: [] });
  });

  it("does not add a filter twice, whatever the case of its value", () => {
    const base = [f("tag", "Kela")];
    expect(sameFilter(f("tag", "kela"), base[0])).toBe(true);
    expect(withFilter(base, f("tag", "kela"))).toBe(base);
    expect(withFilter(base, f("tag", "kela", true))).toHaveLength(2);
  });
});
