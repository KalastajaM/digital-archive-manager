/** The typed API calls: URLs built from the OpenAPI path templates, the request() they go
 * through (signal, NetworkError), and types taken from schema.d.ts (checked by tsc in
 * the build: a ``@ts-expect-error`` that stops erroring fails it). */
import { afterEach, describe, expect, expectTypeOf, it, vi } from "vitest";
import { mockFetch } from "../test-utils";
import { apiDelete, apiGet, apiPost, NetworkError } from "./client";
import type { components } from "./schema";
import { buildUrl } from "./typed";

type Schemas = components["schemas"];

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("buildUrl", () => {
  it("fills and encodes the path parameters", () => {
    expect(buildUrl("/api/maintenance/jobs/{job_id}/stop", { job_id: "a b/c" })).toBe(
      "/api/maintenance/jobs/a%20b%2Fc/stop",
    );
  });

  it("appends the query in order, leaving out empty values and repeating arrays", () => {
    expect(buildUrl("/api/x", undefined, { q: "é&", n: 2, gone: undefined, none: null, tag: ["a", "b"], on: true })).toBe(
      "/api/x?q=%C3%A9%26&n=2&tag=a&tag=b&on=true",
    );
    expect(buildUrl("/api/x", undefined, { gone: undefined })).toBe("/api/x");
  });

  it("refuses a template whose parameter has no value", () => {
    expect(() => buildUrl("/api/x/{id}", {})).toThrow("no value for {id}");
  });
});

describe("apiGet, apiPost and apiDelete", () => {
  it("call the built URL with the body and answer the JSON", async () => {
    const calls = mockFetch({
      "GET /api/maintenance/jobs/j%201": { body: { job_id: "j 1" } },
      "POST /api/maintenance/moved/undo": { body: { dry_run: false, pairs: [], errors: [], undo_id: null } },
      "DELETE /api/maintenance/jobs": { body: { forgotten: 2 } },
    });
    const job = await apiGet("/api/maintenance/jobs/{job_id}", { path: { job_id: "j 1" } });
    expect(job.job_id).toBe("j 1");
    const undone = await apiPost("/api/maintenance/moved/undo", { body: { undo_id: "u1" } });
    expect(undone.errors).toEqual([]);
    expect(await apiDelete("/api/maintenance/jobs", { query: { kind: "moved" } })).toEqual({ forgotten: 2 });
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      "GET /api/maintenance/jobs/j%201",
      "POST /api/maintenance/moved/undo",
      "DELETE /api/maintenance/jobs?kind=moved",
    ]);
    expect(calls[1].body).toEqual({ undo_id: "u1" });
  });

  it("pass the signal on and say when the server cannot be reached", async () => {
    const fetch = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    });
    vi.stubGlobal("fetch", fetch);
    const signal = new AbortController().signal;
    await expect(apiGet("/api/maintenance/duplicates/estimate", { signal })).rejects.toBeInstanceOf(NetworkError);
    expect(fetch).toHaveBeenCalledWith("/api/maintenance/duplicates/estimate", expect.objectContaining({ signal }));
  });

  it("take their types from the schema", () => {
    expectTypeOf(apiGet<"/api/maintenance/jobs/{job_id}">)
      .returns.resolves.toEqualTypeOf<Schemas["MaintenanceJobOut"]>();
    expectTypeOf(apiPost<"/api/maintenance/moved/reconnect">)
      .returns.resolves.toEqualTypeOf<Schemas["ReconnectOut"]>();
    // what does not match the API does not compile (the calls are never made)
    const never = () => {
      // @ts-expect-error a path parameter is required
      void apiGet("/api/maintenance/jobs/{job_id}");
      // @ts-expect-error not a path of the API
      void apiGet("/api/no-such-path");
      // @ts-expect-error the body is required
      void apiPost("/api/maintenance/moved/undo");
      // @ts-expect-error the body has the wrong shape
      void apiPost("/api/maintenance/moved/undo", { body: { undo: "u1" } });
    };
    expect(never).toBeTypeOf("function");
  });
});
