import { describe, expect, it } from "vitest";
import { collectionMoveRunning, endCollectionMove, movedText, recreatedLinks, startCollectionMove, subtreeOf } from "./collectionTree";

const c = (id: number, parent_id: number | null) => ({ id, name: `c${id}`, parent_id });

describe("collectionTree", () => {
  it("subtreeOf: the collection and everything under it, nothing else", () => {
    const list = [c(1, null), c(2, 1), c(3, 2), c(4, null), c(5, 4), c(6, 1)];
    expect([...subtreeOf(list, 1)].sort()).toEqual([1, 2, 3, 6]);
    expect([...subtreeOf(list, 3)]).toEqual([3]);
  });

  it("movedText names the target and, past 50 recreated links, how many (a slow move explained)", () => {
    expect(movedText("Sauna", "Car")).toBe("Moved Sauna into Car");
    expect(movedText("Sauna", null)).toBe("Moved Sauna to the top level");
    expect(movedText("Sauna", "Car", 50)).toBe("Moved Sauna into Car");
    expect(movedText("Sauna", null, 51)).toBe("Moved Sauna to the top level (recreated 51 links)");
  });

  it("recreatedLinks counts the links the move's batch made", () => {
    const op = (kind: string) => ({ kind, src: null, dst: "x", drive_id: null, note: null });
    expect(recreatedLinks({ batch: null })).toBe(0);
    expect(recreatedLinks({ batch: { done: [op("mkdir"), op("symlink"), op("symlink"), op("unlink_symlink")] } })).toBe(2);
  });

  it("one collection move at a time, shared by every caller", () => {
    expect(startCollectionMove()).toBe(true);
    expect(collectionMoveRunning()).toBe(true);
    expect(startCollectionMove()).toBe(false);
    endCollectionMove();
    expect(startCollectionMove()).toBe(true);
    endCollectionMove();
  });
});
