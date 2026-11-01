/** Versions in the file's panel: the notice, the rows, the move and Not a version. */
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { type Call, mockFetch, renderWithProviders } from "../test-utils";
import css from "../styles.css?raw";
import { VersionsBlock, VersionsNotice } from "./VersionsBlock";

const FOLDER = "30. Home/Legal";
const LONG = `${"Lease agreement with a very long name ".repeat(6)}.docx`;
const file = (drive_id: string, name: string, mtime: number | null, extra = {}) => ({
  drive_id,
  name,
  path: `${FOLDER}/${name}`,
  mtime,
  latest: false,
  in_archive: false,
  ...extra,
});
const FILES = [
  file("d3", "Lease final (1).docx", 1760000000, { latest: true }),
  file("d0", "Lease final.docx", 1759000000),
  file("d1", "Lease v2.docx", 1758000000),
  file("d2", "Lease.docx", 1757000000, { in_archive: true, path: `${FOLDER}/Archive/Lease.docx` }),
];
const body = (over = {}) => ({
  files: FILES,
  latest: "d3",
  hidden: 0,
  folder: `${FOLDER}/Archive`,
  movable: ["d0", "d1"],
  staying: [],
  blocked: null,
  ...over,
});
const NONE = body({ files: [], latest: null, folder: null, movable: [] });
const sent = (calls: Call[], method: string, url: string) => calls.filter((c) => c.method === method && c.url === url);

function block(data: unknown, routes: Parameters<typeof mockFetch>[0] = {}, driveId = "d0") {
  const calls = mockFetch({ [`GET /api/files/${driveId}/versions`]: { body: data }, ...routes });
  const view = renderWithProviders(
    <MemoryRouter>
      <VersionsNotice driveId={driveId} />
      <VersionsBlock driveId={driveId} />
    </MemoryRouter>,
  );
  return { calls, ...view };
}

afterEach(cleanup);

describe("the notice", () => {
  it("names the latest and links to it in Browse", async () => {
    block(body());
    const notice = await screen.findByText(/^Newer version:/);
    const link = within(notice).getByRole("link", { name: "Lease final (1).docx" });
    expect(link.getAttribute("href")).toContain("d3");
    expect(notice.textContent).toMatch(/^Newer version: Lease final \(1\)\.docx, /);
  });

  it("is not shown on the latest", async () => {
    block(body(), {}, "d3");
    await screen.findByText("Versions");
    expect(document.querySelector(".versions-notice")).toBeNull();
  });

  it("nothing at all for a file without versions", async () => {
    const { calls } = block(NONE);
    await waitFor(() => expect(sent(calls, "GET", "/api/files/d0/versions").length).toBeGreaterThan(0));
    expect(screen.queryByText("Versions")).toBeNull();
    expect(document.querySelector(".versions-notice")).toBeNull();
  });
});

describe("the block", () => {
  it("lists the rows newest first with their markers", async () => {
    block(body());
    await screen.findByText("Versions");
    const rows = [...document.querySelectorAll<HTMLElement>(".version-row")];
    expect(rows.map((r) => r.dataset.driveId)).toEqual(["d3", "d0", "d1", "d2"]);
    expect(within(rows[0]).getByText("Latest")).toBeTruthy();
    expect(within(rows[1]).getByText("This file")).toBeTruthy();
    expect(within(rows[3]).getByText("Archived")).toBeTruthy();
  });

  it("moves the movable files through the preview", async () => {
    const { calls } = block(body(), {
      "POST /api/browse/move/preview": {
        body: [{ kind: "move", src: `${FOLDER}/Lease v2.docx`, dst: `${FOLDER}/Archive/Lease v2.docx`, drive_id: "d1" }],
      },
    });
    await userEvent.click(await screen.findByRole("button", { name: "Move 2 older to Archive…" }));
    await waitFor(() =>
      expect(sent(calls, "POST", "/api/browse/move/preview")[0]?.body).toEqual({
        drive_ids: ["d0", "d1"],
        folder: `${FOLDER}/Archive`,
      }),
    );
    expect(sent(calls, "POST", "/api/browse/move")).toHaveLength(0);
  });

  it("greys the move and says why", async () => {
    block(body({ movable: [], blocked: "The older versions are locked" }));
    const button = await screen.findByRole("button", { name: "Move older…" });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    expect(button.getAttribute("title")).toBe("The older versions are locked");
  });

  it("names the files that stay", async () => {
    block(body({ movable: ["d1"], staying: [{ name: "Lease final.docx", reason: "locked" }] }));
    expect(await screen.findByText(/1 file will stay: Lease final\.docx \(locked\)/)).toBeTruthy();
  });

  it("marks a pair not a version, with Undo", async () => {
    const { calls } = block(body(), {
      "POST /api/files/d0/versions/dismiss": { body: { dismissed: [] } },
      "POST /api/files/d0/versions/restore": { body: { dismissed: [] } },
    });
    await userEvent.click(await screen.findByRole("button", { name: "Not a version: Lease v2.docx" }));
    await waitFor(() =>
      expect(sent(calls, "POST", "/api/files/d0/versions/dismiss")[0]?.body).toEqual({ drive_id: "d1" }),
    );
    await userEvent.click(await screen.findByRole("button", { name: "Undo" }));
    await waitFor(() =>
      expect(sent(calls, "POST", "/api/files/d0/versions/restore")[0]?.body).toEqual({ drive_id: "d1" }),
    );
  });

  it("None of these are versions marks all the others with one Undo", async () => {
    const { calls } = block(body(), {
      "POST /api/files/d0/versions/dismiss": { body: { dismissed: [] } },
    });
    await userEvent.click(await screen.findByRole("button", { name: "None of these are versions" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/files/d0/versions/dismiss")).toHaveLength(3));
    expect(await screen.findByText("3 files marked not a version")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Undo" })).toHaveLength(1);
  });

  it("shows what is marked, and Show again takes the mark off", async () => {
    const { calls } = block(body({ hidden: 1 }), {
      "GET /api/files/d0/versions/dismissed": {
        body: { dismissed: [{ drive_id: "d9", path: `${FOLDER}/Lease old.docx`, name: "Lease old.docx" }] },
      },
      "POST /api/files/d0/versions/restore": { body: { dismissed: [] } },
    });
    await userEvent.click(await screen.findByRole("button", { name: "1 marked not a version" }));
    await userEvent.click(await screen.findByRole("button", { name: "Show Lease old.docx again" }));
    await waitFor(() =>
      expect(sent(calls, "POST", "/api/files/d0/versions/restore")[0]?.body).toEqual({ drive_id: "d9" }),
    );
  });

  it("still offers the way back when every other file is marked", async () => {
    block(body({ files: [], latest: null, folder: null, movable: [], hidden: 2 }));
    expect(await screen.findByRole("button", { name: "2 marked not versions" })).toBeTruthy();
  });

  it("wraps a long name, since its end tells the versions apart", async () => {
    block(body({ files: [file("d0", LONG, 1759000000), file("d3", LONG, 1760000000, { latest: true })] }));
    await screen.findByText("Versions");
    const names = [...document.querySelectorAll(".version-name")];
    expect(names[0].classList.contains("trunc")).toBe(false);
    expect(css).toMatch(/\.version-name \{[^}]*overflow-wrap: anywhere/);
    expect(names[0].getAttribute("title")).toContain(LONG);
  });
});
