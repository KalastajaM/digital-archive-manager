import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import type { FileRequest } from "../api/client";
import { ToastProvider } from "../components/Toasts";
import { mockFetch } from "../test-utils";
import { useFiling } from "./useFiling";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <ToastProvider>{children}</ToastProvider>
    </QueryClientProvider>
  );
}

const REQUESTS: FileRequest[] = [
  { drive_id: "d1", name: "a.pdf", folder: "10. Financial", tags: [], tray: "to-pay", tray_fields: { reference: "" } },
  { drive_id: "d2", name: "b.pdf", folder: "10. Financial", tags: [], tray: "to-pay", tray_fields: { reference: "" } },
];

describe("useFiling", () => {
  it("the confirm keeps the speaker's scan prefill from preview time, not the live entries", async () => {
    mockFetch({
      "POST /api/inbox/preview": {
        body: [{ kind: "move", src: "##. Organize/a.pdf", dst: "10. Financial/a.pdf", drive_id: "d1", note: null }],
      },
    });
    const seen: string[] = [];
    const { result, rerender } = renderHook(
      ({ prefill }: { prefill: Record<string, string> | undefined }) =>
        useFiling(
          () => {},
          (id) => {
            seen.push(id);
            return prefill;
          },
        ),
      { wrapper, initialProps: { prefill: { reference: "RF18 5390 0754 7034" } as Record<string, string> | undefined } },
    );
    result.current.form.current = REQUESTS;
    act(() => result.current.fileIt(REQUESTS, true));
    await waitFor(() => expect(result.current.confirm).not.toBeNull());
    expect(seen).toEqual(["d1"]); // the speaker: the first request
    rerender({ prefill: undefined }); // the inbox refetched: the entry is gone
    expect(result.current.confirm?.prefill).toEqual({ reference: "RF18 5390 0754 7034" });
  });
});

describe("useFiling via", () => {
  const run = async (args: [FileRequest[], boolean?, ("form" | "batch" | "codes")?]) => {
    const calls = mockFetch({
      "POST /api/inbox/preview": {
        body: [{ kind: "move", src: "##. Organize/a.pdf", dst: "10. Financial/a.pdf", drive_id: "d1", note: null }],
      },
      "POST /api/inbox/file": {
        body: { batch_id: "b1", dry_run: false, done: [], failed: null, error: null, index_error: null, untagged: [] },
      },
    });
    const { result } = renderHook(() => useFiling(() => {}), { wrapper });
    result.current.form.current = args[0];
    act(() => result.current.fileIt(...args));
    await waitFor(() => expect(result.current.confirm ?? calls.some((c) => c.url === "/api/inbox/file")).toBeTruthy());
    if (result.current.confirm) act(() => result.current.confirmApply());
    await waitFor(() => expect(calls.some((c) => c.url === "/api/inbox/file")).toBe(true));
    return calls.find((c) => c.url === "/api/inbox/file")?.body;
  };

  it("passes codes through the confirm", async () => {
    expect(await run([REQUESTS, true, "codes"])).toMatchObject({ via: "codes" });
  });
  it("defaults a batch to batch and a single filing to form", async () => {
    expect(await run([REQUESTS, true])).toMatchObject({ via: "batch" });
    expect(await run([[REQUESTS[0]]])).toMatchObject({ via: "form" });
  });
});
