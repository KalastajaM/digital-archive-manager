import { cleanup, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { mockFetch, renderWithProviders } from "../../test-utils";
import { Sidebar } from "./Sidebar";

const nav = () => screen.getByRole("navigation", { name: "Main" });

function setup() {
  mockFetch({
    "GET /api/status": { body: { inbox_count: 7 } },
    "GET /api/today": { body: { attention: [], overview: { inbox: 0, trays: [], collections: [] } } },
    "GET /api/trays": { body: { trays: [], errors: [] } },
    "GET /api/collections": { body: [] },
  });
  renderWithProviders(
    <MemoryRouter initialEntries={["/browse"]}>
      <Sidebar />
    </MemoryRouter>,
  );
}

afterEach(() => {
  cleanup();
  delete document.documentElement.dataset.style;
});

describe("Sidebar rows and the New look", () => {
  it("name themselves with a tooltip in New (the icon rail has no labels), with the count", async () => {
    document.documentElement.dataset.style = "new";
    setup();
    const inbox = await within(nav()).findByRole("link", { name: "Inbox (7)" });
    expect(inbox).toHaveAttribute("title", "Inbox (7)");
    expect(within(nav()).getByRole("link", { name: "Browse" })).toHaveAttribute("title", "Browse");
    expect(within(nav()).getByRole("link", { name: "Starred" })).toHaveAttribute("title", "Starred");
  });

  it("add no tooltip in Classic", async () => {
    setup();
    const inbox = await within(nav()).findByRole("link", { name: "Inbox (7)" });
    expect(inbox).not.toHaveAttribute("title");
    expect(within(nav()).getByRole("link", { name: "Browse" })).not.toHaveAttribute("title");
  });
});
