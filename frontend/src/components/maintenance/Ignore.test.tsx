import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { mockFetch, renderWithProviders } from "../../test-utils";
import { IgnoreButton, IgnoredList, useIgnore } from "./Ignore";

const entry = { id: 5, kind: "duplicates", key: "k1", label: "scan.pdf", created: 1 };

function Harness({ onChange }: { onChange: () => void }) {
  const ignore = useIgnore(onChange);
  return (
    <IgnoreButton label="scan.pdf" onClick={() => void ignore.ignore({ kind: "duplicates", key: "k1", label: "scan.pdf" })} />
  );
}

describe("IgnoreButton and useIgnore", () => {
  it("ignores an entry, tells the check and offers Undo", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const calls = mockFetch({
      "POST /api/maintenance/ignored": { body: entry },
      "DELETE /api/maintenance/ignored/5": { status: 204, body: null },
    });
    renderWithProviders(<Harness onChange={onChange} />);
    await user.click(screen.getByRole("button", { name: "Ignore scan.pdf" }));
    expect(await screen.findByText("Ignored scan.pdf")).toBeInTheDocument();
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ kind: "duplicates", key: "k1", label: "scan.pdf" });
    await user.click(screen.getByRole("button", { name: /undo/i }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(2));
  });

  it("says when it could not ignore", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    mockFetch({ "POST /api/maintenance/ignored": { status: 409, body: { error: "database is locked" } } });
    renderWithProviders(<Harness onChange={onChange} />);
    await user.click(screen.getByRole("button", { name: "Ignore scan.pdf" }));
    expect(await screen.findByText("Not ignored: database is locked")).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe("IgnoredList", () => {
  it("shows nothing when this card ignores nothing", async () => {
    const calls = mockFetch({ "GET /api/maintenance/ignored": { body: [{ ...entry, kind: "other" }] } });
    renderWithProviders(<IgnoredList kinds={["duplicates"]} onChange={() => {}} />);
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("opens the list and takes an entry back", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const calls = mockFetch({
      "GET /api/maintenance/ignored": { body: [entry] },
      "DELETE /api/maintenance/ignored/5": { status: 204, body: null },
    });
    renderWithProviders(<IgnoredList kinds={["duplicates"]} onChange={onChange} />);
    await user.click(await screen.findByRole("button", { name: "1 ignored entry" }));
    await user.click(screen.getByRole("button", { name: "Stop ignoring scan.pdf" }));
    expect(await screen.findByText("No longer ignored: scan.pdf")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "DELETE")).toBe(true);
    expect(onChange).toHaveBeenCalled();
  });

  it("says when stopping failed", async () => {
    const user = userEvent.setup();
    mockFetch({
      "GET /api/maintenance/ignored": { body: [entry] },
      "DELETE /api/maintenance/ignored/5": { status: 404, body: { error: "no such entry" } },
    });
    renderWithProviders(<IgnoredList kinds={["duplicates"]} onChange={() => {}} />);
    await user.click(await screen.findByRole("button", { name: "1 ignored entry" }));
    await user.click(screen.getByRole("button", { name: "Stop ignoring scan.pdf" }));
    expect(await screen.findByText("Still ignored: no such entry")).toBeInTheDocument();
  });
});
