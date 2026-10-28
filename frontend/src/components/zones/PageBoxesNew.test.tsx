/** Draw a box in the New look as drawn on the board: the document bar leads with the file,
 * the hint sits beside the pressed button, and the panel numbers each box with its colour,
 * lists the words found as chips and ends with Back to filing and Make a rule. Classic keeps
 * its panel. */
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { mockFetch, renderWithProviders } from "../../test-utils";
import { FilePreview } from "../FilePreview";

const pdf = { drive_id: "d1", path: "##. Organize/a.pdf", ext: "pdf" };
const FOUND = { read: true, lines: [{ text: "Pohjola Vakuutus Oy", box: [0.1, 0.1, 0.5, 0.2] }], unavailable: null };

afterEach(() => {
  cleanup();
  delete document.documentElement.dataset.style;
});

function setup(look: "new" | "classic") {
  if (look === "new") document.documentElement.dataset.style = "new";
  mockFetch({
    "GET /api/files/d1/page1": { body: { read: true, lines: [], unavailable: null } },
    "POST /api/files/d1/page1/lines": { body: FOUND },
    "GET /api/settings/people": { body: { people: [], address_zone: [0.06, 0.1, 0.52, 0.3], default_address_zone: [0.06, 0.1, 0.52, 0.3] } },
    "GET /api/rules": { body: { rules: [], errors: [], state: { offer: true, declined: 0 } } },
    "GET /api/status": { body: { special_folders: { inbox: "##. Organize" } } },
  } as never);
  renderWithProviders(
    <MemoryRouter>
      <FilePreview file={pdf} bar={look === "new" ? <span>a.pdf</span> : undefined} boxTool={{ suggestion: { name_source: "scan", folder_source: null } }} />
    </MemoryRouter>,
  );
  return userEvent.setup();
}

async function draw() {
  const surface = await screen.findByTestId("box-surface");
  surface.getBoundingClientRect = () => ({ left: 0, top: 0, width: 200, height: 400, right: 200, bottom: 400, x: 0, y: 0 }) as DOMRect;
  fireEvent.pointerDown(surface, { clientX: 20, clientY: 40, button: 0 });
  fireEvent.pointerMove(surface, { clientX: 100, clientY: 120 });
  fireEvent.pointerUp(surface, { clientX: 100, clientY: 120 });
}

describe("Draw a box in the New look", () => {
  it("shows the tool as a button with words, and the hint in the document bar", async () => {
    const user = setup("new");
    const bar = screen.getByRole("toolbar", { name: "Document" });
    const button = within(bar).getByRole("button", { name: "Draw a box" });
    expect(button).toHaveTextContent("Draw a box");
    await user.click(button);
    expect(button).toHaveAttribute("aria-pressed", "true");
    expect(await within(bar).findByText(/Drag over page 1 to draw a box/)).toBeInTheDocument();
  });

  it("numbers the box, lists its words as chips, and ends with Back to filing and Make a rule", async () => {
    const user = setup("new");
    await user.click(screen.getByRole("button", { name: "Draw a box" }));
    await draw();
    const panel = await screen.findByRole("region", { name: "The boxes" });
    expect(panel).toHaveTextContent("A box is a place on page 1. In a rule it becomes an area.");
    expect(await within(panel).findByText("Words found in it")).toBeInTheDocument();
    expect(within(panel).getByText("Pohjola Vakuutus Oy")).toHaveClass("box-word");
    expect(screen.getByTestId("kept-box")).toHaveAttribute("data-tone", "0");
    expect(within(panel).getByRole("button", { name: "Make a rule…" })).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Back to filing" }));
    expect(screen.queryByRole("region", { name: "The boxes" })).toBeNull();
    expect(screen.queryByTestId("kept-box")).toBeNull();
  });
});

describe("Draw a box in Classic", () => {
  it("has no bar, no words on the button and no Back to filing", async () => {
    const user = setup("classic");
    expect(screen.queryByRole("toolbar", { name: "Document" })).toBeNull();
    const button = screen.getByRole("button", { name: "Draw a box" });
    expect(button).not.toHaveTextContent("Draw a box");
    await user.click(button);
    await draw();
    const panel = await screen.findByRole("region", { name: "The boxes" });
    expect(within(panel).queryByRole("button", { name: "Back to filing" })).toBeNull();
    expect(within(panel).queryByText("Words found in it")).toBeNull();
  });
});
