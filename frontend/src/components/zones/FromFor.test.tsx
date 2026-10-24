import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { type InboxEntry, useInbox } from "../../api/client";
import { type Call, mockFetch, renderWithProviders } from "../../test-utils";
import { AssignSheet, FromFor } from "./FromFor";

const PEOPLE = {
  people: [
    { name: "Michiel", match: ["Michiel Visser"] },
    { name: "Tiina", match: ["Tiina Visser"] },
  ],
  address_zone: [0.06, 0.1, 0.52, 0.3],
  default_address_zone: [0.06, 0.1, 0.52, 0.3],
};

function entry(
  suggestion: Record<string, unknown> = {},
  assignment: Record<string, unknown> | null = null,
): InboxEntry {
  return {
    record: { drive_id: "d1", path: "##. Organize/a.pdf", name: "a.pdf" },
    suggestion: { person: null, person_source: null, people_found: [], waiting_for_page1: false, ...suggestion },
    assignment,
  } as unknown as InboxEntry;
}
const assigned = (set_by: "owner" | "filing", over: Record<string, unknown> = {}) => ({
  drive_id: "d1",
  sender: "Pohjola",
  person: "Tiina",
  set_by,
  set_at: 1,
  ...over,
});
const puts = (calls: Call[]) => calls.filter((c) => c.method === "PUT" && c.url === "/api/assignments");

/** Something showing the inbox, so that a change that reloads it can be seen. */
function InboxProbe() {
  useInbox();
  return null;
}

function setup(ui: React.ReactElement, extra: Parameters<typeof mockFetch>[0] = {}) {
  const calls = mockFetch({
    "GET /api/settings/people": { body: PEOPLE },
    "GET /api/senders": { body: [{ sender: "Pohjola", count: 14 }, { sender: "Verohallinto", count: 3 }] },
    "GET /api/inbox": { body: [] },
    "PUT /api/assignments": { body: [] },
    ...extra,
  });
  renderWithProviders(
    <>
      <InboxProbe />
      {ui}
    </>,
  );
  return { calls, user: userEvent.setup() };
}

