import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { type Call, deferred, mockFetch, renderWithProviders } from "../test-utils";
import { FilePreview } from "./FilePreview";

const pdf = { drive_id: "d1", path: "##. Organize/a.pdf", ext: "pdf" };
const jpg = { drive_id: "d2", path: "##. Organize/b.jpg", ext: "jpg" };

const page = () => screen.getByRole("img", { name: /page 1/i }) as HTMLImageElement;
const zoomLabel = () => screen.getByTestId("zoom-level").textContent;

describe("FilePreview zoom", () => {
  it("starts at fit with the 900 px render", () => {
    render(<FilePreview file={pdf} />);
    expect(zoomLabel()).toBe("Fit");
    expect(page().getAttribute("src")).toContain("w=900");
  });

  it("zooms in and out with the buttons and asks for sharper renders", () => {
    render(<FilePreview file={pdf} />);
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(zoomLabel()).toBe("150%");
    expect(page().style.width).toBe("150%");
    expect(page().getAttribute("src")).toContain("w=1400");
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(zoomLabel()).toBe("200%");
    expect(page().getAttribute("src")).toContain("w=2000");
    fireEvent.click(screen.getByRole("button", { name: "Fit" }));
    expect(zoomLabel()).toBe("Fit");
    fireEvent.click(screen.getByRole("button", { name: "Zoom out" }));
    expect(zoomLabel()).toBe("75%");
    expect(page().getAttribute("src")).toContain("w=900");
  });

  it("stops at the smallest and largest level", () => {
    render(<FilePreview file={pdf} />);
    const zoomIn = screen.getByRole("button", { name: "Zoom in" });
    for (let i = 0; i < 10; i++) fireEvent.click(zoomIn);
    expect(zoomLabel()).toBe("300%");
    expect(zoomIn).toBeDisabled();
    const zoomOut = screen.getByRole("button", { name: "Zoom out" });
    for (let i = 0; i < 10; i++) fireEvent.click(zoomOut);
    expect(zoomLabel()).toBe("50%");
    expect(zoomOut).toBeDisabled();
  });

  it("follows + - 0 keys, but not while typing", () => {
    render(
      <>
        <input aria-label="name" />
        <FilePreview file={pdf} />
      </>,
    );
    fireEvent.keyDown(document.body, { key: "+" });
    expect(zoomLabel()).toBe("150%");
    fireEvent.keyDown(document.body, { key: "=" });
    expect(zoomLabel()).toBe("200%");
    fireEvent.keyDown(document.body, { key: "-" });
    expect(zoomLabel()).toBe("150%");
    fireEvent.keyDown(document.body, { key: "0" });
    expect(zoomLabel()).toBe("Fit");
    const input = screen.getByRole("textbox", { name: "name" });
    input.focus();
    fireEvent.keyDown(input, { key: "+" });
    expect(zoomLabel()).toBe("Fit");
  });

  it("zooms images too", () => {
    render(<FilePreview file={jpg} />);
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    const img = screen.getByRole("img") as HTMLImageElement;
    expect(img.style.width).toBe("150%");
  });

  it("resets to fit for another file", () => {
    const { rerender } = render(<FilePreview file={pdf} />);
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    rerender(<FilePreview file={{ ...pdf, drive_id: "d3" }} />);
    expect(zoomLabel()).toBe("Fit");
  });

  it("zooms with Cmd/Ctrl + wheel (and pinch), but plain wheel only scrolls", () => {
    render(<FilePreview file={pdf} />);
    const frame = screen.getByTestId("zoom-frame");
    fireEvent.wheel(frame, { deltaY: -100 });
    expect(zoomLabel()).toBe("Fit");
    fireEvent.wheel(frame, { deltaY: -100, metaKey: true });
    expect(zoomLabel()).toBe("150%");
    fireEvent.wheel(frame, { deltaY: -100, ctrlKey: true }); // trackpad pinch
    expect(zoomLabel()).toBe("200%");
    fireEvent.wheel(frame, { deltaY: 100, ctrlKey: true });
    expect(zoomLabel()).toBe("150%");
  });

  it("takes small pinch deltas together before stepping", () => {
    render(<FilePreview file={pdf} />);
    const frame = screen.getByTestId("zoom-frame");
    fireEvent.wheel(frame, { deltaY: -10, ctrlKey: true });
    expect(zoomLabel()).toBe("Fit");
    for (let i = 0; i < 5; i++) fireEvent.wheel(frame, { deltaY: -10, ctrlKey: true });
    expect(zoomLabel()).toBe("150%");
  });

  it("pans a zoomed preview by dragging with the mouse", () => {
    render(<FilePreview file={pdf} />);
    const frame = screen.getByTestId("zoom-frame");
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    frame.scrollLeft = 200;
    frame.scrollTop = 200;
    fireEvent.mouseDown(frame, { button: 0, clientX: 300, clientY: 300 });
    expect(frame).toHaveClass("dragging");
    fireEvent.mouseMove(window, { clientX: 250, clientY: 220 });
    expect(frame.scrollLeft).toBe(250);
    expect(frame.scrollTop).toBe(280);
    fireEvent.mouseUp(window);
    expect(frame).not.toHaveClass("dragging");
    fireEvent.mouseMove(window, { clientX: 0, clientY: 0 });
    expect(frame.scrollLeft).toBe(250);
  });

  it("does not drag at fit or with another mouse button", () => {
    render(<FilePreview file={pdf} />);
    const frame = screen.getByTestId("zoom-frame");
    fireEvent.mouseDown(frame, { button: 0, clientX: 300, clientY: 300 });
    expect(frame).not.toHaveClass("dragging");
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    fireEvent.mouseDown(frame, { button: 2, clientX: 300, clientY: 300 });
    expect(frame).not.toHaveClass("dragging");
  });

  it("shows no zoom controls without a preview", () => {
    mockFetch({});
    render(<FilePreview file={{ drive_id: "d4", path: "x.docx", ext: "docx" }} />);
    expect(screen.queryByRole("button", { name: "Zoom in" })).toBeNull();
  });
});

