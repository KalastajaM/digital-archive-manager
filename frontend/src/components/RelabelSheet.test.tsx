import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { mockFetch, renderWithProviders } from "../test-utils";
import { RelabelSheet, relabelSummary } from "./RelabelSheet";

const folder = { label: "Old", path: "/data/old", attached: true, connected: true, files: 3 };
const relabel = (dry: boolean) => ({
  label: "Old",
  new_label: "Taxes",
  counts: { files: 3, operations: 2 },
  files: [{ name: "rules.yaml" }],
  warnings: dry ? ["Open windows keep the old label until reload."] : [],
  restart_needed: false,
});

describe("RelabelSheet", () => {
  it("summarises what changes in plain words", () => {
    expect(relabelSummary(relabel(true) as never)).toBe(
      "Changes 3 index entries, 2 journal entries and 1 file (rules.yaml). Nothing on the disk changes.",
    );
  });

  it("previews first, then changes the label and reports it", async () => {
    const user = userEvent.setup();
    const onDone = vi.fn();
    const calls = mockFetch({
      "POST /api/archive-folders/Old/relabel": (call) => ({ body: relabel((call.body as { dry_run: boolean }).dry_run) }),
    });
    renderWithProviders(<RelabelSheet folder={folder} onClose={() => {}} onDone={onDone} />);
    const preview = screen.getByRole("button", { name: "Preview" });
    expect(preview).toBeDisabled();
    await user.type(screen.getByLabelText("New label"), "Taxes");
    await user.click(preview);
    expect(await screen.findByText(/^Changes 3 index entries/)).toBeInTheDocument();
    expect(screen.getByText("Open windows keep the old label until reload.")).toBeInTheDocument();
    expect(calls[0].body).toEqual({ label: "Taxes", dry_run: true });
    await user.click(screen.getByRole("button", { name: "Change label" }));
    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
    expect(calls[1].body).toEqual({ label: "Taxes", dry_run: false });
  });

  it("editing the label after a preview asks for a new preview", async () => {
    const user = userEvent.setup();
    mockFetch({ "POST /api/archive-folders/Old/relabel": { body: relabel(true) } });
    renderWithProviders(<RelabelSheet folder={folder} onClose={() => {}} onDone={() => {}} />);
    await user.type(screen.getByLabelText("New label"), "Taxes");
    await user.click(screen.getByRole("button", { name: "Preview" }));
    await screen.findByText(/^Changes 3 index entries/);
    await user.type(screen.getByLabelText("New label"), "2");
    expect(screen.getByRole("button", { name: "Preview" })).toBeInTheDocument();
    expect(screen.queryByText(/^Changes 3 index entries/)).not.toBeInTheDocument();
  });

  it("shows the server's refusal and stays open", async () => {
    const user = userEvent.setup();
    const onDone = vi.fn();
    mockFetch({ "POST /api/archive-folders/Old/relabel": { status: 409, body: { error: "that label is taken" } } });
    renderWithProviders(<RelabelSheet folder={folder} onClose={() => {}} onDone={onDone} />);
    await user.type(screen.getByLabelText("New label"), "Taxes");
    await user.click(screen.getByRole("button", { name: "Preview" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("that label is taken");
    expect(onDone).not.toHaveBeenCalled();
  });
});
