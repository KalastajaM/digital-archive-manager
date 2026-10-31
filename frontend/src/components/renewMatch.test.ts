import { describe, expect, it } from "vitest";
import type { RenewCandidate } from "../api/client";
import { renewMatches } from "./renewMatch";

const candidate = (item_id: number, folder: string | null, person: string | null): RenewCandidate => ({
  item_id,
  title: `item ${item_id}`,
  drive_id: `d${item_id}`,
  expires: "2027-06-30",
  kind: "Passport",
  folder,
  person,
  locked: false,
});

const ids = (list: RenewCandidate[]) => list.map((c) => c.item_id);

describe("renewMatches", () => {
  it("keeps a candidate in the same folder for the same person", () => {
    const list = [candidate(1, "40. Family/Tiina", "Tiina"), candidate(2, "40. Family/Tiina", "Mikko"), candidate(3, "40. Family/Mikko", "Tiina")];
    expect(ids(renewMatches(list, "40. Family/Tiina", "Tiina"))).toEqual([1]);
  });

  it("matches when neither has a person", () => {
    const list = [candidate(1, "10. Home", null), candidate(2, "10. Home", "Tiina")];
    expect(ids(renewMatches(list, "10. Home", null))).toEqual([1]);
  });

  it("one person set and the other not is no match", () => {
    expect(renewMatches([candidate(1, "10. Home", "Tiina")], "10. Home", null)).toEqual([]);
    expect(renewMatches([candidate(1, "10. Home", null)], "10. Home", "Tiina")).toEqual([]);
  });

  it("compares folders case folded and NFC normalised", () => {
    const list = [candidate(1, "20. Kela/Päätökset", null), candidate(2, null, null)];
    expect(ids(renewMatches(list, "20. kela/päätökset", null))).toEqual([1]);
  });

  it("no folder matches nothing", () => {
    expect(renewMatches([candidate(1, null, null)], "", null)).toEqual([]);
  });
});
