import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { STATUS_ON } from "../components/ai/testData";
import { mockFetch } from "../test-utils";
import { type AIStatus, useAIStatus, useAISwitch } from "./client";

function wrapper(client: QueryClient) {
  return ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("the AI status query", () => {
  it("is reused for a minute (the server asks the Keychain), and refetched after the switch", async () => {
    let current: AIStatus = STATUS_ON;
    const calls = mockFetch({
      "GET /api/ai/status": () => ({ body: current }),
      "POST /api/ai/state": (call) => {
        const on = (call.body as { enabled: boolean }).enabled;
        current = { ...current, switched_on: on, enabled: on };
        return { body: current };
      },
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const gets = () => calls.filter((c) => c.method === "GET" && c.url === "/api/ai/status").length;
    const first = renderHook(() => useAIStatus(), { wrapper: wrapper(client) });
    await waitFor(() => expect(first.result.current.data?.enabled).toBe(true));
    first.unmount();
    // a screen mounted again within the minute does not ask again
    const again = renderHook(() => ({ status: useAIStatus(), change: useAISwitch() }), { wrapper: wrapper(client) });
    expect(again.result.current.status.data?.enabled).toBe(true);
    expect(gets()).toBe(1);
    await act(() => again.result.current.change.mutateAsync(false));
    await waitFor(() => expect(again.result.current.status.data?.switched_on).toBe(false));
    await waitFor(() => expect(gets()).toBe(2)); // refreshed after the toggle
  });
});
