import { describe, expect, it } from "vitest";
import {
  ADD_FROM_OWN_FOLDER,
  ALREADY_HERE,
  collectionAt,
  DELETE_TARGET_REASON,
  type DropInput,
  IMPORTANT_MOVE_REASON,
  IMPORTANT_TARGET_REASON,
  judgeDrop,
  LINK_OFF_REASON,
  MIXED_REASON,
  ONGOING_ROOT_REASON,
  TOP_REASON,
  APP_FOLDER_REASON,
  EXTRA_ROOT_REASON,
  FOLDER_INTO_ITSELF,
  FOLDER_TOP_REASON,
  folderSourceRefusal,
  judgeFolderDrop,
  ONGOING_TARGET_REASON,
} from "./dropModes";
import { LOCKED_REASON } from "./api/client";
import { TO_DELETE_REASON } from "./toDelete";

const areas = { quarantine: "##. To Delete", ongoing: "##. Ongoing", important: "##. Important" };
const sauna = { id: 7, name: "Sauna", ongoing_rel: "##. Ongoing/Sauna", members: [] as { drive_id: string }[] };
const input = (over: Partial<DropInput>): DropInput => ({
  dragged: [{ id: "a", path: "10. Financial/a.pdf", locked: false }],
  count: 1,
  target: "13. Taxes",
  areas,
  collections: [sauna],
  canLink: true,
  alt: false,
  ...over,
});

describe("judgeDrop", () => {
  it("an ordinary drop offers all three ways, Move first", () => {
    expect(judgeDrop(input({}))).toEqual({
      kind: "files",
      modes: { move: null, link: null, copy: null },
      initial: "move",
      place: "plain",
    });
  });

  it("Option preselects Copy", () => {
    expect(judgeDrop(input({ alt: true }))).toMatchObject({ kind: "files", initial: "copy" });
  });

  it("the file's own folder: refused, unless Option asks for a copy (Move and Link stay off)", () => {
    const here = { target: "10. Financial" };
    expect(judgeDrop(input(here))).toMatchObject({ kind: "refused" });
    expect(judgeDrop(input({ ...here, alt: true }))).toEqual({
      kind: "files",
      modes: { move: ALREADY_HERE, link: ALREADY_HERE, copy: null },
      initial: "copy",
      place: "plain",
    });
  });

  it("a locked file keeps its refusal, but may still be copied with Option", () => {
    const locked = { dragged: [{ id: "a", path: "10. Financial/a.pdf", locked: true }] };
    expect(judgeDrop(input(locked))).toEqual({ kind: "refused", reason: LOCKED_REASON });
    expect(judgeDrop(input({ ...locked, alt: true }))).toMatchObject({
      modes: { move: LOCKED_REASON, link: null, copy: null },
      initial: "copy",
    });
  });

  it("Link is off where links cannot be made", () => {
    expect(judgeDrop(input({ canLink: false }))).toMatchObject({ modes: { link: LINK_OFF_REASON } });
  });

  it("the top of the archive and the app's folders as targets", () => {
    expect(judgeDrop(input({ target: "" }))).toEqual({ kind: "refused", reason: TOP_REASON });
    expect(judgeDrop(input({ target: "##. Ongoing" }))).toEqual({ kind: "refused", reason: ONGOING_ROOT_REASON });
    expect(judgeDrop(input({ target: "##. To Delete/10. Financial" }))).toEqual({ kind: "refused", reason: DELETE_TARGET_REASON });
    expect(judgeDrop(input({ target: "##. Important" }))).toEqual({ kind: "refused", reason: IMPORTANT_TARGET_REASON });
  });

  it("a collection's folder in Ongoing: the only thing a drop does is add to it", () => {
    expect(judgeDrop(input({ target: "##. Ongoing/Sauna" }))).toEqual({ kind: "collection", collection: sauna });
    // a group's folder inside it belongs to the same collection
    expect(judgeDrop(input({ target: "##. Ongoing/Sauna/Plans" }))).toMatchObject({ kind: "collection" });
    // a folder in Ongoing that is no collection's
    expect(judgeDrop(input({ target: "##. Ongoing/Other" }))).toEqual({ kind: "refused", reason: ONGOING_ROOT_REASON });
    const member = { ...sauna, members: [{ drive_id: "a" }] };
    expect(judgeDrop(input({ target: "##. Ongoing/Sauna", collections: [member] }))).toEqual({
      kind: "refused",
      reason: "Already in Sauna",
    });
    // the links of Ongoing and Important are not files to add
    const row = { dragged: [{ id: "l", path: "##. Ongoing/Sauna/a.pdf", locked: false }] };
    expect(judgeDrop(input({ ...row, target: "##. Ongoing/Sauna/Plans" }))).toEqual({ kind: "refused", reason: ADD_FROM_OWN_FOLDER });
  });

  it("rows of Ongoing move the real file; Important rows cannot be moved but linked or copied", () => {
    const ongoing = { dragged: [{ id: "l", path: "##. Ongoing/Sauna/a.pdf", locked: false }] };
    expect(judgeDrop(input(ongoing))).toMatchObject({ kind: "files", place: "ongoing", initial: "move" });
    const important = { dragged: [{ id: "i", path: "##. Important/p.pdf", locked: false }] };
    expect(judgeDrop(input(important))).toEqual({
      kind: "files",
      modes: { move: IMPORTANT_MOVE_REASON, link: null, copy: null },
      initial: "link",
      place: "important",
    });
  });

  it("rows of To Delete restore into the folder, with no choice", () => {
    const gone = { dragged: [{ id: "t", path: "##. To Delete/10. Financial/old.pdf", locked: false }] };
    expect(judgeDrop(input(gone))).toEqual({ kind: "restore", folder: "13. Taxes" });
    expect(judgeDrop(input({ ...gone, target: "##. To Delete/x" }))).toEqual({ kind: "refused", reason: "Already in To Delete" });
  });

  it("files from different places are dragged one place at a time", () => {
    const mixed = {
      dragged: [
        { id: "a", path: "10. Financial/a.pdf", locked: false },
        { id: "l", path: "##. Ongoing/Sauna/a.pdf", locked: false },
      ],
      count: 2,
    };
    expect(judgeDrop(input(mixed))).toEqual({ kind: "refused", reason: MIXED_REASON });
  });
});

