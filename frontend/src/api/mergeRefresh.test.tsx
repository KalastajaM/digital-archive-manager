/** After a merge, what is on screen of the target reloads: its checklist gains the merged
 * collection's items, even when it is already shown (Browse's other pane). */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { mockFetch } from "../test-utils";
import { useChecklist, useMergeCollection } from "./client";

function wrapper(client: QueryClient) {
  return ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("a merge", () => {
  it("reloads the checklist of a collection already shown", async () => {
    const calls = mockFetch({
      "GET /api/checklist/collection/3": { body: [] },
      "POST /api/collections/1/merge": { body: { collection: { id: 3 }, batch: null, problems: [], ongoing_status: null } },
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const gets = () => calls.filter((c) => c.method === "GET" && c.url === "/api/checklist/collection/3").length;
    const hook = renderHook(() => ({ list: useChecklist("collection", "3"), merge: useMergeCollection() }), { wrapper: wrapper(client) });
    await waitFor(() => expect(gets()).toBe(1));
    await act(async () => {
      await hook.result.current.merge.merge.mutateAsync({ id: 1, into: 3 });
    });
    await waitFor(() => expect(gets()).toBe(2));
  });
});
