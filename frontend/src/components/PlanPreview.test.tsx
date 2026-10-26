import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { visible } from "../text";
import { PlanList } from "./PlanPreview";

describe("visible", () => {
  it("marks bidi overrides, isolates, marks and C0 controls", () => {
    expect(visible("a‮fdp.exe")).toBe("a⟨U+202E⟩fdp.exe");
    expect(visible("⁦x⁩‎‏")).toBe("⟨U+2066⟩x⟨U+2069⟩⟨U+200E⟩⟨U+200F⟩");
    expect(visible("tab\there\nnul\u0000")).toBe("tab⟨U+0009⟩here⟨U+000A⟩nul⟨U+0000⟩");
    expect(visible("a\u061Cb\u007Fc\u0085d\u009Fe")).toBe(
      "a⟨U+061C⟩b⟨U+007F⟩c⟨U+0085⟩d⟨U+009F⟩e",
    );
    expect(visible("\u200B\u200C\u200D\u2060\uFEFF")).toBe(
      "⟨U+200B⟩⟨U+200C⟩⟨U+200D⟩⟨U+2060⟩⟨U+FEFF⟩",
    );
    expect(visible("Sähkö € 2026")).toBe("Sähkö € 2026");
  });

  it("is applied to plan paths", () => {
    render(
      <PlanList
        ops={[{ kind: "move", src: "##. Organize/in‮voice.pdf", dst: "X/a‮b.pdf", drive_id: "d", note: null }]}
      />,
    );
    expect(screen.getByText("##. Organize/in⟨U+202E⟩voice.pdf")).toBeInTheDocument();
    expect(screen.getByText("X/a⟨U+202E⟩b.pdf")).toBeInTheDocument();
  });
});

describe("PlanList picture ops", () => {
  it("shows the picture by its file name and where it goes back to by the rules folder", () => {
    render(
      <PlanList
        ops={[
          { kind: "picture_to_quarantine", src: "abs:/Users/me/config/rules/areas/old-1.png", dst: "##. To Delete/dam rule picture old-1.png", drive_id: null, note: null },
          { kind: "picture_back", src: "##. To Delete/dam rule picture old-1.png", dst: "abs:C:\\cfg\\rules\\areas\\old-1.png", drive_id: null, note: null },
        ]}
      />,
    );
    expect(screen.getByText("Move to To Delete")).toBeInTheDocument();
    expect(screen.getByText("Put back")).toBeInTheDocument();
    expect(screen.getByText("old-1.png")).toBeInTheDocument();
    expect(screen.getByText("rules/areas/old-1.png")).toBeInTheDocument();
    expect(screen.queryByText(/Users/)).not.toBeInTheDocument();
  });
});

describe("PlanList", () => {
  it("shows single-path ops (folders made or removed, links removed) with one path and no arrow", () => {
    const one = "##. Ongoing/C/New group";
    render(
      <PlanList
        ops={[
          { kind: "remove_empty_dir", src: one, dst: one, drive_id: null, note: null },
          { kind: "mkdir", src: null, dst: "##. Ongoing/C/Plans", drive_id: null, note: null },
          { kind: "unlink_symlink", src: "##. Ongoing/C/a.pdf", dst: "##. Ongoing/C/a.pdf", drive_id: null, note: null },
          { kind: "move", src: "a/x.pdf", dst: "b/x.pdf", drive_id: null, note: null },
        ]}
      />,
    );
    expect(screen.getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      `Remove empty folder${one}`,
      "New folder##. Ongoing/C/Plans",
      "Remove link##. Ongoing/C/a.pdf",
      "Movea/x.pdf → b/x.pdf",
    ]);
  });
});

describe("PlanList numbering", () => {
  const mk = (dst: string) => ({ kind: "mkdir" as const, src: null, dst, drive_id: null, note: null });

  it("shows a single step as plain text, with no list and so no lone '1.'", () => {
    const { container } = render(<PlanList ops={[mk("A/New")]} />);
    expect(screen.queryByRole("list")).toBeNull();
    expect(container.querySelector("ol")).toBeNull();
    expect(container.querySelector("p.plan-op")).toHaveTextContent("New folderA/New");
  });

  it("keeps the numbered list for two or more steps", () => {
    const { container } = render(<PlanList ops={[mk("A/One"), mk("A/Two")]} />);
    expect(container.querySelector("ol.plan")).not.toBeNull();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });
});

