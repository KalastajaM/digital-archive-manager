import { describe, expect, it } from "vitest";
import { isWordToken, withoutNoise } from "./text";

describe("OCR noise", () => {
  it("a word token has at least two letters or digits", () => {
    expect(isWordToken("Pohjola")).toBe(true);
    expect(isWordToken("1.11.2019")).toBe(true);
    expect(isWordToken("Oy")).toBe(true);
    expect(isWordToken("•ö")).toBe(false);
    expect(isWordToken("ö")).toBe(false);
    expect(isWordToken("|")).toBe(false);
  });

  it("drops the noise from a line and says nothing when only noise is left", () => {
    expect(withoutNoise("•ö Pohjola Vakuutus")).toBe("Pohjola Vakuutus");
    expect(withoutNoise("•ö |")).toBe("");
  });
});
