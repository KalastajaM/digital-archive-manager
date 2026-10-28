/** Quick Look in compare mode (Relatives): the subject beside the shown file, what they
 * share, and the verdict keys. Without ``compare`` nothing changes. */
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockFetch, renderWithProviders } from "../test-utils";
import { type QLFile, QuickLook } from "./QuickLook";

const file = (id: string, name: string): QLFile => ({ drive_id: id, name, path: `13. Taxes/${name}`, ext: "pdf" });
const FILES = [file("a", "a.pdf"), file("b", "b.pdf"), file("c", "c.pdf")];
const SUBJECT = file("s", "subject.pdf");

function setup(compare: boolean, index = 0, reason: ((f: QLFile) => string | null) | undefined = undefined) {
  mockFetch({});
  const onIndex = vi.fn();
  const onClose = vi.fn();
  const onNotRelated = vi.fn();
  renderWithProviders(
    <MemoryRouter>
      <QuickLook
        files={FILES}
        index={index}
        onIndex={onIndex}
        onClose={onClose}
        compare={compare ? { subject: SUBJECT, shared: (f) => [`Tag: Taxes (${f.name})`, "+ same month"], reason, onNotRelated } : undefined}
      />
    </MemoryRouter>,
  );
  return { onIndex, onClose, onNotRelated, user: userEvent.setup() };
}
const dialog = () => screen.getByRole("dialog", { name: /Quick Look/ });

afterEach(cleanup);

