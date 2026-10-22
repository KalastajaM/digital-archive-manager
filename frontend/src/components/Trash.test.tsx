import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { useKeydown } from "../keyboard";
import { type Call, IMPORTANT_REFUSED, mockFetch, quarantineRoute, renderWithProviders, undoButton } from "../test-utils";
import { isTrashKey, TrashButton, useTrash } from "./Trash";

const FILES = { a: "10. Financial/a.pdf", b: "10. Financial/b.pdf" };
const quarantines = (calls: Call[]) => calls.filter((c) => c.method === "POST" && c.url === "/api/quarantine");

function Harness({ ids, onTrashed }: { ids: string[]; onTrashed?: (ids: string[]) => void }) {
  const trash = useTrash({ onTrashed });
  useKeydown((e) => {
    if (!isTrashKey(e)) return;
    e.preventDefault();
    trash.start(ids);
  });
  return (
    <div>
      <input aria-label="Name" />
      <TrashButton count={ids.length > 1 ? ids.length : undefined} disabled={trash.busy} onClick={() => trash.start(ids)} />
      {trash.view}
    </div>
  );
}

function setup(ids: string[], extra: Parameters<typeof mockFetch>[0] = {}) {
  const calls = mockFetch({ "POST /api/quarantine": quarantineRoute(FILES), ...extra });
  const trashed: string[][] = [];
  renderWithProviders(<Harness ids={ids} onTrashed={(t) => trashed.push(t)} />);
  return { calls, trashed, user: userEvent.setup() };
}

describe("Trash", () => {
  it("the bin button is named and tipped Move to To Delete, with the ⌘⌫ key", () => {
    setup(["a"]);
    const button = screen.getByRole("button", { name: "Move to To Delete" });
    expect(button).toHaveAttribute("data-tip", "Move to To Delete ⌘⌫");
  });

  it("previews, confirms and moves once however often clicked; Undo goes through the undo confirm", async () => {
    const { calls, trashed, user } = setup(["a"], {
      "POST /api/activity/q1/undo/preview": {
        body: [{ kind: "move", src: `##. To Delete/${FILES.a}`, dst: FILES.a, drive_id: "a", note: null }],
      },
      "POST /api/activity/q1/undo": { body: { batch_id: "u1", dry_run: false, done: [], failed: null, error: null, index_error: null } },
    });
    const button = screen.getByRole("button", { name: "Move to To Delete" });
    act(() => {
      button.click();
      button.click(); // in one tick: only the in-flight guard stops the second
    });
    const dialog = await screen.findByRole("dialog", { name: "Move to To Delete?" });
    expect(dialog).toHaveTextContent(`${FILES.a} → ##. To Delete/${FILES.a}`);
    expect(dialog).toHaveTextContent(/Nothing is deleted/);
    expect(quarantines(calls).map((c) => c.body)).toEqual([{ drive_ids: ["a"], dry_run: true }]);
    const apply = within(dialog).getByRole("button", { name: "Move to To Delete" });
    act(() => {
      apply.click();
      apply.click();
    });
    const undo = await screen.findByRole("button", { name: "Undo" });
    expect(quarantines(calls).map((c) => c.body)).toEqual([
      { drive_ids: ["a"], dry_run: true },
      { drive_ids: ["a"], dry_run: false },
    ]);
    expect(trashed).toEqual([["a"]]);
    expect(screen.getByText("Moved to To Delete: a.pdf")).toBeInTheDocument();

    await user.click(undo);
    const confirm = await screen.findByRole("dialog", { name: "Undo these changes?" });
    await waitFor(() => expect(confirm).toHaveTextContent(`##. To Delete/${FILES.a} → ${FILES.a}`));
    await user.click(await undoButton(confirm));
    await waitFor(() => expect(calls.filter((c) => c.url === "/api/activity/q1/undo")).toHaveLength(1));
  });

  it("⌘⌫ opens the same confirm; a plain ⌫ never trashes; ⌘⌫ while typing edits the text", async () => {
    const { calls, user } = setup(["a"]);
    await user.click(screen.getByLabelText("Name"));
    await user.keyboard("xy{Meta>}{Backspace}{/Meta}");
    expect(quarantines(calls)).toHaveLength(0);
    (document.activeElement as HTMLElement).blur();
    await user.keyboard("{Backspace}");
    fireEvent.keyDown(document.body, { key: "Delete" });
    await new Promise((r) => setTimeout(r, 10));
    expect(quarantines(calls)).toHaveLength(0);
    await user.keyboard("{Meta>}{Backspace}{/Meta}");
    await screen.findByRole("dialog", { name: "Move to To Delete?" });
    expect(quarantines(calls)).toHaveLength(1);
  });

  it("a selection goes in one batch", async () => {
    const { calls, user } = setup(["a", "b"]);
    await user.click(screen.getByRole("button", { name: "Move 2 to To Delete" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(/These 2 move into/);
    await user.click(within(dialog).getByRole("button", { name: "Move to To Delete" }));
    await screen.findByText("Moved to To Delete: a.pdf, b.pdf");
    expect(quarantines(calls).map((c) => c.body)).toEqual([
      { drive_ids: ["a", "b"], dry_run: true },
      { drive_ids: ["a", "b"], dry_run: false },
    ]);
  });

  it("a file marked Important is refused with the server's reason, and nothing moves", async () => {
    const { calls, trashed, user } = setup(["a"], { "POST /api/quarantine": IMPORTANT_REFUSED(FILES.a) });
    await user.click(screen.getByRole("button", { name: "Move to To Delete" }));
    expect(
      await screen.findByText(`Not moved to To Delete: This file is marked Important; unmark it first: ${FILES.a}`),
    ).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(quarantines(calls)).toHaveLength(1);
    expect(trashed).toEqual([]);
  });

  it("a protected path is refused in plain words", async () => {
    const { user } = setup(["a"], {
      "POST /api/quarantine": { status: 400, body: { error: "invalid request: 'X/a.pdf' is protected and cannot be quarantined" } },
    });
    await user.click(screen.getByRole("button", { name: "Move to To Delete" }));
    expect(await screen.findByText(/in a protected folder and cannot be moved to To Delete/)).toBeInTheDocument();
  });

  it("⌘⌫ with another modifier, held down, or under a dialog does nothing", async () => {
    const { calls } = setup(["a"]);
    fireEvent.keyDown(document.body, { key: "Backspace", metaKey: true, altKey: true });
    fireEvent.keyDown(document.body, { key: "Backspace", metaKey: true, shiftKey: true });
    fireEvent.keyDown(document.body, { key: "Backspace", metaKey: true, ctrlKey: true });
    fireEvent.keyDown(document.body, { key: "Backspace", metaKey: true, repeat: true });
    const dialog = document.createElement("dialog");
    document.body.append(dialog);
    dialog.showModal();
    fireEvent.keyDown(document.body, { key: "Backspace", metaKey: true });
    dialog.close();
    dialog.remove();
    await new Promise((r) => setTimeout(r, 10));
    expect(quarantines(calls)).toHaveLength(0);
  });
});
