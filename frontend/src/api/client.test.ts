import { describe, expect, it } from "vitest";
import { mockFetch } from "../test-utils";
import { ApiError, errorText, patch, post, put } from "./client";

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
