import { focusManager } from "@tanstack/react-query";
import { act, cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ItemBarcode } from "../api/client";
import { type Call, deferred, mockFetch, renderWithProviders } from "../test-utils";
import { Barcode, BAR_HEIGHT, FULL_MODULE_PX, MIN_MODULE_PX, MODULE_PX, QUIET_MODULES } from "./Barcode";

const CODE = "421123456000007850000842000000000000000000005390075426";
// bar, space, bar, …: bars of 2, 1, 3 and 2 modules (bar first and last)
const MODULES = [2, 1, 1, 2, 3, 1, 2];

const OK: ItemBarcode = {
  code: CODE,
  modules: MODULES,
  reason: null,
  printed: null,
  printed_fields: null,
  mismatch: [],
};

function renderBarcode(reply: ItemBarcode | ((call: Call) => Promise<{ body: unknown }>), extra = {}) {
  const calls = mockFetch({
    "GET /api/items/7/barcode": typeof reply === "function" ? reply : { body: reply },
    ...extra,
  });
  const user = userEvent.setup();
  renderWithProviders(<Barcode itemId={7} />);
  return { calls, user };
}

const svg = () => screen.getByRole("img", { name: /^Bank barcode/ });

describe("Barcode", () => {
  it("draws one rect per bar, 60 px high, at least 2 px a module, with 10-module quiet zones", async () => {
    renderBarcode(OK);
    await screen.findByRole("img", { name: /^Bank barcode/ });
    const rects = [...svg().querySelectorAll("rect")];
    expect(rects).toHaveLength(4); // the bars only: the white paper is the background
    expect(MODULE_PX).toBeGreaterThanOrEqual(2);
    expect(BAR_HEIGHT).toBe(60);
    expect(QUIET_MODULES).toBe(10);
    const total = MODULES.reduce((a, b) => a + b, 0) + 2 * QUIET_MODULES;
    expect(svg()).toHaveAttribute("width", String(total * MODULE_PX));
    expect(svg()).toHaveAttribute("height", "60");
    const geometry = rects.map((r) => [r.getAttribute("x"), r.getAttribute("width"), r.getAttribute("height")]);
    const q = QUIET_MODULES;
    const m = MODULE_PX;
    expect(geometry).toEqual([
      [String(q * m), String(2 * m), "60"],
      [String((q + 3) * m), String(1 * m), "60"],
      [String((q + 6) * m), String(3 * m), "60"],
      [String((q + 10) * m), String(2 * m), "60"],
    ]);
  });

  it("shows the 54 digits in monospace and copies them", async () => {
    const { user } = renderBarcode(OK);
    const code = await screen.findByText(CODE);
    expect(code.tagName).toBe("CODE");
    await user.click(screen.getByRole("button", { name: "Copy barcode number" }));
    expect(await navigator.clipboard.readText()).toBe(CODE);
  });

  it("a reason hides the SVG and is said in one line", async () => {
    renderBarcode({ ...OK, code: null, modules: null, reason: "the IBAN is not a Finnish (FI) account" });
    expect(await screen.findByText("No barcode: the IBAN is not a Finnish (FI) account")).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /^Bank barcode/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Copy barcode number" })).not.toBeInTheDocument();
  });

  it("a reason with hidden characters is shown visibly", async () => {
    renderBarcode({ ...OK, code: null, modules: null, reason: "no\u202EIBAN" });
    expect(await screen.findByText("No barcode: no⟨U+202E⟩IBAN")).toBeInTheDocument();
  });

  it("a mismatch names the fields with the printed values; the button patches just those, once", async () => {
    const slow = deferred<{ body: unknown }>();
    const { calls, user } = renderBarcode(
      {
        ...OK,
        printed: "4".padEnd(54, "0"),
        printed_fields: {
          iban: "FI7944052020036082",
          amount: "4883.15",
          reference: "868516259619897",
          due_date: "2010-06-12",
        },
        mismatch: ["amount", "due_date"],
      },
      { "PATCH /api/items/7": () => slow.promise },
    );
    const warning = await screen.findByRole("region", { name: "The printed barcode differs" });
    expect(warning).toHaveTextContent("amount (printed 4 883,15 €)");
    expect(warning).toHaveTextContent("due date (printed 12.6.2010)");
    expect(warning).not.toHaveTextContent("IBAN");
    const use = screen.getByRole("button", { name: "Use the printed barcode's values" });
    await user.dblClick(use);
    await waitFor(() => expect(calls.filter((c) => c.method === "PATCH")).toHaveLength(1));
    expect(calls.filter((c) => c.method === "PATCH")[0]).toMatchObject({
      url: "/api/items/7",
      body: { fields: { amount: "4883.15", due_date: "2010-06-12" } },
    });
    await act(async () => slow.resolve({ body: {} }));
    await user.click(use);
    await waitFor(() => expect(calls.filter((c) => c.method === "PATCH")).toHaveLength(2));
  });

  it("a failed patch is shown, and the button works again", async () => {
    const { user } = renderBarcode(
      {
        ...OK,
        printed: "4".padEnd(54, "0"),
        printed_fields: { iban: "FI7944052020036082", amount: null, reference: "868516259619897", due_date: null },
        mismatch: ["reference"],
      },
      { "PATCH /api/items/7": { status: 400, body: { error: "reference: not valid" } } },
    );
    await user.click(await screen.findByRole("button", { name: "Use the printed barcode's values" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("reference: not valid");
    expect(screen.getByRole("button", { name: "Use the printed barcode's values" })).toBeEnabled();
  });

  it("says so when the barcode cannot be loaded", async () => {
    mockFetch({ "GET /api/items/7/barcode": { status: 500, body: { error: "boom" } } });
    renderWithProviders(<Barcode itemId={7} />);
    expect(await screen.findByText(/Could not load the barcode/)).toBeInTheDocument();
  });

  describe("full size", () => {
    const full = () => screen.getByRole("dialog", { name: "Bank barcode" });

    it("a double click on the barcode opens it at 3 px a module, the full width, with the code; Esc closes", async () => {
      const { user } = renderBarcode(OK);
      await user.dblClick(await screen.findByRole("img", { name: /^Bank barcode/ }));
      const dialog = full();
      expect(FULL_MODULE_PX).toBe(3);
      const big = within(dialog).getByRole("img", { name: `Bank barcode ${CODE}` });
      const total = MODULES.reduce((a, b) => a + b, 0) + 2 * QUIET_MODULES;
      expect(big).toHaveAttribute("width", String(total * 3));
      const geometry = [...big.querySelectorAll("rect")].map((r) => [r.getAttribute("x"), r.getAttribute("width")]);
      const q = QUIET_MODULES;
      expect(geometry).toEqual([
        [String(q * 3), String(2 * 3)],
        [String((q + 3) * 3), String(1 * 3)],
        [String((q + 6) * 3), String(3 * 3)],
        [String((q + 10) * 3), String(2 * 3)],
      ]);
      expect(within(dialog).getByText(CODE).tagName).toBe("CODE");
      // the digits sit past the quiet zone the SVG draws (set from here, not repeated in CSS)
      expect(big.parentElement!.style.getPropertyValue("--quiet-zone")).toBe(`${QUIET_MODULES * 3}px`);
      // it scrolls sideways in a narrow window instead of scaling (that would break the modules)
      expect(big.closest(".barcode-full")).not.toBeNull();

      await user.keyboard("{Escape}");
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      // the small one stays as it was
      expect(svg()).toHaveAttribute("width", String(total * MODULE_PX));
      expect(svg().parentElement!.style.getPropertyValue("--quiet-zone")).toBe(`${QUIET_MODULES * MODULE_PX}px`);
    });

    it("stays open while the code is fetched again, with the last code and an Updating… label", async () => {
      const NEW = "4".padEnd(54, "1");
      const again = deferred<{ body: unknown }>();
      let n = 0;
      const { user } = renderBarcode(() => (++n === 1 ? Promise.resolve({ body: OK }) : again.promise));
      await user.click(await screen.findByRole("button", { name: /^Show large barcode/ }));
      const dialog = full();
      act(() => {
        focusManager.setFocused(false);
        focusManager.setFocused(true); // the window comes back: the barcode is fetched again
      });
      await waitFor(() => expect(n).toBe(2));
      expect(full()).toBe(dialog); // the same sheet, not closed and reopened
      expect(within(dialog).getByText("Updating…")).toBeInTheDocument();
      expect(within(dialog).getByText(CODE)).toBeInTheDocument();
      await act(async () => again.resolve({ body: { ...OK, code: NEW } }));
      await waitFor(() => expect(within(dialog).getByText(NEW)).toBeInTheDocument());
      expect(full()).toBe(dialog);
      expect(within(dialog).queryByText("Updating…")).not.toBeInTheDocument();
      focusManager.setFocused(undefined);
    });

    it("the labeled button opens it too, and Close closes it", async () => {
      const { user } = renderBarcode(OK);
      await user.click(await screen.findByRole("button", { name: /^Show large barcode/ }));
      expect(full()).toBeInTheDocument();
      await user.click(within(full()).getByRole("button", { name: "Close" }));
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  describe("scaling and Pay mode", () => {
    afterEach(() => vi.restoreAllMocks());
    const total = MODULES.reduce((a, b) => a + b, 0) + 2 * QUIET_MODULES;

    it("scales down to the pane while a phone can still read it, and no further", async () => {
      let width = 40; // the pane is narrower than the 2 px symbol (62 px)
      vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockImplementation(function (this: HTMLElement) {
        return this.classList.contains("barcode-drawn") ? width : 0;
      });
      renderBarcode(OK);
      await screen.findByRole("img", { name: /^Bank barcode/ });
      const px = 40 / total;
      expect(Number(svg().getAttribute("width"))).toBeCloseTo(total * px, 5);
      expect(svg().parentElement!.style.getPropertyValue("--quiet-zone")).toBe(`${QUIET_MODULES * px}px`);
      width = 10; // narrower than MIN_MODULE_PX allows: it stops shrinking (and scrolls)
      cleanup();
      renderBarcode(OK);
      await screen.findByRole("img", { name: /^Bank barcode/ });
      expect(Number(svg().getAttribute("width"))).toBeCloseTo(total * MIN_MODULE_PX, 5);
    });

    it("the hint is a labeled button; Pay mode shows the bill's values large, and copies the number", async () => {
      const pay = [
        { label: "Payee", value: "Northpower Oy" },
        { label: "Amount", value: "84,20 €" },
        { label: "Reference", value: "RF18 5390 0754 2" },
        { label: "IBAN", value: "FI21 1234 5600 0007 85" },
        { label: "Due date", value: "15.10.2026" },
      ];
      mockFetch({ "GET /api/items/7/barcode": { body: OK } });
      const user = userEvent.setup();
      renderWithProviders(<Barcode itemId={7} pay={pay} />);
      await user.click(await screen.findByRole("button", { name: /^Show large barcode/ }));
      const dialog = screen.getByRole("dialog", { name: "Bank barcode" });
      const facts = within(dialog).getByLabelText("Payment details");
      for (const f of pay) {
        expect(within(facts).getByText(f.label)).toBeInTheDocument();
        expect(within(facts).getByText(f.value)).toBeInTheDocument();
      }
      expect(within(dialog).getByRole("button", { name: "Copy barcode number" })).toBeInTheDocument();
    });

    it("b opens Pay mode (not while typing or with a dialog open)", async () => {
      mockFetch({ "GET /api/items/7/barcode": { body: OK } });
      const user = userEvent.setup();
      renderWithProviders(
        <>
          <input aria-label="Note" />
          <Barcode itemId={7} />
        </>,
      );
      await screen.findByRole("img", { name: /^Bank barcode/ });
      await user.click(screen.getByRole("textbox", { name: "Note" }));
      await user.keyboard("b");
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      await user.keyboard("{Escape}");
      (document.activeElement as HTMLElement).blur();
      await user.keyboard("b");
      expect(screen.getByRole("dialog", { name: "Bank barcode" })).toBeInTheDocument();
    });
  });

  describe("in a window too narrow for it", () => {
    afterEach(() => vi.restoreAllMocks());

    it("says to widen the window while the barcode overflows its box", async () => {
      const wide = function (this: HTMLElement) {
        return this.classList.contains("barcode-paper") ? 724 : 0;
      };
      vi.spyOn(HTMLElement.prototype, "scrollWidth", "get").mockImplementation(wide);
      vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockImplementation(function (this: HTMLElement) {
        return this.classList.contains("barcode-paper") ? 480 : 0;
      });
      renderBarcode(OK);
      expect(await screen.findByText("Too narrow to scan: widen the window or show the large barcode")).toBeInTheDocument();
    });

    it("says nothing when it fits", async () => {
      renderBarcode(OK);
      await screen.findByRole("img", { name: /^Bank barcode/ });
      expect(screen.queryByText("Too narrow to scan: widen the window or show the large barcode")).not.toBeInTheDocument();
    });
  });
});
