import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AIPrepared } from "../../api/client";
import { CONFIRM_KEY_DELAY_MS } from "../PlanPreview";
import { type Call, deferred, mockFetch, renderWithProviders } from "../../test-utils";
import { prepared, STATUS_ON } from "./testData";
import { ALREADY_SENT, useAISend } from "./useAI";

const posts = (calls: Call[], url: string) => calls.filter((c) => c.method === "POST" && c.url === url);

function Harness({ onResult }: { onResult: (data: Record<string, unknown>, cached: boolean) => void }) {
  const ai = useAISend<Record<string, unknown>>("suggest-filing", (data, info) => onResult(data, info.cached));
  return (
    <>
      <button type="button" onClick={() => ai.ask({ drive_id: "d1" })}>
        Ask AI
      </button>
      {ai.sheet}
    </>
  );
}

function setup(prep: AIPrepared | ((call: Call) => AIPrepared), run: unknown = { data: { ok: 1 }, cost_eur: 0.001, cached: false }) {
  const onResult = vi.fn();
  const calls = mockFetch({
    "GET /api/ai/status": { body: STATUS_ON },
    "POST /api/ai/suggest-filing/prepare": (call) => ({ body: typeof prep === "function" ? prep(call) : prep }),
    "POST /api/ai/suggest-filing/run": typeof run === "function" ? (run as () => { body: unknown }) : { body: run },
  });
  renderWithProviders(<Harness onResult={onResult} />);
  return { calls, onResult };
}

async function openSheet() {
  await userEvent.click(screen.getByRole("button", { name: "Ask AI" }));
  return screen.findByRole("dialog", { name: "What will be sent" });
}

afterEach(() => {
  vi.restoreAllMocks();
  fireEvent.keyUp(window, { key: "Meta" });
});

