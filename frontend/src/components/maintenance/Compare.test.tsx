import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { DupFile } from "../../api/client";
import { mockFetch, renderWithProviders } from "../../test-utils";
import { Compare } from "./Compare";

const file = (id: string, path: string, extra: Partial<DupFile> = {}): DupFile => ({
  drive_id: id,
  path,
  name: path.split("/").pop()!,
  size: 1024,
  mtime: 1_700_000_000,
  place: "numbered",
  locked: null,
  why: null,
  ...extra,
});
const two = [file("d1", "40. House/scan.pdf"), file("d2", "##. Inbox/scan.pdf", { mtime: 1_800_000_000 })];

function open(files = two, props: Partial<Parameters<typeof Compare>[0]> = {}) {
  mockFetch({});
  const onKeep = vi.fn();
  const onClose = vi.fn();
  renderWithProviders(<Compare name="scan.pdf" files={files} keep="d1" onKeep={onKeep} onClose={onClose} {...props} />);
  return { onKeep, onClose };
}

describe("Compare", () => {
  it("shows the kept file on the left and the other on the right, saying which is newer", () => {
    open();
    const left = screen.getByRole("region", { name: "Left" });
    const right = screen.getByRole("region", { name: "Right" });
    expect(within(left).getByText("Kept")).toBeInTheDocument();
    expect(within(left).getByText(/\(older\)/)).toBeInTheDocument();
    expect(within(right).getByText(/\(newer\)/)).toBeInTheDocument();
    expect(screen.getByText("2 files with this name")).toBeInTheDocument();
  });

  it("keeps the file on the right when asked", async () => {
    const user = userEvent.setup();
    const { onKeep } = open();
    await user.click(within(screen.getByRole("region", { name: "Right" })).getByRole("button", { name: "Keep this one" }));
    expect(onKeep).toHaveBeenCalledWith("d2");
  });

  it("closes with the button and with Esc", async () => {
    const user = userEvent.setup();
    const { onClose } = open();
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent(screen.getByRole("dialog", { hidden: true }), new Event("cancel", { cancelable: true }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("with more than two files each side has a menu, and the other side's file is not offered", () => {
    open([...two, file("d3", "50. Other/scan.pdf")]);
    const menu = screen.getByLabelText("File on the left") as HTMLSelectElement;
    expect(menu.value).toBe("d1");
    expect(within(menu).getByRole("option", { name: "##. Inbox/scan.pdf" })).toBeDisabled();
    expect(within(menu).getByRole("option", { name: "50. Other/scan.pdf" })).toBeEnabled();
  });
});