describe("PlanList paths and notes", () => {
  it("wraps paths only at / _ and spaces: a <wbr> after each, never inside a word", () => {
    const { container } = render(
      <PlanList ops={[{ kind: "mkdir", src: null, dst: "40. House/heal th_care/x.pdf", drive_id: null, note: null }]} />,
    );
    const code = container.querySelector("code")!;
    expect(code.textContent).toBe("40. House/heal th_care/x.pdf");
    expect(code.innerHTML).toBe("40. <wbr>House/<wbr>heal <wbr>th_<wbr>care/<wbr>x.pdf");
  });

  it("shows routine folder creation in the quiet style and keeps the warning style for real notes", () => {
    render(
      <PlanList
        ops={[
          { kind: "mkdir", src: null, dst: "40. New", drive_id: null, note: "create missing folder" },
          { kind: "move", src: "a.pdf", dst: "40. New/a_2.pdf", drive_id: "d", note: "renamed to avoid collision" },
        ]}
      />,
    );
    const [quiet, warn] = screen.getAllByRole("listitem");
    expect(quiet).not.toHaveClass("plan-noted");
    expect(quiet.querySelector(".plan-note")).toHaveClass("plan-note-routine");
    expect(warn).toHaveClass("plan-noted");
    expect(warn.querySelector(".plan-note")).not.toHaveClass("plan-note-routine");
  });

  it("shows missing folders made one inside the other as one line; a sibling or a folder of its own stays apart", () => {
    const made = (dst: string, note: string | null = "create missing folder") =>
      ({ kind: "mkdir", src: null, dst, drive_id: null, note }) as const;
    render(
      <PlanList
        ops={[
          made("##. To Delete/90. Other"),
          made("##. To Delete/90. Other/Tomas"),
          made("##. To Delete/90. Other/Tomas/Docs"),
          made("##. To Delete/10. Bank"),
          made("40. New", null),
          made("40. New/Sub", null),
          { kind: "quarantine", src: "90. Other/Tomas/Docs/p.pdf", dst: "##. To Delete/90. Other/Tomas/Docs/p.pdf", drive_id: "d", note: null },
        ]}
      />,
    );
    const lines = screen.getAllByRole("listitem").map((li) => li.textContent);
    expect(lines.slice(0, 4)).toEqual([
      "New folders##. To Delete/90. Other/Tomas/Docs (3 missing folders)",
      "New folder##. To Delete/10. Bank (create missing folder)",
      "New folder40. New",
      "New folder40. New/Sub",
    ]);
    expect(lines).toHaveLength(5);
  });

  it("collapses a link removed and made again at the same path into one plain line", () => {
    const at = "##. Ongoing/Tax 2025.pdf";
    render(
      <PlanList
        ops={[
          { kind: "unlink_symlink", src: at, dst: at, drive_id: null, note: null },
          { kind: "symlink", src: "13. Taxes/Tax 2025.pdf", dst: at, drive_id: null, note: null },
          { kind: "move", src: "a/x.pdf", dst: "b/x.pdf", drive_id: null, note: null },
        ]}
      />,
    );
    expect(screen.getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      `${at} stays; the app now manages this link`,
      "Movea/x.pdf → b/x.pdf",
    ]);
    expect(screen.queryByText("Remove link")).not.toBeInTheDocument();
  });

  it("de-emphasises the folder both ends of a move share, so the change stands out", () => {
    const { container } = render(
      <PlanList ops={[{ kind: "rename", src: "40. House/Sauna/a.pdf", dst: "40. House/Sauna/b.pdf", drive_id: "d", note: null }]} />,
    );
    const same = container.querySelectorAll(".plan-same");
    expect([...same].map((e) => e.textContent)).toEqual(["40. House/Sauna/", "40. House/Sauna/"]);
    expect(container.textContent).toBe("Rename40. House/Sauna/a.pdf → 40. House/Sauna/b.pdf");
  });

  it("the quarantine op reads as the one user-facing name", () => {
    render(<PlanList ops={[{ kind: "quarantine", src: "A/a.pdf", dst: "##. To Delete/A/a.pdf", drive_id: "d", note: null }]} />);
    expect(screen.getByText("Move to To Delete")).toBeInTheDocument();
    expect(screen.queryByText("Quarantine")).not.toBeInTheDocument();
  });
});