describe("SendSheet", () => {
  it("shows the task, the model, the estimate, the month's spend and the exact payload (visible)", async () => {
    setup(prepared({ notes: ["Skipped x.pdf: in 50. Medical"] }));
    const dialog = await openSheet();
    const d = within(dialog);
    expect(d.getByText("Suggest filing")).toBeInTheDocument();
    expect(d.getByText("claude-haiku-5-5")).toBeInTheDocument();
    expect(d.getByText(/at most 0,0012 €/)).toBeInTheDocument();
    await waitFor(() => expect(d.getByText(/1,25 € of 5,00 € this month/)).toBeInTheDocument());
    expect(d.getByRole("meter", { name: "This month's AI spend" })).toHaveAttribute("aria-valuenow", "1.25");
    const payload = d.getByLabelText("Text that will be sent");
    expect(payload.tagName).toBe("PRE");
    expect(payload.textContent).toBe("Document text:\n<document>\nNorthpower Oy lasku⟨U+202E⟩ 84,20 €\n</document>");
    expect(d.getByText("Skipped x.pdf: in 50. Medical")).toBeInTheDocument();
    // Cancel has the focus, never Send
    expect(d.getByRole("button", { name: "Cancel" })).toHaveFocus();
  });

  it("Send runs exactly the prepared token, once, and hands the answer over", async () => {
    const { calls, onResult } = setup(prepared());
    const dialog = await openSheet();
    expect(posts(calls, "/api/ai/suggest-filing/prepare")[0].body).toEqual({ params: { drive_id: "d1" } });
    await userEvent.click(within(dialog).getByRole("button", { name: "Send" }));
    await waitFor(() => expect(onResult).toHaveBeenCalledWith({ ok: 1 }, false));
    expect(posts(calls, "/api/ai/suggest-filing/run").map((c) => c.body)).toEqual([{ token: "tok-1" }]);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("a double-click on Send sends once", async () => {
    const hold = deferred<{ body: unknown }>();
    const { calls, onResult } = setup(prepared(), () => hold.promise);
    const dialog = await openSheet();
    const send = within(dialog).getByRole("button", { name: "Send" });
    fireEvent.click(send);
    fireEvent.click(send);
    fireEvent.click(send);
    await waitFor(() => expect(posts(calls, "/api/ai/suggest-filing/run")).toHaveLength(1));
    await act(async () => hold.resolve({ body: { data: { ok: 1 }, cost_eur: 0, cached: false } }));
    await waitFor(() => expect(onResult).toHaveBeenCalledTimes(1));
    expect(posts(calls, "/api/ai/suggest-filing/run")).toHaveLength(1);
  });

  it("a double-click on Ask AI prepares once", async () => {
    const hold = deferred<AIPrepared>();
    const calls = mockFetch({
      "GET /api/ai/status": { body: STATUS_ON },
      "POST /api/ai/suggest-filing/prepare": async () => ({ body: await hold.promise }),
    });
    renderWithProviders(<Harness onResult={vi.fn()} />);
    const ask = screen.getByRole("button", { name: "Ask AI" });
    fireEvent.click(ask);
    fireEvent.click(ask);
    await waitFor(() => expect(posts(calls, "/api/ai/suggest-filing/prepare")).toHaveLength(1));
    fireEvent.click(ask);
    await act(async () => hold.resolve(prepared()));
    expect(await screen.findByRole("dialog", { name: "What will be sent" })).toBeInTheDocument();
    expect(posts(calls, "/api/ai/suggest-filing/prepare")).toHaveLength(1);
  });

  it("blocked: Send is disabled and the reason is shown", async () => {
    const { calls } = setup(prepared({ blocked: "in an excluded folder: 50. Medical", payload_text: "" }));
    const dialog = await openSheet();
    const d = within(dialog);
    expect(d.getByRole("button", { name: "Send" })).toBeDisabled();
    expect(d.getByText(/in an excluded folder: 50\. Medical/)).toBeInTheDocument();
    expect(d.getByText("Nothing will be sent.")).toBeInTheDocument();
    expect(d.getByText("nothing (not sent)")).toBeInTheDocument();
    fireEvent.keyDown(dialog, { key: "Enter", metaKey: true });
    expect(posts(calls, "/api/ai/suggest-filing/run")).toHaveLength(0);
  });

  it("Cmd+Enter sends only after the delay and a key release (ConfirmPlan arming)", async () => {
    const real = performance.now.bind(performance);
    let offset = 0;
    vi.spyOn(performance, "now").mockImplementation(() => real() + offset);
    const { calls } = setup(prepared());
    // a key is down while the sheet opens (the press that asked)
    fireEvent.keyDown(window, { key: "Meta", code: "MetaLeft" });
    fireEvent.click(screen.getByRole("button", { name: "Ask AI" }));
    const dialog = await screen.findByRole("dialog", { name: "What will be sent" });
    // too soon, and the key not yet released
    fireEvent.keyDown(dialog, { key: "Enter", metaKey: true });
    expect(posts(calls, "/api/ai/suggest-filing/run")).toHaveLength(0);
    offset = CONFIRM_KEY_DELAY_MS + 10;
    // long enough, but the key held since the sheet opened was never released
    fireEvent.keyDown(dialog, { key: "Enter", metaKey: true });
    expect(posts(calls, "/api/ai/suggest-filing/run")).toHaveLength(0);
    fireEvent.keyUp(dialog, { key: "Meta", code: "MetaLeft" });
    fireEvent.keyDown(dialog, { key: "Enter", metaKey: true });
    await waitFor(() => expect(posts(calls, "/api/ai/suggest-filing/run")).toHaveLength(1));
  });

  it("Esc cancels: nothing is sent", async () => {
    const { calls } = setup(prepared());
    const dialog = await openSheet();
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(posts(calls, "/api/ai/suggest-filing/run")).toHaveLength(0);
  });

  it("a cached result is shown at once, labelled from earlier; Ask again prepares with refresh", async () => {
    const { calls } = setup((call) =>
      (call.body as { params: Record<string, unknown> }).params.refresh
        ? prepared({ token: "tok-2" })
        : prepared({ cached: { summary: "A Northpower bill‮." }, estimate_eur: 0 }),
    );
    const dialog = await openSheet();
    const d = within(dialog);
    expect(d.getByText("from earlier")).toHaveClass("tag");
    expect(d.getByText("nothing (from earlier)")).toBeInTheDocument();
    expect(d.queryByLabelText("Text that will be sent")).not.toBeInTheDocument();
    expect(d.getByText(/A Northpower bill⟨U\+202E⟩\./)).toBeInTheDocument();
    expect(d.queryByRole("button", { name: "Send" })).not.toBeInTheDocument();
    await userEvent.click(d.getByRole("button", { name: "Ask again" }));
    await waitFor(() => expect(posts(calls, "/api/ai/suggest-filing/prepare")).toHaveLength(2));
    expect(posts(calls, "/api/ai/suggest-filing/prepare")[1].body).toEqual({ params: { drive_id: "d1", refresh: true } });
    const again = await screen.findByRole("dialog", { name: "What will be sent" });
    expect(within(again).getByRole("button", { name: "Send" })).toBeEnabled();
    expect(within(again).queryByText("from earlier")).not.toBeInTheDocument();
    expect(within(again).getByLabelText("Text that will be sent")).toBeInTheDocument();
  });

  it("Use this on a cached result runs its token (free) and hands it over", async () => {
    const { calls, onResult } = setup(prepared({ cached: { ok: 2 } }), { data: { ok: 2 }, cost_eur: 0, cached: true });
    const dialog = await openSheet();
    await userEvent.click(within(dialog).getByRole("button", { name: "Use this" }));
    await waitFor(() => expect(onResult).toHaveBeenCalledWith({ ok: 2 }, true));
    expect(posts(calls, "/api/ai/suggest-filing/run").map((c) => c.body)).toEqual([{ token: "tok-1" }]);
  });

  it("a refused run says why and offers Prepare again instead of Send", async () => {
    const onResult = vi.fn();
    let n = 0;
    const calls = mockFetch({
      "GET /api/ai/status": { body: STATUS_ON },
      "POST /api/ai/suggest-filing/prepare": () => ({ body: prepared({ token: `tok-${++n}` }) }),
      "POST /api/ai/suggest-filing/run": { status: 400, body: { error: "This has changed since the preview. Prepare it again." } },
    });
    renderWithProviders(<Harness onResult={onResult} />);
    const dialog = await openSheet();
    await userEvent.click(within(dialog).getByRole("button", { name: "Send" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("This has changed since the preview. Prepare it again.");
    expect(within(dialog).queryByRole("button", { name: "Send" })).not.toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Prepare again" }));
    await waitFor(() => expect(posts(calls, "/api/ai/suggest-filing/prepare")).toHaveLength(2));
    const again = await screen.findByRole("dialog", { name: "What will be sent" });
    expect(within(again).getByRole("button", { name: "Send" })).toBeEnabled();
    expect(onResult).not.toHaveBeenCalled();
  });
});

describe("SendSheet: closing and failed prepares", () => {
  it("while sending, Cancel reads Close (already sent); closing says the answer is saved", async () => {
    const hold = deferred<{ body: unknown }>();
    const { onResult } = setup(prepared(), () => hold.promise);
    const dialog = await openSheet();
    fireEvent.click(within(dialog).getByRole("button", { name: "Send" }));
    const close = await within(dialog).findByRole("button", { name: "Close (already sent)" });
    expect(within(dialog).getByText(/the answer is paid for/)).toBeInTheDocument();
    expect(within(dialog).getByText(/Press “Ask AI” again and choose “Use this”.*no extra cost/)).toBeInTheDocument();
    fireEvent.click(close);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(await screen.findByText(ALREADY_SENT)).toBeInTheDocument();
    // the late answer is dropped: the form is never filled behind the user's back
    await act(async () => hold.resolve({ body: { data: { ok: 1 }, cost_eur: 0.001, cached: false } }));
    expect(onResult).not.toHaveBeenCalled();
  });

  it("Esc while sending closes with the same toast", async () => {
    const hold = deferred<{ body: unknown }>();
    setup(prepared(), () => hold.promise);
    const dialog = await openSheet();
    fireEvent.click(within(dialog).getByRole("button", { name: "Send" }));
    await within(dialog).findByRole("button", { name: "Close (already sent)" });
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(await screen.findByText(ALREADY_SENT)).toBeInTheDocument();
    await act(async () => hold.resolve({ body: { data: {}, cost_eur: 0, cached: false } }));
  });

  it("a plain Cancel (nothing sent) shows no toast", async () => {
    setup(prepared());
    const dialog = await openSheet();
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByText(ALREADY_SENT)).not.toBeInTheDocument();
  });

  it("a failed Ask again leaves the result from earlier usable", async () => {
    const onResult = vi.fn();
    const calls = mockFetch({
      "GET /api/ai/status": { body: STATUS_ON },
      "POST /api/ai/suggest-filing/prepare": (call) =>
        (call.body as { params: Record<string, unknown> }).params.refresh
          ? { status: 409, body: { error: "AI is off: turn it on with dam ai --on" } }
          : { body: prepared({ cached: { ok: 3 } }) },
      "POST /api/ai/suggest-filing/run": { body: { data: { ok: 3 }, cost_eur: 0, cached: true } },
    });
    renderWithProviders(<Harness onResult={onResult} />);
    const dialog = await openSheet();
    await userEvent.click(within(dialog).getByRole("button", { name: "Ask again" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("AI is off");
    expect(within(dialog).queryByRole("button", { name: "Prepare again" })).not.toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Use this" }));
    await waitFor(() => expect(onResult).toHaveBeenCalledWith({ ok: 3 }, true));
    expect(posts(calls, "/api/ai/suggest-filing/run").map((c) => c.body)).toEqual([{ token: "tok-1" }]);
  });
});

describe("euro", () => {
  it("writes euros as the app writes money, small amounts with four decimals", async () => {
    const { euro } = await import("./SendSheet");
    expect(euro(0)).toBe("0,00 €");
    expect(euro(5)).toBe("5,00 €");
    expect(euro(1.25)).toBe("1,25 €");
    expect(euro(0.0012)).toBe("0,0012 €");
    expect(euro(0.00002)).toBe("< 0,0001 €");
  });
});

const TIMEOUT_TEXT =
  "Claude didn't answer within 2 minutes, so the app stopped waiting. Nothing was changed. Try again. Up to 0,0024 € is counted this month in case it was charged.";

describe("SendSheet: waiting for Claude", () => {
  afterEach(() => vi.useRealTimers());

  it("states the limit before sending", async () => {
    setup(prepared({ timeout_s: 120 }));
    const dialog = await openSheet();
    expect(within(dialog).getByText("Gives up after")).toBeInTheDocument();
    expect(within(dialog).getByText("2 min")).toBeInTheDocument();
  });

  it("shows a live status while the call runs: seconds tick, the limit is stated, a calm line follows", async () => {
    const hold = deferred<{ body: unknown }>();
    setup(prepared({ timeout_s: 140 }), () => hold.promise);
    const dialog = await openSheet();
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    fireEvent.click(within(dialog).getByRole("button", { name: "Send" }));
    const status = await within(dialog).findByRole("status");
    expect(status).toHaveTextContent("Waiting for Claude (claude-haiku-5-5)… 0 s");
    expect(status).toHaveTextContent("gives up after 2 min 20 s");
    expect(status).not.toHaveTextContent("not stuck");
    const send = within(dialog).getByRole("button", { name: "Waiting for Claude…" });
    expect(send).toBeDisabled();
    act(() => void vi.advanceTimersByTime(3000));
    expect(status).toHaveTextContent("… 3 s");
    act(() => void vi.advanceTimersByTime(9000));
    expect(status).toHaveTextContent("… 12 s");
    expect(status).toHaveTextContent("Larger requests can take a minute; the app is not stuck.");
    act(() => void vi.advanceTimersByTime(60_000));
    expect(status).toHaveTextContent("… 1 min 12 s");
    vi.useRealTimers();
    await act(async () => hold.resolve({ body: { data: { ok: 1 }, cost_eur: 0, cached: false } }));
  });

  it("a timeout reads in plain words, without a status name", async () => {
    setup(prepared(), () => ({ status: 409, body: { error: TIMEOUT_TEXT } }) as { body: unknown });
    const dialog = await openSheet();
    await userEvent.click(within(dialog).getByRole("button", { name: "Send" }));
    const alert = await within(dialog).findByRole("alert");
    expect(alert).toHaveTextContent(TIMEOUT_TEXT);
    expect(alert.textContent).not.toMatch(/Conflict|409|Error/);
    // the status line is gone once the call has ended
    expect(within(dialog).queryByText(/Waiting for Claude \(/)).not.toBeInTheDocument();
  });
});
