import { describe, expect, it } from "vitest";
import type { FilingCode } from "../../api/client";
import { matchCodes } from "./CodePicker";

const code = (c: string, label: string): FilingCode => ({
  code: c,
  label,
  tray: null,
  folder: null,
  name: null,
  tags: [],
  collections: [],
  as_suggested: false,
  inbox_folder: null,
});

const CODES = [code("P", "To pay"), code("V3", "Car insurance"), code("A", "To action"), code("PA", "Payslips")];

describe("matchCodes", () => {
  it("lists every code for an empty query", () => {
    expect(matchCodes(CODES, " ").map((c) => c.code)).toEqual(["P", "V3", "A", "PA"]);
  });

  it("puts codes that start with the query first, then labels that hold it", () => {
    expect(matchCodes(CODES, "p").map((c) => c.code)).toEqual(["P", "PA"]);
    expect(matchCodes(CODES, "a").map((c) => c.code)).toEqual(["A", "P", "V3", "PA"]);
  });

  it("finds a code by its label", () => {
    expect(matchCodes(CODES, "insur").map((c) => c.code)).toEqual(["V3"]);
  });
});
