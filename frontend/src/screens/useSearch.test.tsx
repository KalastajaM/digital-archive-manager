import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SEARCH_DEBOUNCE_MS, useSearch } from "./useSearch";

afterEach(() => vi.unstubAllGlobals());

/** A fetch that answers [] for every search but only once told to, and records the signals. */
function slowFetch() {
  const signals: AbortSignal[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((_url: string, init: RequestInit) => {
      const signal = init.signal as AbortSignal;
      signals.push(signal);
      return new Promise((_resolve, reject) => {
        signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      });
    }),
  );
  return signals;
}

describe("useSearch", () => {
  it("aborts the previous request when the query changes, without an error", async () => {
    const signals = slowFetch();
    const { result, rerender } = renderHook(({ q }) => useSearch(q), { initialProps: { q: "kela" } });
    await waitFor(() => expect(signals).toHaveLength(1), { timeout: SEARCH_DEBOUNCE_MS * 4 });
    rerender({ q: "kela letter" });
    await waitFor(() => expect(signals).toHaveLength(2), { timeout: SEARCH_DEBOUNCE_MS * 4 });
    expect(signals[0].aborted).toBe(true);
    expect(signals[1].aborted).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("aborts on unmount and shows no error", async () => {
    const signals = slowFetch();
    const { result, unmount } = renderHook(() => useSearch("kela"));
    await waitFor(() => expect(signals).toHaveLength(1), { timeout: SEARCH_DEBOUNCE_MS * 4 });
    unmount();
    expect(signals[0].aborted).toBe(true);
    expect(result.current.error).toBeNull();
  });
});