describe("collectionAt", () => {
  it("picks the deepest collection folder", () => {
    const inner = { id: 8, name: "Inner", ongoing_rel: "##. Ongoing/Sauna/Inner", members: [] };
    expect(collectionAt("##. Ongoing/Sauna/Inner/x", [sauna, inner])?.id).toBe(8);
    expect(collectionAt("##. Ongoing/Sauna", [sauna, inner])?.id).toBe(7);
    expect(collectionAt("##. Ongoing/Nope", [sauna, inner])).toBeNull();
  });
});

describe("judgeFolderDrop", () => {
  const special = { ...areas, inbox: "##. Organize" };
  const folder = { path: "20. Home/2009", folder: null };
  const judge = (target: string, f: { path: string; folder?: string | null } = folder) =>
    judgeFolderDrop({ folder: f, target, areas: special });

  it("takes an ordinary folder elsewhere, also the top of an extra folder", () => {
    expect(judge("Old years")).toBeNull();
    expect(judge("30. Car/Old")).toBeNull();
  });

  it("never into itself or its own subfolder; not where it is already", () => {
    expect(judge("20. Home/2009")).toBe(FOLDER_INTO_ITSELF);
    expect(judge("20. Home/2009/sub")).toBe(FOLDER_INTO_ITSELF);
    expect(FOLDER_INTO_ITSELF).toBe("Cannot move a folder into itself");
    expect(judge("20. Home")).toBe(ALREADY_HERE);
    expect(judge("20. Home/2009x")).toBeNull(); // a sibling with a longer name is no subfolder
  });

  it("never to the top of the archive or into the app's own folders", () => {
    expect(judge("")).toBe(FOLDER_TOP_REASON);
    expect(judge("##. To Delete/x")).toBe(DELETE_TARGET_REASON);
    expect(judge("##. Important")).toBe(IMPORTANT_TARGET_REASON);
    expect(judge("##. Ongoing/Sauna")).toBe(ONGOING_TARGET_REASON);
  });

  it("refuses the folders the app keeps in place", () => {
    expect(folderSourceRefusal({ path: "Old years", folder: "Old years" }, special)).toBe(EXTRA_ROOT_REASON);
    for (const path of ["##. Organize", "##. Ongoing", "##. Important", "##. To Delete"]) {
      expect(folderSourceRefusal({ path }, special)).toBe(APP_FOLDER_REASON);
    }
    expect(folderSourceRefusal({ path: "##. Ongoing/Sauna" }, special)).toMatch(/##\. Ongoing/);
    expect(folderSourceRefusal({ path: "##. Important/x" }, special)).toMatch(/##\. Important/);
    expect(folderSourceRefusal({ path: "##. To Delete/x" }, special)).toBe(TO_DELETE_REASON);
    expect(folderSourceRefusal({ path: "##. Organize/Scans" }, special)).toBeNull(); // inside the inbox is ordinary
    expect(folderSourceRefusal({ path: "Old years/2009", folder: "Old years" }, special)).toBeNull();
    expect(folderSourceRefusal({ path: "x" }, undefined)).toBe("The special folders are not known yet");
    expect(judge("Old years", { path: "##. Ongoing/Sauna" })).toMatch(/##\. Ongoing/); // the source first
  });
});
