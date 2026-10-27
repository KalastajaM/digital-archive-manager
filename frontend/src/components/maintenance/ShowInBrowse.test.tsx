import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { QuickLookButton, ShowInBrowse } from "./ShowInBrowse";

function Where() {
  const at = useLocation();
  return <p data-testid="where">{at.pathname + at.search}</p>;
}

describe("ShowInBrowse", () => {
  it("goes to the given Browse location", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/maintenance"]}>
        <Routes>
          <Route path="*" element={<><ShowInBrowse to="/browse?path=40.%20House" /><Where /></>} />
        </Routes>
      </MemoryRouter>,
    );
    await user.click(screen.getByRole("button", { name: "Show in Browse" }));
    expect(screen.getByTestId("where")).toHaveTextContent("/browse?path=40.%20House");
  });

  it("takes another label", () => {
    render(
      <MemoryRouter>
        <ShowInBrowse to="/browse" label="Show the folder" />
      </MemoryRouter>,
    );
    expect(screen.getByRole("button", { name: "Show the folder" })).toBeInTheDocument();
  });
});

describe("QuickLookButton", () => {
  it("calls back on click", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<QuickLookButton onClick={onClick} />);
    await user.click(screen.getByRole("button", { name: "Quick Look" }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
