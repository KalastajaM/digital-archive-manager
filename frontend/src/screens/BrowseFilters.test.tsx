import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import type { SearchHit } from "../api/client";
import { type Call, mockFetch, renderWithProviders } from "../test-utils";
import Browse from "./Browse";

afterEach(() => {
  cleanup();
  localStorage.clear();
});

const hit = (id: string, path: string): SearchHit => ({
  drive_id: id,
  path,
  name: path.slice(path.lastIndexOf("/") + 1),
  snippet: path.slice(path.lastIndexOf("/") + 1),
  rank: -1,
  size: 10,
  mtime: 1_700_000_000,
  marks: [],
});

const queryOf = (call: Call) => new URL(call.url, "http://x").searchParams;
const searches = (calls: Call[]) => calls.filter((c) => c.url.startsWith("/api/search"));
const lastQ = (calls: Call[]) => queryOf(searches(calls).at(-1) as Call).get("q");
const where = () => screen.getByTestId("where").textContent;
function Where() {
  const loc = useLocation();
  return <p data-testid="where">{loc.pathname + loc.search}</p>;
}

const COLLECTION = (id: number, name: string, kind: string | null = null) => ({ id, name, kind, state: "open" });

function setup(url: string) {
  const calls = mockFetch({
    "GET /api/browse": { body: [] },
    "GET /api/status": {
      body: { special_folders: { inbox: "##. Organize", ongoing: "##. Ongoing", important: "##. Important", quarantine: "##. To Delete" } },
    },
    "GET /api/search": { body: [hit("a", "one.pdf")] },
    "GET /api/tags": { body: [{ name: "insurance", files: 2 }] },
    "GET /api/collections": { body: [COLLECTION(1, "House sale"), COLLECTION(2, "Holiday"), COLLECTION(3, "★ Ongoing", "starred")] },
    "GET /api/senders": { body: [{ sender: "Kela", count: 4 }, { sender: "Pohjola", count: 1 }] },
    "GET /api/settings/people": { body: { people: [{ name: "Tiina", match: ["Tiina"] }, { name: "Michiel", match: ["Michiel"] }], address_zone: [], default_address_zone: [] } },
    "GET /api/trays": { body: { trays: [{ id: "to-pay", name: "To pay" }, { id: "to-read", name: "To read" }], errors: [] } },
    "GET /api/folders": { body: ["50. Medical", "50. Medical/Hospital", "90. Other People"] },
  });
  const user = userEvent.setup();
  renderWithProviders(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route
          path="/browse"
          element={
            <>
              <Browse />
              <Where />
            </>
          }
        />
        <Route path="/help" element={<p>Help page</p>} />
      </Routes>
    </MemoryRouter>,
  );
  return { calls, user };
}

const box = () => screen.getByRole("searchbox", { name: "Search" }) as HTMLInputElement;
const options = async () => within(await screen.findByRole("listbox", { name: "Suggestions" })).getAllByRole("option");
const chips = () => within(screen.getByRole("list", { name: "Search filters" })).getAllByRole("listitem").map((li) => li.textContent);

describe("Filter completions", () => {
  it("offers a filter name for a few letters, and the values once the colon is there", async () => {
    const { user } = setup("/browse");
    await user.type(box(), "col");
    const names = await options();
    expect(names.map((o) => o.textContent)).toContain("collection:");
    await user.click(names.find((o) => o.textContent === "collection:") as HTMLElement);
    expect(box()).toHaveValue("collection:");
    const values = await options();
    // the built-in ★ collection is not a name to search for
    expect(values.map((o) => o.textContent)).toEqual(["House sale", "Holiday"]);
    await user.click(values[0]);
    expect(where()).toBe("/browse?q=collection%3A%22House+sale%22");
    expect(chips()).toEqual(["collection:House sale×"]);
    expect(box()).toHaveValue("");
  });

  it("completes senders, people, trays, folders, types and is: words", async () => {
    const { user } = setup("/browse");
    const offered = async (typed: string) => {
      await user.clear(box());
      await user.type(box(), typed);
      return (await options()).map((o) => o.textContent);
    };
    expect(await offered("from:k")).toEqual(["Kela4"]);
    expect(await offered("for:ti")).toEqual(["Tiina"]);
    expect(await offered("tray:to-p")).toEqual(["to-payTo pay"]);
    expect(await offered("in:hosp")).toEqual(["50. Medical/Hospital"]);
    expect(await offered("type:i")).toEqual(["image"]);
    expect(await offered("is:lo")).toEqual(["locked"]);
    expect(await offered("tag:ins")).toEqual(["insurance2"]);
  });

  it("the arrow keys and Enter pick a suggestion, as for tags", async () => {
    const { user } = setup("/browse");
    await user.type(box(), "is:");
    await options();
    await user.keyboard("{ArrowDown}{ArrowDown}{Enter}");
    expect(where()).toBe("/browse?q=is%3Aimportant");
    expect(chips()).toEqual(["is:important×"]);
  });

  it("Enter finishes a filter that has no suggestions as typed", async () => {
    const { user } = setup("/browse");
    await user.type(box(), "date:2026-10{Enter}");
    expect(where()).toBe("/browse?q=date%3A2026-10");
    expect(box()).toHaveValue("");
  });

  it("a - in front makes a negated filter with its own chip", async () => {
    const { user, calls } = setup("/browse");
    await user.type(box(), 'kela -tag:paid -in:"90. Other People" ');
    expect(chips()).toEqual(["not tag:paid×", "not in:90. Other People×"]);
    expect(box().value.trim()).toBe("kela");
    await waitFor(() => expect(lastQ(calls)).toBe('kela -tag:paid -in:"90. Other People"'));
  });

  it("an unknown name stays a word and searches as text", async () => {
    const { user, calls } = setup("/browse");
    await user.type(box(), "http://x.org ");
    await waitFor(() => expect(lastQ(calls)).toBe("http://x.org"));
    expect(screen.queryByRole("list", { name: "Search filters" })).not.toBeInTheDocument();
  });
});

