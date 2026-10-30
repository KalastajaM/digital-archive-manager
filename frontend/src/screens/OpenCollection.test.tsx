/** /open-collection/<id>: a link that knows only a collection's id opens it in Browse
 * (Important on its page). */
import { cleanup, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { mockFetch, renderWithProviders } from "../test-utils";
import OpenCollection from "./OpenCollection";

function Where() {
  const loc = useLocation();
  return <p data-testid="where">{loc.pathname + loc.search}</p>;
}

function setup(id: number) {
  mockFetch({
    "GET /api/collections": {
      body: [
        { id: 3, name: "House sale", kind: null, state: "open", parent_id: null, members: [], path: ["House sale"] },
        { id: 2, name: "! Important", kind: "important", state: "open", parent_id: null, members: [], path: ["! Important"] },
      ],
    },
  });
  renderWithProviders(
    <MemoryRouter initialEntries={[`/open-collection/${id}`]}>
      <Routes>
        <Route path="/open-collection/:id" element={<OpenCollection />} />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(cleanup);

describe("OpenCollection", () => {
  it("forwards to the collection in Browse", async () => {
    setup(3);
    expect(await screen.findByTestId("where")).toHaveTextContent('/browse?tree=collections&q=collection%3A%22House+sale%22');
  });
  it("forwards Important to its page", async () => {
    setup(2);
    expect(await screen.findByTestId("where")).toHaveTextContent("/important");
  });
  it("says when there is no such collection", async () => {
    setup(99);
    expect(await screen.findByText("There is no such collection.")).toBeInTheDocument();
  });
});
