import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../test-utils";
import { FileActionBar } from "./FileActionBar";

const run = () => vi.fn();
const names = () => within(screen.getByRole("toolbar", { name: "x" })).getAllByRole("button").map((b) => b.getAttribute("aria-label"));
const Host = ({ children }: { children: React.ReactNode }) => (
  <div role="toolbar" aria-label="x">
    {children}
  </div>
);

describe("FileActionBar", () => {
  it("draws every action in the one order, and the bin last", () => {
    renderWithProviders(
      <Host>
        <FileActionBar
          tray={{ label: "Put in tray", entries: [{ label: "To pay", onSelect: run() }] }}
          removeFromTray={{ run: run() }}
          backToInbox={{ run: run() }}
          moveTo={{ run: run(), shortcut: "⇧⌘M" }}
          sender={{ run: run() }}
          person={{ run: run() }}
          ask={{ run: run() }}
          star={{ on: false, run: run() }}
          important={{ on: false, run: run() }}
          restore={{ entries: [{ label: "Restore to where it was", onSelect: run() }] }}
          trash={{ run: run() }}
        />
      </Host>,
    );
    expect(names()).toEqual([
      "Put in tray",
      "Remove from tray",
      "Back to inbox",
      "Move to…",
      "From…",
      "For…",
      "Ask AI",
      "Star",
      "Mark Important",
      "Restore from To Delete",
      "Move to To Delete",
    ]);
  });

  it("shows only the actions a screen gives it, with the labels of a marked selection", () => {
    renderWithProviders(
      <Host>
        <FileActionBar
          tray={{ label: "Move to tray", entries: [] }}
          star={{ on: true, run: run() }}
          important={{ on: true, run: run() }}
          trash={{ run: run(), count: 3 }}
        />
      </Host>,
    );
    expect(names()).toEqual(["Move to tray", "Remove the star", "Unmark Important", "Move 3 to To Delete"]);
  });

  it("a disabled action keeps its reason as the tooltip, and does nothing when clicked", async () => {
    const user = userEvent.setup();
    const back = vi.fn();
    renderWithProviders(
      <Host>
        <FileActionBar
          tray={{ label: "Put in tray", entries: [], disabled: true, reason: "In To Delete: restore it first" }}
          backToInbox={{ run: back, reason: "Already in the inbox" }}
          ask={{ run: run(), disabled: true, reason: "AI is off: Activity → AI turns it on" }}
          star={{ on: false, run: run(), disabled: true }}
        />
      </Host>,
    );
    const tray = screen.getByRole("button", { name: "Put in tray" });
    expect(tray).toBeDisabled();
    expect(tray.parentElement).toHaveAttribute("data-tip", "In To Delete: restore it first");
    const inbox = screen.getByRole("button", { name: "Back to inbox" });
    expect(inbox).toBeDisabled();
    expect(inbox.parentElement).toHaveAttribute("data-tip", "Already in the inbox");
    await user.click(inbox);
    expect(back).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Ask AI" }).parentElement).toHaveAttribute("data-tip", "AI is off: Activity → AI turns it on");
    expect(screen.getByRole("button", { name: "Star" })).toBeDisabled();
  });

  it("the tray button opens a pull-down of the trays; picking one runs it", async () => {
    const user = userEvent.setup();
    const pick = vi.fn();
    renderWithProviders(
      <Host>
        <FileActionBar
          tray={{
            label: "Move to tray",
            entries: [
              { label: "To read", onSelect: pick },
              { label: "To action", onSelect: run() },
            ],
          }}
        />
      </Host>,
    );
    await user.click(screen.getByRole("button", { name: "Move to tray" }));
    const menu = await screen.findByRole("menu", { name: "Move to tray" });
    expect(within(menu).getAllByRole("menuitem").map((m) => m.textContent)).toEqual(["To read", "To action"]);
    await user.click(within(menu).getByRole("menuitem", { name: "To read" }));
    expect(pick).toHaveBeenCalledOnce();
  });
});
