/** The address area of one document in the New look: drawn with Draw a box, moved on the
 * page, removed, and given back to the usual one; Classic shows none of it. */
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { mockFetch, renderWithProviders } from "../../test-utils";
import { FilePreview } from "../FilePreview";
import { AreaChange } from "./AreaChange";

const pdf = { drive_id: "d1", path: "##. Organize/a.pdf", ext: "pdf" };
const FOUND = { read: true, lines: [{ text: "Tiina Visser", box: [0.1, 0.1, 0.5, 0.2] }], unavailable: null };
const PEOPLE = {
  people: [{ name: "Tiina", match: ["Tiina Visser"] }],
  address_zone: [0.06, 0.1, 0.52, 0.3],
  default_address_zone: [0.06, 0.1, 0.52, 0.3],
  address_zone_set: false,
};
const AREA = "/api/files/d1/address-area";

afterEach(() => {
  cleanup();
  delete document.documentElement.dataset.style;
});

function setup(look: "new" | "classic", state: "general" | "document" | "none" = "general") {
  if (look === "new") document.documentElement.dataset.style = "new";
  // what the server holds: the save changes what the next read gives
  let held = { state, box: state === "document" ? [0.1, 0.1, 0.5, 0.2] : null };
  const calls = mockFetch({
    "GET /api/files/d1/page1": { body: { read: true, lines: [], unavailable: null } },
    "POST /api/files/d1/page1/lines": { body: FOUND },
    "GET /api/settings/people": { body: PEOPLE },
    "PUT /api/settings/people": { body: PEOPLE },
    "GET /api/rules": { body: { rules: [], errors: [], state: { offer: true, declined: 0 } } },
    "GET /api/status": { body: { special_folders: { inbox: "##. Organize" } } },
    [`GET ${AREA}`]: () => ({ body: held }),
    [`PUT ${AREA}`]: (call: { body: { box: number[] | null } }) => {
      const box = call.body.box;
      held = box ? { state: "document", box } : { state: "none", box: null };
      return { body: held };
    },
    [`DELETE ${AREA}`]: () => {
      held = { state: "general", box: null };
      return { body: held };
    },
  } as never);
  renderWithProviders(
    <MemoryRouter>
      <FilePreview file={pdf} bar={look === "new" ? <span>a.pdf</span> : undefined} boxTool={{ suggestion: { name_source: "scan", folder_source: null } }} />
    </MemoryRouter>,
  );
  return { user: userEvent.setup(), calls };
}

async function draw() {
  const surface = await screen.findByTestId("box-surface");
  surface.getBoundingClientRect = () => ({ left: 0, top: 0, width: 200, height: 400, right: 200, bottom: 400, x: 0, y: 0 }) as DOMRect;
  fireEvent.pointerDown(surface, { clientX: 20, clientY: 40, button: 0 });
  fireEvent.pointerMove(surface, { clientX: 100, clientY: 120 });
  fireEvent.pointerUp(surface, { clientX: 100, clientY: 120 });
}

describe("the address area of one document", () => {
  it("removes it, so nobody is looked for on this document", async () => {
    const { user, calls } = setup("new");
    await user.click(screen.getByRole("button", { name: "Draw a box" }));
    const group = await screen.findByRole("group", { name: "Address area of this document" });
    expect(within(group).getByText("This document uses the usual address area.")).toBeInTheDocument();
    await user.click(within(group).getByRole("button", { name: "No address area on this document" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT" && c.url === AREA)).toBe(true));
    expect(calls.find((c) => c.method === "PUT" && c.url === AREA)?.body).toEqual({ box: null });
    expect(await within(group).findByText(/has no address area/)).toBeInTheDocument();
  });

  it("gives it back to the usual area", async () => {
    const { user, calls } = setup("new", "none");
    await user.click(screen.getByRole("button", { name: "Draw a box" }));
    const group = await screen.findByRole("group", { name: "Address area of this document" });
    await user.click(within(group).getByRole("button", { name: "Use the usual address area" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.url === AREA)).toBe(true));
    expect(await within(group).findByText("This document uses the usual address area.")).toBeInTheDocument();
  });

  it("a document without one says so without Draw a box, and can get the usual one back", async () => {
    setup("new", "none");
    const group = await screen.findByRole("group", { name: "Address area of this document" });
    expect(within(group).getByRole("button", { name: "Use the usual address area" })).toBeInTheDocument();
  });

  it("a document with the usual one keeps quiet until the areas are shown or Draw a box is on", async () => {
    const { user } = setup("new");
    await screen.findByRole("button", { name: "Draw a box" });
    expect(screen.queryByRole("group", { name: "Address area of this document" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Draw a box" }));
    expect(await screen.findByRole("group", { name: "Address area of this document" })).toBeInTheDocument();
  });

  it("makes a drawn box this document's own area", async () => {
    const { user, calls } = setup("new");
    await user.click(screen.getByRole("button", { name: "Draw a box" }));
    await draw();
    const panel = await screen.findByRole("region", { name: "The boxes" });
    await user.click(await within(panel).findByRole("button", { name: "Address area for this document only" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT" && c.url === AREA)).toBe(true));
    expect(calls.find((c) => c.method === "PUT" && c.url === AREA)?.body).toEqual({ box: [0.1, 0.1, 0.5, 0.3] });
  });

  it("is not offered in Classic", async () => {
    const { user } = setup("classic");
    await user.click(screen.getByRole("button", { name: "Draw a box" }));
    await draw();
    const panel = await screen.findByRole("region", { name: "The boxes" });
    expect(await within(panel).findByRole("button", { name: "Address area for all letters" })).toBeInTheDocument();
    expect(within(panel).queryByRole("button", { name: "Address area for this document only" })).toBeNull();
    expect(screen.queryByRole("group", { name: "Address area of this document" })).toBeNull();
  });
});

describe("moving the address area on a document", () => {
  const area = { rule_id: "", index: 0, box: [0.06, 0.1, 0.52, 0.3], kind: "address" as const, lines: [], matched: true, wins: false };

  function renderChange(document = false) {
    window.document.documentElement.dataset.style = "new";
    const calls = mockFetch({
      "GET /api/settings/people": { body: PEOPLE },
      "PUT /api/settings/people": { body: PEOPLE },
      [`PUT ${AREA}`]: { body: { state: "document", box: [0.1, 0.4, 0.5, 0.6] } },
      [`DELETE ${AREA}`]: { body: { state: "general", box: null } },
    } as never);
    renderWithProviders(<AreaChange driveId="d1" area={{ ...area, document }} box={[0.1, 0.4, 0.5, 0.6]} onClose={() => {}} />);
    return { user: userEvent.setup(), calls };
  }

  it("moves it on this document at once, without asking; Undo gives back the usual area", async () => {
    const { user, calls } = renderChange();
    expect(await screen.findByText("Address area moved on this document.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(calls.find((c) => c.method === "PUT" && c.url === AREA)?.body).toEqual({ box: [0.1, 0.4, 0.5, 0.6] });
    expect(calls.some((c) => c.url === "/api/settings/people" && c.method === "PUT")).toBe(false);
    await user.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.url === AREA)).toBe(true));
  });

  it("Undo on a document with its own area puts its earlier box back", async () => {
    const { user, calls } = renderChange(true);
    await user.click(await screen.findByRole("button", { name: "Undo" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "PUT" && c.url === AREA)).toHaveLength(2));
    expect(calls.filter((c) => c.method === "PUT" && c.url === AREA)[1].body).toEqual({ box: area.box });
  });
});