describe("compare mode", () => {
  it("shows this file beside the relative, with what they share and the verdict buttons", () => {
    setup(true);
    const d = dialog();
    expect(within(d).getByText("Is this related?")).toBeInTheDocument();
    expect(within(d).getByText("subject.pdf")).toBeInTheDocument();
    expect(within(d).getByText("a.pdf")).toBeInTheDocument();
    expect(within(d).getByRole("list", { name: "In common" })).toHaveTextContent("Tag: Taxes (a.pdf)");
    expect(within(d).getByRole("button", { name: /Not related/ })).toBeInTheDocument();
    expect(within(d).getByRole("button", { name: /Skip/ })).toBeInTheDocument();
    expect(within(d).getByRole("button", { name: /Related, next/ })).toBeInTheDocument();
  });

  it("puts an AI pick's reason on a line of its own, not among the In common labels", () => {
    setup(true, 0, (f) => (f.drive_id === "a" ? "the power of attorney this letter refers to" : null));
    const d = dialog();
    const line = within(d).getByText(/the power of attorney this letter refers to/);
    expect(line.closest(".quicklook-reason")).not.toBeNull();
    expect(within(d).getByRole("list", { name: "In common" })).not.toHaveTextContent("power of attorney");
    // a long label keeps its full text on hover
    expect(within(d).getByText("Tag: Taxes (a.pdf)")).toHaveAttribute("title", "Tag: Taxes (a.pdf)");
    cleanup();
    setup(true, 1, () => null);
    expect(document.querySelector(".quicklook-reason")).toBeNull();
  });

  it("N marks the shown file not related through the caller and does not move itself", () => {
    const { onNotRelated, onIndex } = setup(true, 1);
    fireEvent.keyDown(dialog(), { key: "n" });
    expect(onNotRelated).toHaveBeenCalledWith(FILES[1]);
    expect(onIndex).not.toHaveBeenCalled();
  });

  it("Y and the right arrow move on; Y on the last file closes; the left arrow steps back", () => {
    const first = setup(true, 0);
    fireEvent.keyDown(dialog(), { key: "y" });
    expect(first.onIndex).toHaveBeenCalledWith(1);
    fireEvent.keyDown(dialog(), { key: "ArrowRight" });
    expect(first.onIndex).toHaveBeenCalledTimes(2);
    cleanup();
    const mid = setup(true, 1);
    fireEvent.keyDown(dialog(), { key: "ArrowLeft" });
    expect(mid.onIndex).toHaveBeenCalledWith(0);
    cleanup();
    const last = setup(true, 2);
    fireEvent.keyDown(dialog(), { key: "y" });
    expect(last.onClose).toHaveBeenCalled();
  });

  it("zooms each pane on its own: + / - go to the pane last clicked, and Move together links them", async () => {
    const { user } = setup(true);
    // [this file, the relative], each pane's level ("Fit" or a percentage)
    const levels = async () => (await screen.findAllByTestId("zoom-level")).map((el) => el.textContent);
    expect(await levels()).toEqual(["Fit", "Fit"]);
    fireEvent.keyDown(dialog(), { key: "+" });
    expect(await levels()).toEqual(["Fit", "150%"]);
    const [subjectIn] = screen.getAllByRole("button", { name: "Zoom in" });
    await user.click(subjectIn);
    expect(await levels()).toEqual(["150%", "150%"]);
    fireEvent.keyDown(dialog(), { key: "+" }); // the subject pane was clicked last
    expect(await levels()).toEqual(["200%", "150%"]);
    const together = within(dialog()).getByRole("button", { name: /Move together/ });
    await user.click(together);
    expect(together).toHaveAttribute("aria-pressed", "true");
    expect(await levels()).toEqual(["200%", "200%"]); // both take the zoom of the pane in use
    fireEvent.keyDown(dialog(), { key: "-" });
    expect(await levels()).toEqual(["150%", "150%"]);
    await user.click(together);
    fireEvent.keyDown(dialog(), { key: "+" });
    expect(await levels()).toEqual(["200%", "150%"]); // apart again: the keys still go to the pane last clicked
  });

  it("Move together turns the pages of both, and apart each turns its own", async () => {
    const { user } = setup(true);
    const pages = async () => (await screen.findAllByText(/^Page \d/)).map((el) => el.textContent);
    expect(await pages()).toEqual(["Page 1", "Page 1"]);
    const [subjectNext, fileNext] = screen.getAllByRole("button", { name: "Next page" });
    await user.click(subjectNext);
    expect(await pages()).toEqual(["Page 2", "Page 1"]);
    await user.click(within(dialog()).getByRole("button", { name: /Move together/ }));
    // switched on: the relative comes to the page of the pane in use
    expect(await pages()).toEqual(["Page 2", "Page 2"]);
    await user.click(fileNext);
    expect(await pages()).toEqual(["Page 3", "Page 3"]);
    await user.click(within(dialog()).getByRole("button", { name: /Move together/ }));
    await user.click(fileNext);
    expect(await pages()).toEqual(["Page 3", "Page 4"]);
  });

  it("Space closes, but Space on a button presses that button", () => {
    const { onClose, onNotRelated } = setup(true);
    const button = within(dialog()).getByRole("button", { name: /Not related/ });
    fireEvent.keyDown(button, { key: " " });
    expect(onClose).not.toHaveBeenCalled();
    expect(onNotRelated).not.toHaveBeenCalled();
    fireEvent.keyDown(dialog(), { key: " " });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("the buttons do the same as the keys", async () => {
    const { user, onIndex, onNotRelated } = setup(true, 0);
    await user.click(within(dialog()).getByRole("button", { name: /Not related/ }));
    expect(onNotRelated).toHaveBeenCalledWith(FILES[0]);
    await user.click(within(dialog()).getByRole("button", { name: /Skip/ }));
    expect(onIndex).toHaveBeenCalledWith(1);
    await user.click(within(dialog()).getByRole("button", { name: /Related, next/ }));
    expect(onIndex).toHaveBeenCalledTimes(2);
  });
});

describe("without compare", () => {
  it("has no verdict keys, no second pane and its own title", () => {
    const { onIndex, onClose } = setup(false);
    const d = dialog();
    expect(within(d).getByRole("heading", { name: "a.pdf" })).toBeInTheDocument();
    expect(within(d).queryByText("Is this related?")).toBeNull();
    expect(within(d).queryByRole("button", { name: /Related, next/ })).toBeNull();
    fireEvent.keyDown(d, { key: "y" });
    fireEvent.keyDown(d, { key: "ArrowRight" });
    fireEvent.keyDown(d, { key: " " });
    expect(onIndex).not.toHaveBeenCalled(); // the host's own handler pages, not Quick Look
    expect(onClose).not.toHaveBeenCalled();
  });
});