describe("FilePreview drag cleanup", () => {
  it("stops listening when unmounted mid-drag", () => {
    const { unmount } = render(<FilePreview file={pdf} />);
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    const frame = screen.getByTestId("zoom-frame");
    fireEvent.mouseDown(frame, { button: 0, clientX: 10, clientY: 10 });
    const removed = vi.spyOn(window, "removeEventListener");
    unmount();
    expect(removed.mock.calls.map((c) => c[0])).toEqual(expect.arrayContaining(["mousemove", "mouseup"]));
    removed.mockRestore();
  });
});

describe("FilePreview fallback", () => {
  const txt = { drive_id: "t1", path: "##. Organize/notes.txt", ext: "txt" };
  const docx = { drive_id: "w1", path: "##. Organize/letter.docx", ext: "docx" };
  const opens = (calls: Call[], id: string, what = "open") =>
    calls.filter((c) => c.method === "POST" && c.url === `/api/files/${id}/${what}`);

  it("text-like files show the text preview (hidden characters marked, lines kept)", async () => {
    const calls = mockFetch({ "GET /api/files/t1/text": { body: { text: "line one\nbad ‮name\tx", truncated: true } } });
    renderWithProviders(<FilePreview file={txt} />);
    const text = await screen.findByTestId("text-preview");
    expect(text.textContent).toBe("line one\nbad ⟨U+202E⟩name\tx");
    expect(screen.getByText(/Only the start of the file is shown/)).toBeInTheDocument();
    expect(calls.some((c) => c.url.startsWith("/api/files/t1/thumb.png"))).toBe(false);
  });

  const THUMB = { body: "png bytes" };
  const thumbs = (calls: Call[], id: string) => calls.filter((c) => c.url.startsWith(`/api/files/${id}/thumb.png`));

  it("a text preview that fails falls back to the Quick Look thumbnail", async () => {
    const calls = mockFetch({
      "GET /api/files/t1/text": { status: 404, body: { error: "no text preview" } },
      "GET /api/files/t1/thumb.png": THUMB,
    });
    renderWithProviders(<FilePreview file={txt} />);
    const img = await screen.findByRole("img", { name: "Preview of notes.txt" });
    expect(img.getAttribute("src")).toMatch(/^blob:/);
    expect(thumbs(calls, "t1").map((c) => c.url)).toEqual(["/api/files/t1/thumb.png?width=1200"]);
  });

  it("other types show the Quick Look thumbnail, then 'No preview' when there is none", async () => {
    const calls = mockFetch({ "GET /api/files/w1/thumb.png": THUMB });
    renderWithProviders(<FilePreview file={docx} />);
    const img = await screen.findByRole("img", { name: "Preview of letter.docx" });
    expect(thumbs(calls, "w1")).toHaveLength(1);
    fireEvent.error(img);
    expect(await screen.findByText("No preview")).toBeInTheDocument();
    expect(screen.getByText("##. Organize/letter.docx")).toBeInTheDocument(); // the Finder hint stays
  });

  it("a double click on the No preview path selects it instead of opening the file", async () => {
    const calls = mockFetch({ "POST /api/files/w1/open": { status: 204, body: null } });
    const user = userEvent.setup();
    renderWithProviders(<FilePreview file={docx} />);
    await user.dblClick(await screen.findByText("##. Organize/letter.docx"));
    expect(opens(calls, "w1")).toHaveLength(0);
  });

  it("shows 'Loading preview…' until the page has arrived", async () => {
    mockFetch({});
    renderWithProviders(<FilePreview file={pdf} />);
    expect(screen.getByText("Loading preview…")).toBeInTheDocument();
    expect(page()).toHaveClass("loading"); // not drawn before it has loaded
    fireEvent.load(page());
    expect(screen.queryByText("Loading preview…")).toBeNull();
    expect(page()).not.toHaveClass("loading");
  });

  it("a page that fails (404) goes on to the thumbnail, with a loading state, then 'No preview'", async () => {
    mockFetch({});
    renderWithProviders(<FilePreview file={pdf} />);
    fireEvent.error(page());
    expect(screen.getByText("Loading preview…")).toBeInTheDocument(); // the thumbnail's wait
    expect(await screen.findByText("No preview")).toBeInTheDocument();
    expect(screen.queryByText("Loading preview…")).toBeNull();
  });

  it("a thumbnail answered 404 moves on to 'No preview'", async () => {
    mockFetch({});
    renderWithProviders(<FilePreview file={docx} />);
    expect(await screen.findByText("No preview")).toBeInTheDocument();
  });

  it("the thumbnail is asked for only once the selection has been still for 250 ms", async () => {
    const calls = mockFetch({ "GET /api/files/w1/thumb.png": THUMB, "GET /api/files/w2/thumb.png": THUMB });
    const other = { drive_id: "w2", path: "##. Organize/other.docx", ext: "docx" };
    const { rerender } = renderWithProviders(<FilePreview file={docx} />);
    expect(screen.queryByRole("img")).toBeNull();
    await act(async () => new Promise((r) => setTimeout(r, 100)));
    expect(thumbs(calls, "w1")).toHaveLength(0);
    rerender(<FilePreview file={other} />); // moved on before 250 ms
    await screen.findByRole("img", { name: "Preview of other.docx" });
    expect(thumbs(calls, "w1")).toHaveLength(0);
    expect(thumbs(calls, "w2")).toHaveLength(1);
  });

  it("a busy server says so and offers a retry", async () => {
    let busy = true;
    const calls = mockFetch({
      "GET /api/files/w1/thumb.png": () => (busy ? { status: 503, body: { error: "busy" } } : THUMB),
    });
    const user = userEvent.setup();
    renderWithProviders(<FilePreview file={docx} />);
    expect(await screen.findByText("Preview busy — try again")).toBeInTheDocument();
    expect(screen.queryByText("No preview")).toBeNull();
    busy = false;
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("img", { name: "Preview of letter.docx" })).toBeInTheDocument();
    expect(thumbs(calls, "w1")).toHaveLength(2);
  });

  it("every state shows Open and Show in Finder", async () => {
    mockFetch({ "GET /api/files/t1/text": { body: { text: "hi", truncated: false } } });
    const buttons = () => [
      screen.getByRole("button", { name: "Open" }),
      screen.getByRole("button", { name: "Show in Finder" }),
    ];
    const { unmount } = renderWithProviders(<FilePreview file={pdf} />);
    expect(buttons()).toHaveLength(2);
    unmount();
    const r2 = renderWithProviders(<FilePreview file={jpg} />);
    expect(buttons()).toHaveLength(2);
    r2.unmount();
    const r3 = renderWithProviders(<FilePreview file={txt} />);
    await screen.findByTestId("text-preview");
    expect(buttons()).toHaveLength(2);
    r3.unmount();
    renderWithProviders(<FilePreview file={docx} />);
    expect(buttons()).toHaveLength(2);
    await screen.findByText("No preview");
    expect(buttons()).toHaveLength(2);
  });

  it("Open and Show in Finder post for this file; a double click on 'No preview' opens it", async () => {
    const calls = mockFetch({
      "POST /api/files/w1/open": { status: 204, body: null },
      "POST /api/files/w1/reveal": { status: 204, body: null },
    });
    const user = userEvent.setup();
    renderWithProviders(<FilePreview file={docx} />);
    await user.click(screen.getByRole("button", { name: "Show in Finder" }));
    await waitFor(() => expect(opens(calls, "w1", "reveal")).toHaveLength(1));
    await user.click(screen.getByRole("button", { name: "Open" }));
    await waitFor(() => expect(opens(calls, "w1")).toHaveLength(1));
    await user.dblClick(await screen.findByText("No preview"));
    await waitFor(() => expect(opens(calls, "w1")).toHaveLength(2));
  });

  it("a refused open shows the server's reason as a toast", async () => {
    mockFetch({
      "POST /api/files/w1/open": {
        status: 409,
        body: { error: "Won't open apps or scripts from the archive — use Show in Finder" },
      },
      "POST /api/files/w1/reveal": { status: 404, body: { error: "letter.docx is not there any ‮more" } },
    });
    const user = userEvent.setup();
    renderWithProviders(<FilePreview file={docx} />);
    await user.click(screen.getByRole("button", { name: "Open" }));
    expect(
      await screen.findByText("Won't open apps or scripts from the archive — use Show in Finder"),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show in Finder" }));
    expect(
      await screen.findByText("Could not show it in Finder: letter.docx is not there any ⟨U+202E⟩more"),
    ).toBeInTheDocument();
  });

  it("a second click while opening sends nothing, and the button says why", async () => {
    const held = deferred<{ status: number; body: null }>();
    const calls = mockFetch({ "POST /api/files/w1/open": () => held.promise });
    renderWithProviders(<FilePreview file={docx} />);
    const open = () => screen.getByRole("button", { name: "Open" });
    const first = open();
    fireEvent.click(first);
    fireEvent.click(first); // same event batch: only the synchronous guard stops it
    await waitFor(() => expect(open()).toBeDisabled());
    expect(open().parentElement).toHaveAttribute("data-tip", "Still opening the last request");
    await act(async () => held.resolve({ status: 204, body: null }));
    expect(opens(calls, "w1")).toHaveLength(1);
    await waitFor(() => expect(open()).toBeEnabled());
  });
});