describe("From and For chips", () => {
  it("say nothing is set, and offer the picker", async () => {
    setup(<FromFor entry={entry()} />);
    expect(screen.getByRole("button", { name: "From: not set" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "For: not set" })).toBeInTheDocument();
  });

  it.each([
    ["assigned", entry({ person: "Tiina", person_source: "assigned" }, assigned("owner")), "For: Tiina · you set this"],
    ["address area", entry({ person: "Tiina", person_source: "address area" }), "For: Tiina · address area"],
    ["rule", entry({ person: "Tiina", person_source: "rule:pohjola" }), "For: Tiina · rule pohjola"],
    ["filed", entry({ person: "Tiina", person_source: "assigned" }, assigned("filing")), "For: Tiina · filed"],
  ])("name where the person came from: %s", (_name, e, expected) => {
    setup(<FromFor entry={e} />);
    expect(screen.getByRole("button", { name: expected })).toBeInTheDocument();
  });

  it("name where the sender came from", () => {
    setup(<FromFor entry={entry({}, assigned("owner", { person: null }))} />);
    expect(screen.getByRole("button", { name: "From: Pohjola · you set this" })).toBeInTheDocument();
  });

  it("set the person from the list and reload the inbox", async () => {
    const { calls, user } = setup(<FromFor entry={entry()} />);
    await user.click(screen.getByRole("button", { name: "For: not set" }));
    const sheet = await screen.findByRole("dialog", { name: "For" });
    expect(within(sheet).getByRole("button", { name: "Save" })).toBeDisabled();
    await user.click(await within(sheet).findByRole("button", { name: "Tiina" }));
    await user.click(within(sheet).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(puts(calls)).toHaveLength(1));
    expect(puts(calls)[0].body).toEqual({ drive_ids: ["d1"], person: "Tiina" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(calls.filter((c) => c.url === "/api/inbox").length).toBeGreaterThan(1));
  });

  it("set a sender typed or picked from the ones in use", async () => {
    const { calls, user } = setup(<FromFor entry={entry()} />);
    await user.click(screen.getByRole("button", { name: "From: not set" }));
    const sheet = await screen.findByRole("dialog", { name: "From" });
    await user.type(within(sheet).getByLabelText("Sender"), "Kela{Enter}");
    await waitFor(() => expect(puts(calls)).toHaveLength(1));
    expect(puts(calls)[0].body).toEqual({ drive_ids: ["d1"], sender: "Kela" });
  });

  it("pick a sender in use", async () => {
    const { calls, user } = setup(<FromFor entry={entry()} />);
    await user.click(screen.getByRole("button", { name: "From: not set" }));
    const sheet = await screen.findByRole("dialog", { name: "From" });
    await user.click(await within(sheet).findByRole("button", { name: /^Verohallinto/ }));
    expect(within(sheet).getByLabelText("Sender")).toHaveValue("Verohallinto");
    await user.click(within(sheet).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(puts(calls)).toHaveLength(1));
    expect(puts(calls)[0].body).toEqual({ drive_ids: ["d1"], sender: "Verohallinto" });
  });

  it("Clear takes the person away", async () => {
    const { calls, user } = setup(<FromFor entry={entry({ person: "Tiina", person_source: "assigned" }, assigned("owner"))} />);
    await user.click(screen.getByRole("button", { name: /^For: Tiina/ }));
    const sheet = await screen.findByRole("dialog", { name: "For" });
    await user.click(within(sheet).getByRole("button", { name: "Clear" }));
    await waitFor(() => expect(puts(calls)).toHaveLength(1));
    expect(puts(calls)[0].body).toEqual({ drive_ids: ["d1"], person: null });
  });

  it("offer no Clear for a person that was only found in the address area", async () => {
    const { user } = setup(<FromFor entry={entry({ person: "Tiina", person_source: "address area" })} />);
    await user.click(screen.getByRole("button", { name: /^For: Tiina/ }));
    const sheet = await screen.findByRole("dialog", { name: "For" });
    expect(within(sheet).queryByRole("button", { name: "Clear" })).toBeNull();
    expect(within(sheet).getByRole("button", { name: "Save" })).toBeInTheDocument();
  });

  it("show the server's message when saving fails", async () => {
    const { user } = setup(<FromFor entry={entry()} />, { "PUT /api/assignments": { status: 400, body: { error: "Unknown person" } } });
    await user.click(screen.getByRole("button", { name: "For: not set" }));
    const sheet = await screen.findByRole("dialog", { name: "For" });
    await user.click(await within(sheet).findByRole("button", { name: "Tiina" }));
    await user.click(within(sheet).getByRole("button", { name: "Save" }));
    expect(await within(sheet).findByText("Unknown person")).toBeInTheDocument();
  });

  it("ask For whom? when a letter names two people, and one click picks", async () => {
    const { calls, user } = setup(<FromFor entry={entry({ people_found: ["Michiel", "Tiina"] })} />);
    const group = screen.getByRole("group", { name: "For whom?" });
    await user.click(within(group).getByRole("button", { name: "Tiina" }));
    await waitFor(() => expect(puts(calls)).toHaveLength(1));
    expect(puts(calls)[0].body).toEqual({ drive_ids: ["d1"], person: "Tiina" });
  });

  it("say Reading page 1… while the suggestion waits, and reload the inbox once it is read", async () => {
    const { calls } = setup(<FromFor entry={entry({ waiting_for_page1: true })} />, {
      "GET /api/files/d1/page1": { body: { read: true, lines: [], unavailable: null } },
    });
    expect(screen.getByText("Reading page 1…")).toBeInTheDocument();
    await waitFor(() => expect(calls.filter((c) => c.url === "/api/files/d1/page1")).toHaveLength(1));
    await waitFor(() => expect(calls.filter((c) => c.url === "/api/inbox").length).toBeGreaterThan(1));
  });

  it("keep reloading while the suggestion still waits after page 1 is read (a picture is made later)", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const { calls } = setup(<FromFor entry={entry({ waiting_for_page1: true })} />, {
        "GET /api/files/d1/page1": { body: { read: true, lines: [], unavailable: null } },
      });
      await waitFor(() => expect(calls.filter((c) => c.url === "/api/inbox").length).toBeGreaterThan(1));
      const before = calls.filter((c) => c.url === "/api/inbox").length;
      await vi.advanceTimersByTimeAsync(4500);
      await waitFor(() => expect(calls.filter((c) => c.url === "/api/inbox").length).toBeGreaterThan(before));
    } finally {
      vi.useRealTimers();
    }
  });

  it("say why page 1 cannot be read instead of Reading page 1…, and do not ask for it", () => {
    const { calls } = setup(<FromFor entry={entry({ page1_unavailable: "no OCR engine" })} />);
    expect(screen.getByText("Page 1 could not be read: no OCR engine.")).toBeInTheDocument();
    expect(screen.queryByText("Reading page 1…")).toBeNull();
    expect(calls.filter((c) => c.url.includes("page1"))).toHaveLength(0);
  });

  it("do not ask for page 1 when nothing waits", () => {
    const { calls } = setup(<FromFor entry={entry()} />);
    expect(calls.filter((c) => c.url.includes("page1"))).toHaveLength(0);
    expect(screen.queryByText("Reading page 1…")).toBeNull();
  });
});

describe("From and For for many documents", () => {
  it("set the person on all of them, and Clear is always offered", async () => {
    const onClose = () => {};
    const { calls, user } = setup(<AssignSheet kind="person" driveIds={["d1", "d2", "d3"]} onClose={onClose} />);
    const sheet = await screen.findByRole("dialog", { name: "For (3 documents)" });
    expect(within(sheet).getByText("Who is these 3 documents for?")).toBeInTheDocument();
    expect(within(sheet).getByRole("button", { name: "Clear" })).toBeInTheDocument();
    await user.click(await within(sheet).findByRole("button", { name: "Michiel" }));
    await user.click(within(sheet).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(puts(calls)).toHaveLength(1));
    expect(puts(calls)[0].body).toEqual({ drive_ids: ["d1", "d2", "d3"], person: "Michiel" });
  });

  it("send only the sender when From is set", async () => {
    const { calls, user } = setup(<AssignSheet kind="sender" driveIds={["d1", "d2"]} onClose={() => {}} />);
    const sheet = await screen.findByRole("dialog", { name: "From (2 documents)" });
    await user.type(within(sheet).getByLabelText("Sender"), "Pohjola");
    await user.click(within(sheet).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(puts(calls)).toHaveLength(1));
    expect(puts(calls)[0].body).toEqual({ drive_ids: ["d1", "d2"], sender: "Pohjola" });
  });

  it("say when there are no people yet", async () => {
    setup(<AssignSheet kind="person" driveIds={["d1"]} onClose={() => {}} />, {
      "GET /api/settings/people": { body: { ...PEOPLE, people: [] } },
    });
    expect(await screen.findByText("No people yet. Add them in Settings, under Filing rules.")).toBeInTheDocument();
  });
});
