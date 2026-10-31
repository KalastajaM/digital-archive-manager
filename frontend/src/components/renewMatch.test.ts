import { describe, expect, it } from "vitest";
import type { InboxEntry, RenewCandidate } from "../api/client";
import { filingPerson, renewMatches } from "./renewMatch";

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

type Who = { assigned?: { person: string | null; set_by: "owner" | "filing" }; person?: string | null; follows?: boolean };
/** Just what ``filingPerson`` reads of an inbox entry. */
const who = ({ assigned, person = null, follows = false }: Who) =>
  ({
    assignment: assigned ? { drive_id: "d1", sender: null, set_at: 0, ...assigned } : null,
    suggestion: { person, folder: "40. Family/Tiina" },
    person_follows_folder: follows,
  }) as unknown as InboxEntry;

describe("filingPerson (mirrors inbox.py _record_person)", () => {
  it("a {person} rule's person, when its folder is kept", () => {
    expect(filingPerson(who({ person: "Tiina", follows: true }), "40. Family/Tiina")).toBe("Tiina");
    expect(filingPerson(who({ person: "Tiina", follows: true }), "40. family/tiina")).toBeNull(); // same() is NFC only
    expect(filingPerson(who({ person: "Tiina", follows: true }), "10. Home")).toBeNull();
  });

  it("a person found without a {person} rule is not recorded", () => {
    expect(filingPerson(who({ person: "Tiina" }), "40. Family/Tiina")).toBeNull();
  });

  it("the owner's assignment wins, even when it sets no person", () => {
    expect(filingPerson(who({ assigned: { person: "Mikko", set_by: "owner" }, person: "Tiina", follows: true }), "40. Family/Tiina")).toBe("Mikko");
    expect(filingPerson(who({ assigned: { person: null, set_by: "owner" }, person: "Tiina", follows: true }), "40. Family/Tiina")).toBeNull();
  });

  it("a filing's assignment is replaced by the rule's person when the folder is kept, else stays", () => {
    const entry = who({ assigned: { person: "Mikko", set_by: "filing" }, person: "Tiina", follows: true });
    expect(filingPerson(entry, "40. Family/Tiina")).toBe("Tiina");
    expect(filingPerson(entry, "10. Home")).toBe("Mikko");
  });
});