describe("FilePreview of a link", () => {
  const link = { drive_id: "l1", path: "##. Important/Houses/Hillside/deed", ext: null, is_link: true };
  const TARGET = "20. Home/Deeds/20010315_Kauppakirja_Hillside.pdf";
  const detail = (over: Record<string, unknown> = {}) => ({
    body: {
      record: { drive_id: "l1", path: link.path, is_link: true },
      tags: [],
      link_target_id: "t1",
      link_target_path: TARGET,
      link_target_inside: true,
      ...over,
    },
  });

  function Location() {
    const loc = useLocation();
    return <p data-testid="location">{loc.pathname + loc.search}</p>;
  }

  const renderLink = () =>
    renderWithProviders(
      <MemoryRouter initialEntries={["/inbox"]}>
        <FilePreview file={link} />
        <Routes>
          <Route path="*" element={<Location />} />
        </Routes>
      </MemoryRouter>,
    );

  it("gives the target's page the Draw a box tool when asked", async () => {
    mockFetch({ "GET /api/files/l1": detail() });
    renderWithProviders(
      <MemoryRouter>
        <FilePreview file={link} boxTool={{}} />
      </MemoryRouter>,
    );
    expect(await screen.findByRole("button", { name: "Draw a box" })).toBeInTheDocument();
  });

  it("says what it links to and previews the target (by the target's type)", async () => {
    mockFetch({ "GET /api/files/l1": detail() });
    renderLink();
    expect(await screen.findByText("Link to")).toBeInTheDocument();
    expect(screen.getByText(TARGET)).toBeInTheDocument();
    // the link has no extension; the target is a PDF: its pages, asked for by the link
    const img = await screen.findByRole("img", { name: /page 1/i });
    expect(img.getAttribute("src")).toContain("/api/files/l1/page/1.png");
  });

  it("Go to target opens Browse at the target's folder with the target selected", async () => {
    mockFetch({ "GET /api/files/l1": detail() });
    const user = userEvent.setup();
    renderLink();
    await user.click(await screen.findByRole("button", { name: "Go to target" }));
    const loc = new URL(screen.getByTestId("location").textContent!, "http://x");
    expect(loc.pathname).toBe("/browse");
    expect(loc.searchParams.get("path")).toBe("20. Home/Deeds");
    expect(loc.searchParams.get("select")).toBe("t1");
  });

  it("a target outside the archive: no preview, only Show in Finder (for the link)", async () => {
    const calls = mockFetch({
      "GET /api/files/l1": detail({ link_target_id: null, link_target_path: "/Users/x/secret‮fdp.exe", link_target_inside: false }),
      "POST /api/files/l1/reveal": { status: 204, body: null },
    });
    const user = userEvent.setup();
    renderLink();
    expect(await screen.findByText("No preview (the link points outside the archive or to nothing)")).toBeInTheDocument();
    expect(screen.getByText("/Users/x/secret⟨U+202E⟩fdp.exe")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Go to target" })).toBeNull();
    expect(screen.queryByRole("img")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Show in Finder" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "POST").map((c) => c.url)).toEqual(["/api/files/l1/reveal"]));
    expect(calls.some((c) => c.url.includes("/page/") || c.url.includes("thumb") || c.url.includes("/text"))).toBe(false);
  });

  it("marks hidden characters in the target path", async () => {
    mockFetch({ "GET /api/files/l1": detail({ link_target_path: "20. Home/a‮fdp.exe.pdf" }) });
    renderLink();
    expect(await screen.findByText("20. Home/a⟨U+202E⟩fdp.exe.pdf")).toBeInTheDocument();
  });

  it("a detail that fails to load shows only the error", async () => {
    mockFetch({ "GET /api/files/l1": { status: 500, body: { error: "database is ‮locked" } } });
    renderLink();
    expect(await screen.findByText(/database is ⟨U\+202E⟩locked/)).toBeInTheDocument();
    expect(screen.queryByText(/outside the archive/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Show in Finder" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Go to target" })).toBeNull();
  });

  it("goToTarget={false} (the viewer window) shows the link without the button", async () => {
    mockFetch({ "GET /api/files/l1": detail() });
    renderWithProviders(
      <MemoryRouter>
        <FilePreview file={link} goToTarget={false} />
      </MemoryRouter>,
    );
    expect(await screen.findByText(TARGET)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Go to target" })).toBeNull();
  });

  it("beforeGoToTarget runs before the navigation (Quick Look closes first)", async () => {
    mockFetch({ "GET /api/files/l1": detail() });
    const order: string[] = [];
    function Probe() {
      const loc = useLocation();
      if (loc.pathname === "/browse") order.push("navigated");
      return null;
    }
    const user = userEvent.setup();
    renderWithProviders(
      <MemoryRouter initialEntries={["/inbox"]}>
        <FilePreview file={link} beforeGoToTarget={() => order.push("closed")} />
        <Routes>
          <Route path="*" element={<Probe />} />
        </Routes>
      </MemoryRouter>,
    );
    await user.click(await screen.findByRole("button", { name: "Go to target" }));
    expect(order[0]).toBe("closed");
    expect(order).toContain("navigated");
  });
});

describe("FilePreview print", () => {
  const sheetImages = () => [...document.querySelectorAll<HTMLImageElement>("body > .print-sheet img")];
  /** Waits for sheet image ``n`` (1-based) and lets it load, or fail. */
  const answer = async (n: number, ok: boolean) => {
    await waitFor(() => expect(sheetImages()).toHaveLength(n));
    fireEvent(sheetImages()[n - 1], new Event(ok ? "load" : "error"));
  };

  it("prints every page of a PDF, sharp, and clears the sheet after printing", async () => {
    const print = vi.spyOn(window, "print").mockImplementation(() => {});
    renderWithProviders(<FilePreview file={pdf} />);
    fireEvent.click(screen.getByRole("button", { name: "Print" }));
    await answer(1, true);
    await answer(2, true);
    await answer(3, false); // past the last page
    await waitFor(() => expect(print).toHaveBeenCalledTimes(1));
    expect(sheetImages().map((i) => i.getAttribute("src"))).toEqual([
      "/api/files/d1/page/1.png?w=2000",
      "/api/files/d1/page/2.png?w=2000",
    ]);
    fireEvent(window, new Event("afterprint"));
    expect(document.querySelector(".print-sheet")).toBeNull();
    await waitFor(() => expect(screen.getByRole("button", { name: "Print" })).toBeEnabled());
    print.mockRestore();
  });

  it("prints an image as it is", async () => {
    const print = vi.spyOn(window, "print").mockImplementation(() => {});
    renderWithProviders(<FilePreview file={jpg} />);
    fireEvent.click(screen.getByRole("button", { name: "Print" }));
    await answer(1, true);
    await waitFor(() => expect(print).toHaveBeenCalledTimes(1));
    expect(sheetImages().map((i) => i.getAttribute("src"))).toEqual(["/api/files/d2/raw"]);
    fireEvent(window, new Event("afterprint"));
    print.mockRestore();
  });

  it("says so when nothing could be loaded, and prints nothing", async () => {
    const print = vi.spyOn(window, "print").mockImplementation(() => {});
    renderWithProviders(<FilePreview file={pdf} />);
    fireEvent.click(screen.getByRole("button", { name: "Print" }));
    await answer(1, false);
    expect(await screen.findByText("Could not print: the preview did not load")).toBeInTheDocument();
    expect(print).not.toHaveBeenCalled();
    expect(document.querySelector(".print-sheet")).toBeNull();
    print.mockRestore();
  });
});
