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

describe("the owner's order", () => {
  const n = (id: number, name: string, position: number, parent_id: number | null = null) => ({ id, name, position, parent_id });
  const list = [n(1, "Apple", 2), n(2, "Zed", 0), n(3, "Mango", 1), n(4, "Kid b", 1, 2), n(5, "Kid a", 0, 2)];

  it("sorts siblings by position, then name", async () => {
    const { childrenOf } = await import("./collectionTree");
    expect(childrenOf(list).get(null)!.map((c) => c.name)).toEqual(["Zed", "Mango", "Apple"]);
    const ties = [n(1, "b", 0), n(2, "A", 0)];
    expect(childrenOf(ties).get(null)!.map((c) => c.name)).toEqual(["A", "b"]);
  });

  it("inTreeOrder is depth-first in that order", async () => {
    const { inTreeOrder, dropZone } = await import("./collectionTree");
    expect(inTreeOrder(list).map((c) => c.name)).toEqual(["Zed", "Kid a", "Kid b", "Mango", "Apple"]);
    const rect = { top: 100, height: 40 };
    expect(dropZone(102, rect)).toBe("before");
    expect(dropZone(120, rect)).toBeNull();
    expect(dropZone(138, rect)).toBe("after");
    expect(dropZone(110, rect, true)).toBe("before");
    expect(dropZone(130, rect, true)).toBe("after");
  });
});