describe("toasts", () => {
  it("show hidden characters", async () => {
    const { ToastProvider, useToast } = await import("./Toasts");
    function Show() {
      const toast = useToast();
      return (
        <button type="button" onClick={() => toast({ kind: "info", text: "Filed as a‮b.pdf" })}>
          go
        </button>
      );
    }
    render(
      <ToastProvider>
        <Show />
      </ToastProvider>,
    );
    screen.getByRole("button", { name: "go" }).click();
    expect(await screen.findByText("Filed as a⟨U+202E⟩b.pdf")).toBeInTheDocument();
  });
});

describe("ConfirmPlan", () => {
  it("only a removal's confirm button is red", async () => {
    const { ConfirmPlan } = await import("./PlanPreview");
    const { rerender } = render(<ConfirmPlan planKey="a" ops={[]} confirmLabel="Move" onConfirm={() => {}} onCancel={() => {}} />);
    expect(screen.getByRole("button", { name: /^Move/ })).not.toHaveClass("danger");
    rerender(<ConfirmPlan planKey="a" ops={[]} confirmLabel="Remove group" danger onConfirm={() => {}} onCancel={() => {}} />);
    expect(screen.getByRole("button", { name: /^Remove group/ })).toHaveClass("primary", "danger");
  });

  it("a new plan in the open dialog starts the keyboard delay again", async () => {
    const { ConfirmPlan, CONFIRM_KEY_DELAY_MS } = await import("./PlanPreview");
    const real = performance.now.bind(performance);
    let offset = 0;
    vi.spyOn(performance, "now").mockImplementation(() => real() + offset);
    const onConfirm = vi.fn();
    const op = (dst: string) => ({ kind: "move" as const, src: "a.pdf", dst, drive_id: "d", note: null });
    const { rerender } = render(
      <ConfirmPlan planKey="p1" ops={[op("X/a.pdf")]} onConfirm={onConfirm} onCancel={() => {}} />,
    );
    offset += CONFIRM_KEY_DELAY_MS + 100;
    rerender(
      <ConfirmPlan planKey="p2" ops={[op("Y/a.pdf")]} onConfirm={onConfirm} onCancel={() => {}} />,
    );
    expect(screen.getByText("Y/a.pdf")).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("button", { name: "Cancel" }), { key: "Enter", metaKey: true });
    expect(onConfirm).not.toHaveBeenCalled();
    offset += CONFIRM_KEY_DELAY_MS + 100;
    fireEvent.keyDown(screen.getByRole("button", { name: "Cancel" }), { key: "Enter", metaKey: true });
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("plain Return on the focused Cancel does nothing; the primary button shows ⌘↩", async () => {
    const { ConfirmPlan } = await import("./PlanPreview");
    const onCancel = vi.fn();
    const onConfirm = vi.fn();
    const op = { kind: "move" as const, src: "a.pdf", dst: "X/a.pdf", drive_id: "d", note: null };
    render(<ConfirmPlan planKey="p1" ops={[op]} onConfirm={onConfirm} onCancel={onCancel} />);
    const cancel = screen.getByRole("button", { name: "Cancel" });
    expect(cancel).toHaveFocus();
    expect(fireEvent.keyDown(cancel, { key: "Enter" })).toBe(false); // the click is prevented
    expect(onCancel).not.toHaveBeenCalled();
    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Confirm" })).toHaveTextContent("Confirm⌘↩");
  });

  it("a key held when it opens blocks Cmd+Enter until a key is released; Cancel has the focus", async () => {
    const { ConfirmPlan, CONFIRM_KEY_DELAY_MS } = await import("./PlanPreview");
    const real = performance.now.bind(performance);
    let offset = 0;
    vi.spyOn(performance, "now").mockImplementation(() => real() + offset);
    const onConfirm = vi.fn();
    const op = { kind: "move" as const, src: "a.pdf", dst: "X/a.pdf", drive_id: "d", note: null };
    // the Cmd+Enter that opened the dialog is still held
    fireEvent.keyDown(window, { key: "Meta", code: "MetaLeft" });
    render(<ConfirmPlan planKey="held" ops={[op]} onConfirm={onConfirm} onCancel={() => {}} />);
    const cancel = screen.getByRole("button", { name: "Cancel" });
    expect(cancel).toHaveFocus();
    offset += CONFIRM_KEY_DELAY_MS + 100;
    fireEvent.keyDown(cancel, { key: "Enter", metaKey: true });
    expect(onConfirm).not.toHaveBeenCalled(); // long enough, but never released
    fireEvent.keyUp(cancel, { key: "Meta", code: "MetaLeft" });
    fireEvent.keyDown(cancel, { key: "Enter", metaKey: true, repeat: true });
    expect(onConfirm).not.toHaveBeenCalled(); // an auto-repeat never confirms
    fireEvent.keyDown(cancel, { key: "Enter", metaKey: true });
    expect(onConfirm).toHaveBeenCalledTimes(1);
    fireEvent.keyUp(window, { key: "Meta" });
  });

  it("with no key held at open, Cmd+Enter confirms once the delay has passed", async () => {
    const { ConfirmPlan, CONFIRM_KEY_DELAY_MS } = await import("./PlanPreview");
    const real = performance.now.bind(performance);
    let offset = 0;
    vi.spyOn(performance, "now").mockImplementation(() => real() + offset);
    const onConfirm = vi.fn();
    const op = { kind: "move" as const, src: "a.pdf", dst: "X/a.pdf", drive_id: "d", note: null };
    fireEvent.keyUp(window, { key: "Meta" }); // nothing held
    render(<ConfirmPlan planKey="free" ops={[op]} onConfirm={onConfirm} onCancel={() => {}} />);
    const cancel = screen.getByRole("button", { name: "Cancel" });
    fireEvent.keyDown(cancel, { key: "Enter", metaKey: true });
    expect(onConfirm).not.toHaveBeenCalled(); // too soon
    offset += CONFIRM_KEY_DELAY_MS + 100;
    fireEvent.keyDown(cancel, { key: "Enter", metaKey: true });
    expect(onConfirm).toHaveBeenCalledTimes(1);
    fireEvent.keyUp(window, { key: "Meta" });
  });

  it("snapshotKey is stable for equal requests and differs for different ones", async () => {
    const { snapshotKey } = await import("./PlanPreview");
    const a = [{ drive_id: "d1", name: "a.pdf", folder: "X", tags: [] }];
    expect(snapshotKey(a)).toBe(snapshotKey(structuredClone(a)));
    expect(snapshotKey(a)).not.toBe(snapshotKey([{ ...a[0], folder: "Y" }]));
  });
});

describe("a move across disks", () => {
  const op = (kind: "copy_across" | "quarantine" | "mkdir", src: string | null, dst: string, size?: number, cloud_only = false) => ({
    kind,
    src,
    dst,
    drive_id: null,
    note: null,
    size: size ?? null,
    cloud_only,
  });

  it("says how many files are copied, how big, where to, and where the originals go", () => {
    render(
      <PlanList
        ops={[
          op("mkdir", null, "Old years/2010"),
          op("copy_across", "Banks/a.pdf", "Old years/2010/a.pdf", 3 * 1024 * 1024),
          op("quarantine", "Banks/a.pdf", "##. To Delete/Banks/a.pdf"),
          op("copy_across", "Banks/b.pdf", "Old years/2010/b.pdf", 1024 * 1024, true),
          op("quarantine", "Banks/b.pdf", "##. To Delete/Banks/b.pdf"),
        ]}
      />,
    );
    expect(screen.getByText("Copies 2 files (4,0 MB) to another disk. The originals go to To Delete once each copy is checked.")).toBeInTheDocument();
    expect(screen.getByText("1 file is in the cloud only and is downloaded first.")).toBeInTheDocument();
    expect(screen.getAllByText("Copy to other disk")).toHaveLength(2);
  });

  it("says a restore across disks leaves the originals in To Delete", () => {
    render(
      <PlanList
        ops={[
          op("copy_across", "##. To Delete/Banks/a.pdf", "Old years/2010/a.pdf", 1024 * 1024),
          op("copy_across", "##. To Delete/Banks/b.pdf", "Old years/2010/b.pdf", 1024 * 1024),
        ]}
      />,
    );
    expect(screen.getByText("Copies 2 files (2,0 MB) to another disk. The originals stay in To Delete.")).toBeInTheDocument();
    expect(screen.queryByText(/go to To Delete/)).toBeNull();
  });

  it("says nothing extra for an ordinary move", () => {
    render(<PlanList ops={[{ kind: "move", src: "A/a.pdf", dst: "B/a.pdf", drive_id: "d", note: null }]} />);
    expect(screen.queryByText(/another disk/)).toBeNull();
  });
});
