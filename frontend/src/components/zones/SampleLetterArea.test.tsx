/** Settings > Reading documents: the address area drawn on a sample letter the
 * owner picks from their computer. The letter is never added to the archive. */
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockFetch, renderWithProviders } from "../../test-utils";
import { AddressAreaSettings } from "../AddressAreaSettings";
import { linesInBox } from "./SampleLetterArea";

const PEOPLE = {
  people: [{ name: "Tiina", match: ["Tiina Visser"] }],
  address_zone: [0.06, 0.1, 0.52, 0.3],
  default_address_zone: [0.05, 0.12, 0.5, 0.28],
  address_zone_set: true,
};
const LONG = "Tiina Visser c/o Hyvinvointialueen asiakaspalvelu ja kotihoidon laskutusyksikkö".repeat(3);
const SAMPLE = {
  image: "data:image/png;base64,iVBORw0KGgo=",
  read: true,
  lines: [
    {
      text: `${LONG} Invoice`,
      box: [0.1, 0.12, 0.9, 0.14],
      words: [
        { text: LONG, box: [0.1, 0.12, 0.4, 0.14] },
        { text: "Invoice", box: [0.8, 0.12, 0.9, 0.14] },
      ],
    },
    { text: "Main Street 1", box: [0.1, 0.16, 0.3, 0.18], words: [] },
    { text: "Total 12,00", box: [0.1, 0.8, 0.3, 0.82], words: [] },
  ],
  unavailable: null,
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function setup(routes: Record<string, unknown> = {}) {
  const calls = mockFetch({
    "GET /api/settings/people": { body: PEOPLE },
    "PUT /api/settings/people": { body: PEOPLE },
    "POST /api/settings/address-area/sample": { body: SAMPLE },
    ...routes,
  } as never);
  renderWithProviders(<AddressAreaSettings />);
  return { user: userEvent.setup(), calls };
}

const letter = () => new File(["%PDF-1.4"], "Kirje 2026.pdf", { type: "application/pdf" });

async function choose(user: ReturnType<typeof userEvent.setup>) {
  const region = await screen.findByRole("region", { name: "Sample letter" });
  await user.upload(within(region).getByLabelText("Sample letter file"), letter());
  return region;
}

async function draw() {
  const surface = await screen.findByTestId("sample-surface");
  surface.getBoundingClientRect = () => ({ left: 0, top: 0, width: 200, height: 400, right: 200, bottom: 400, x: 0, y: 0 }) as DOMRect;
  // from (0.05, 0.1) to (0.5, 0.2)
  fireEvent.pointerDown(surface, { clientX: 10, clientY: 40, button: 0 });
  fireEvent.pointerMove(surface, { clientX: 100, clientY: 80 });
  fireEvent.pointerUp(surface, { clientX: 100, clientY: 80 });
}

describe("linesInBox", () => {
  it("keeps the words of a line that are in the box, and a line without words when half of it is", () => {
    const got = linesInBox(SAMPLE.lines, [0.05, 0.1, 0.5, 0.2]);
    expect(got).toEqual([LONG, "Main Street 1"]);
    expect(linesInBox(SAMPLE.lines, [0.6, 0.5, 0.7, 0.6])).toEqual([]);
  });
});

describe("The address area from a sample letter", () => {
  it("reads the chosen file, shows page 1 with the area in use, and saves the box drawn", async () => {
    const { user, calls } = setup();
    const region = await choose(user);
    const sent = calls.find((c) => c.method === "POST");
    expect(sent?.url).toBe("/api/settings/address-area/sample?name=Kirje%202026.pdf");
    expect(sent?.headers["Content-Type"]).toBe("application/octet-stream");
    expect(sent?.body).toBeInstanceOf(File);
    const page = await within(region).findByRole("img", { name: "Page 1 of the sample letter" });
    expect(page).toHaveAttribute("src", SAMPLE.image);
    // the area in use now, dashed
    const now = region.querySelector(".area-address");
    expect(now).toHaveClass("area-off");
    expect(within(region).getByRole("button", { name: "Use for all letters" })).toBeDisabled();
    await draw();
    expect(screen.getByTestId("sample-box")).toHaveStyle({ left: "5%", top: "10%" });
    const lines = within(region).getByRole("list", { name: "Lines in the box" });
    expect(within(lines).getAllByRole("listitem").map((li) => li.textContent)).toEqual([LONG, "Main Street 1"]);
    expect(within(lines).getByText(LONG)).toHaveClass("sample-line");
    expect(within(region).getByText("This replaces the area you set.")).toBeInTheDocument();
    expect(within(region).getByText(/Documents with their own address area keep it/)).toBeInTheDocument();
    await user.click(within(region).getByRole("button", { name: "Use for all letters" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ people: PEOPLE.people, address_zone: [0.05, 0.1, 0.5, 0.2] });
    expect(await within(region).findByText(/Saved\. Letters use the new area/)).toBeInTheDocument();
    expect(within(region).queryByRole("img", { name: "Page 1 of the sample letter" })).toBeNull();
  });

  it("drawing again replaces the box, and Esc drops it", async () => {
    const { user } = setup();
    await choose(user);
    await draw();
    await draw();
    expect(screen.getAllByTestId("sample-box")).toHaveLength(1);
    await user.keyboard("{Escape}");
    expect(screen.queryByTestId("sample-box")).toBeNull();
  });

  it("says why there are no lines", async () => {
    const { user } = setup({
      "POST /api/settings/address-area/sample": { body: { ...SAMPLE, read: false, lines: [], unavailable: "no OCR engine installed" } },
    });
    const region = await choose(user);
    await draw();
    expect(await within(region).findByText("The text of this letter could not be read: no OCR engine installed.")).toBeInTheDocument();
  });

  it("shows why a file is refused", async () => {
    const { user } = setup({
      "POST /api/settings/address-area/sample": { status: 400, body: { error: "A sample letter is a PDF, JPG or PNG file." } },
    });
    const region = await choose(user);
    expect(await within(region).findByRole("alert")).toHaveTextContent("A sample letter is a PDF, JPG or PNG file.");
  });

  it("Close drops the letter without saving", async () => {
    const { user, calls } = setup();
    const region = await choose(user);
    await draw();
    await user.click(within(region).getByRole("button", { name: "Close" }));
    expect(within(region).queryByRole("img", { name: "Page 1 of the sample letter" })).toBeNull();
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
  });
});