describe("The filter row and the address", () => {
  it("shows every kind of filter as a chip, and a chip's x removes just that one", async () => {
    const { user, calls } = setup("/browse?q=kela+type%3Apdf+-tag%3Apaid+after%3A2025");
    await screen.findByText("one.pdf");
    expect(chips()).toEqual(["type:pdf×", "not tag:paid×", "after:2025×"]);
    expect(box()).toHaveValue("kela");
    await user.click(screen.getByRole("button", { name: "Remove filter -tag:paid" }));
    expect(where()).toBe("/browse?q=kela+type%3Apdf+after%3A2025");
    await waitFor(() => expect(lastQ(calls)).toBe("kela type:pdf after:2025"));
  });

  it("All / Any belongs to the tags only", async () => {
    const { user, calls } = setup("/browse?q=type%3Apdf+tag%3Aa+tag%3Ab+-tag%3Ac");
    await screen.findByText("one.pdf");
    const mode = screen.getByRole("group", { name: "Match tags" });
    await user.click(within(mode).getByRole("button", { name: "Any" }));
    expect(where()).toBe("/browse?q=type%3Apdf+tag%3Aa+tag%3Ab+-tag%3Ac&tag_mode=any");
    await waitFor(() => expect(queryOf(searches(calls).at(-1) as Call).get("tag_mode")).toBe("any"));
  });

  it("filters alone do not show All / Any", async () => {
    setup("/browse?q=type%3Apdf+date%3A2026");
    await screen.findByText("one.pdf");
    expect(screen.queryByRole("group", { name: "Match tags" })).not.toBeInTheDocument();
  });

  it("the words follow into the address as they are typed, without piling up history", async () => {
    const { user } = setup("/browse?q=tag%3Aa");
    await screen.findByText("one.pdf");
    await user.type(box(), "kela");
    await waitFor(() => expect(where()).toBe("/browse?q=kela+tag%3Aa"));
    expect(box()).toHaveValue("kela");
  });

  it("a search error from a bad value is shown", async () => {
    const calls = mockFetch({
      "GET /api/browse": { body: [] },
      "GET /api/status": { body: { special_folders: { inbox: "i", ongoing: "o", important: "m", quarantine: "q" } } },
      "GET /api/search": { status: 400, body: { error: "'x' is not a date. Use YYYY, YYYY-MM or YYYY-MM-DD." } },
    });
    renderWithProviders(
      <MemoryRouter initialEntries={["/browse?q=date%3Ax"]}>
        <Browse />
      </MemoryRouter>,
    );
    expect(await screen.findByText(/is not a date/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove filter date:x" })).toBeInTheDocument();
    expect(calls.length).toBeGreaterThan(0);
  });
});

describe("The ? popup", () => {
  it("opens next to the search box and lists every filter with an example", async () => {
    const { user } = setup("/browse");
    await user.click(screen.getByRole("button", { name: "Search help" }));
    const pop = screen.getByRole("dialog", { name: "Search filters" });
    for (const name of ["name:", "in:", "tag:", "collection:", "from:", "for:", "type:", "date:", "before:", "after:", "tray:", "is:"]) {
      expect(within(pop).getAllByRole("button").some((b) => b.textContent?.startsWith(name))).toBe(true);
    }
    expect(within(pop).getByText(/quotes/i)).toBeInTheDocument();
    expect(within(pop).getByRole("link", { name: "Searching in the guide" })).toHaveAttribute("href", "/help#searching");
  });

  it("a click on an example puts it in the box and closes the popup", async () => {
    const { user } = setup("/browse");
    await user.type(box(), "kela");
    await user.click(screen.getByRole("button", { name: "Search help" }));
    await user.click(within(screen.getByRole("dialog", { name: "Search filters" })).getByRole("button", { name: "tag:insurance" }));
    expect(screen.queryByRole("dialog", { name: "Search filters" })).not.toBeInTheDocument();
    expect(box()).toHaveValue("kela tag:insurance");
    // it is still being edited; Enter makes it a chip
    await user.type(box(), "{Enter}");
    expect(chips()).toEqual(["tag:insurance×"]);
    expect(where()).toBe("/browse?q=kela+tag%3Ainsurance");
  });

  it("Esc and a click outside close it", async () => {
    const { user } = setup("/browse");
    const open = () => user.click(screen.getByRole("button", { name: "Search help" }));
    await open();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Search filters" })).not.toBeInTheDocument();
    await open();
    await user.click(document.body);
    expect(screen.queryByRole("dialog", { name: "Search filters" })).not.toBeInTheDocument();
    await open();
    await open(); // the button toggles
    expect(screen.queryByRole("dialog", { name: "Search filters" })).not.toBeInTheDocument();
  });

  it("the link goes to the guide's Searching section", async () => {
    const { user } = setup("/browse");
    await user.click(screen.getByRole("button", { name: "Search help" }));
    await user.click(screen.getByRole("link", { name: "Searching in the guide" }));
    expect(await screen.findByText("Help page")).toBeInTheDocument();
  });
});
