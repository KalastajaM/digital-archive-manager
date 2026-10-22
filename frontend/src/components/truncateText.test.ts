import { describe, expect, it } from "vitest";
import { truncateName, truncatePath } from "./truncateText";

/** One character is one unit wide. */
const within = (max: number) => (t: string) => t.length <= max;

describe("truncatePath", () => {
  it("leaves a path that fits", () => {
    expect(truncatePath("70. Work/Brightwave", within(30))).toBe("70. Work/Brightwave");
  });

  it("drops the middle folders and keeps the first and the last", () => {
    const path = "70. Work/Charlie/Projects/2019/Brightwave";
    expect(truncatePath(path, within(24))).toBe("70. Work/…/Brightwave");
  });

  it("keeps as many of the last folders as fit", () => {
    const path = "70. Work/Charlie/Projects/2019/Brightwave";
    expect(truncatePath(path, within(33))).toBe("70. Work/…/2019/Brightwave");
    expect(truncatePath(path, within(40))).toBe("70. Work/…/Projects/2019/Brightwave");
  });

  it("keeps the last folder whole behind the start of the rest when the first does not fit", () => {
    expect(truncatePath("70. Work/Charlie/Brightwave", within(18))).toBe("70. Wo…/Brightwave");
    expect(truncatePath("30. Home/Electricity", within(19))).toBe("30. Ho…/Electricity");
  });

  it("falls back to the last folder behind an ellipsis when little of the start would show", () => {
    expect(truncatePath("70. Work/Charlie/Brightwave", within(14))).toBe("…/Brightwave");
    expect(truncatePath("70. Work/Charlie/Brightwave", within(3))).toBe("…/Brightwave");
  });

  it("does not touch a single folder", () => {
    expect(truncatePath("Brightwave", within(3))).toBe("Brightwave");
  });
});

describe("truncateName", () => {
  it("leaves a name that fits", () => {
    expect(truncateName("a.pdf", within(10))).toBe("a.pdf");
  });

  it("cuts the end of the base and keeps the extension", () => {
    expect(truncateName("20051025_Housingcooperatives.pdf", within(18))).toBe("20051025_Hous….pdf");
  });

  it("cuts a name without an extension at the end", () => {
    expect(truncateName("Housingcooperatives", within(8))).toBe("Housing…");
  });

  it("treats a leading dot as part of the name, not an extension", () => {
    expect(truncateName(".gitignore-everything", within(8))).toBe(".gitign…");
  });

  it("leaves the name whole for the CSS ellipsis when fewer than 3 characters would show", () => {
    expect(truncateName("20051025_Housingcooperatives.pdf", within(2))).toBe("20051025_Housingcooperatives.pdf");
    expect(truncateName("20051025_Housingcooperatives.pdf", within(7))).toBe("20051025_Housingcooperatives.pdf");
    expect(truncateName("20051025_Housingcooperatives.pdf", within(8))).toBe("200….pdf");
  });

  it("does not split a character made of two code units", () => {
    expect(truncateName("😀😀😀😀😀.txt", (t) => Array.from(t).length <= 8)).toBe("😀😀😀….txt");
  });
});
