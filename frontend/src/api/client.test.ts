import { describe, expect, it, vi } from "vitest";
import { mockFetch } from "../test-utils";
import { ApiError, errorText, get, isAbort, NetworkError, patch, post, put } from "./client";

describe("request", () => {
  it("PATCH and PUT send JSON like POST; a 204 answer gives undefined", async () => {
    const calls = mockFetch({
      "PATCH /api/checklist/3": { status: 204, body: null },
      "PUT /api/notes/item/1": { body: { text: "hi" } },
      "POST /api/checklist/3/remove": { status: 204, body: null },
    });
    expect(await patch("/api/checklist/3", { done: true })).toBeUndefined();
    expect(await put("/api/notes/item/1", { text: "hi" })).toEqual({ text: "hi" });
    expect(await post("/api/checklist/3/remove")).toBeUndefined();
    for (const call of calls) {
      expect(call.headers["Content-Type"]).toBe("application/json");
      expect(call.credentials).toBe("same-origin");
    }
    expect(calls.map((c) => [c.method, c.body])).toEqual([
      ["PATCH", { done: true }],
      ["PUT", { text: "hi" }],
      ["POST", {}],
    ]);
  });
});

describe("ApiError messages", () => {
  it("a sentence from the server stands alone, without the status name", () => {
    expect(errorText(new ApiError(409, "item was changed — mark it done instead"))).toBe(
      "item was changed — mark it done instead",
    );
    expect(errorText(new ApiError(400, "no such tray"))).toBe("no such tray");
    expect(errorText(new ApiError(404, "file x"))).toBe("file x");
  });

  it("without a sentence the status gets a plain label", () => {
    expect(errorText(new ApiError(409, ""))).toBe("Conflict");
    expect(errorText(new ApiError(418, ""))).toBe("Error 418");
  });

  it("a server error keeps its label, which says where to look", () => {
    expect(errorText(new ApiError(500, "boom"))).toBe("Internal error (see the dam log): boom");
  });
});

describe("network failures and cancelled requests", () => {
  it("a server that cannot be reached gives a plain sentence, not the browser's", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const error = await get("/api/status").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(NetworkError);
    expect(errorText(error)).toBe("dam is not running or cannot be reached. Start it again and reload this page.");
  });

  it("an HTTP error keeps its own message", async () => {
    mockFetch({ "GET /api/x": { status: 404, body: { error: "no such thing" } } });
    expect(errorText(await get("/api/x").catch((e: unknown) => e))).toBe("no such thing");
  });

  it("passes the signal to fetch; an abort stays an abort and is not a failure to show", async () => {
    const fetchMock = vi.fn((_url: string, init: RequestInit) =>
      new Promise((_resolve, reject) => {
        init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();
    const pending = get("/api/browse", controller.signal).catch((e: unknown) => e);
    expect(fetchMock.mock.calls[0][1].signal).toBe(controller.signal);
    controller.abort();
    const error = await pending;
    expect(isAbort(error)).toBe(true);
    expect(error).not.toBeInstanceOf(NetworkError);
  });
});
