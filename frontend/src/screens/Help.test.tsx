/** Help renders docs/guide.md with its contents beside it. The second half keeps the
 * guide from drifting: every screen has a section, and every link lands on a heading. */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import app from "../App.tsx?raw";
import guide from "../../../docs/guide.md?raw";
import reference from "../../../docs/reference.md?raw";
import Help, { DIAGRAMS_SECTION, headings, helpMarkdown, slug } from "./Help";

function renderHelp(at = "/help") {
  return render(
    <MemoryRouter initialEntries={[at]}>
      <Help />
    </MemoryRouter>,
  );
}

describe("Help", () => {
  it("lists the guide's sections beside it, without the guide's own title and Contents", () => {
    renderHelp();
    const toc = screen.getByRole("navigation", { name: "Contents" });
    expect(toc).toHaveTextContent("How dam works");
    expect(toc).toHaveTextContent("Starter layouts"); // a ### entry
    expect(toc).not.toHaveTextContent(/^Contents/);
    expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Contents" })).toBeNull();
    expect(screen.getByRole("heading", { level: 2, name: "Trays" })).toHaveAttribute("id", "trays");
  });

  it("every word of the guide is under a section in the contents, so none hides above the first", () => {
    expect(helpMarkdown(guide).trimStart()).toMatch(/^## /);
    renderHelp();
    expect(screen.getByRole("link", { name: "What dam is" })).toHaveAttribute("aria-current", "location");
  });

  it("a contents entry marks its section as the current one", async () => {
    renderHelp();
    const link = screen.getByRole("link", { name: "Trays" });
    await userEvent.click(link);
    expect(link).toHaveAttribute("aria-current", "location");
  });

  it("opens at the section in the address", () => {
    renderHelp("/help#reminders");
    expect(screen.getByRole("link", { name: "Reminders" })).toHaveAttribute("aria-current", "location");
  });

  it("links to the technical reference open it on GitHub in a new tab", () => {
    renderHelp();
    const link = screen.getAllByRole("link", { name: "technical reference" })[0];
    expect(link).toHaveAttribute("href", expect.stringMatching(/^https:\/\/github\.com\/.+\/docs\/reference\.md$/));
    expect(link).toHaveAttribute("target", "_blank");
  });

  it("shows the diagrams of how dam works right under that section's heading", () => {
    renderHelp();
    const heading = screen.getByRole("heading", { level: 2, name: "How dam works" });
    expect(heading).toHaveAttribute("id", DIAGRAMS_SECTION);
    const diagrams = heading.nextElementSibling as HTMLElement;
    const figures = within(diagrams).getAllByRole("figure");
    expect(figures.map((f) => f.querySelector("figcaption strong")?.textContent)).toEqual([
      "The filing flow",
      "Where a filed document lands",
      "When the trays remind you",
      "The safety loop",
      "“Delete” is a move",
      "What stays on your computer",
    ]);
    // each diagram is described for a screen reader
    for (const figure of figures) expect(within(figure).getByRole("img")).toHaveAccessibleName();
    // the arrowheads are this instance's own, so every arrow finds one
    const heads = new Set([...diagrams.querySelectorAll("marker")].map((m) => `url(#${m.id})`));
    for (const path of diagrams.querySelectorAll("[marker-end]")) expect(heads).toContain(path.getAttribute("marker-end"));
  });

  it("shows the Relatives diagram right under the Relatives heading", () => {
    renderHelp();
    const heading = screen.getByRole("heading", { level: 2, name: "Relatives" });
    const diagram = heading.nextElementSibling as HTMLElement;
    expect(within(diagram).getByRole("figure")).toHaveTextContent("How Relatives works");
  });

  it("slugs headings the way GitHub does", () => {
    expect(slug("AI (optional)")).toBe("ai-optional");
    expect(slug("Starred and Important")).toBe("starred-and-important");
    expect(slug("Run it as its own app window")).toBe("run-it-as-its-own-app-window");
  });
});

const ids = (markdown: string) => new Set(headings(markdown).map((h) => h.id));
const anchors = (markdown: string, file: string) =>
  [...markdown.matchAll(/\]\(([^)\s]*)\)/g)].map((m) => m[1]).filter((href) => href.startsWith(`${file}#`) || (file === "" && href.startsWith("#")));

/** The guide section that explains each screen. A new route fails here until the guide
 * covers it. */
const SCREEN_SECTIONS: Record<string, string> = {
  "/": "today",
  "/inbox": "filing-from-the-inbox",
  "/trays/:trayId?": "trays",
  "/collections/:id?": "collections",
  "/open-collection/:id": "collections",
  "/ongoing": "converting-existing-folders",
  "/starred": "starred-and-important",
  "/important": "starred-and-important",
  "/important/convert": "converting-existing-folders",
  "/browse": "browse",
  "/tags": "tags",
  "/ask": "ai-optional",
  "/activity": "activity-and-undo",
  "/maintenance": "maintenance",
  "/settings/:section?": "settings",
  "/help": "how-dam-works",
  "/viewer/:driveId": "quick-look-and-the-viewer-window",
};

describe("the guide stays in step with the app", () => {
  const guideIds = ids(guide);

  it("every screen has a section in the guide", () => {
    const routes = [...app.matchAll(/<Route path="([^"]+)"/g)].map((m) => m[1]).filter((p) => p !== "*");
    expect(routes.length).toBeGreaterThan(5);
    for (const route of routes) {
      expect(SCREEN_SECTIONS, `add ${route} to SCREEN_SECTIONS and the guide`).toHaveProperty([route]);
      expect(guideIds, `${route} → #${SCREEN_SECTIONS[route]}`).toContain(SCREEN_SECTIONS[route]);
    }
  });

  it("every sidebar row is named in the guide's description of the window", () => {
    const sidebar = helpMarkdown(guide).split("## The window")[1].split("\n## ")[0];
    for (const row of ["Today", "Inbox", "Trays", "Collections", "Important", "Starred", "Browse", "Tags", "Ask", "Activity", "Settings", "Help"]) {
      expect(sidebar).toContain(`**${row}**`);
    }
  });

  it("the guide's links land on its own headings and the reference's", () => {
    const referenceIds = ids(reference);
    for (const href of anchors(guide, "")) expect(guideIds, href).toContain(href.slice(1));
    for (const href of anchors(guide, "reference.md")) expect(referenceIds, href).toContain(href.split("#")[1]);
    for (const href of anchors(reference, "")) expect(referenceIds, href).toContain(href.slice(1));
  });

  it("the guide's Contents list names every section", () => {
    const listed = new Set(anchors(guide.split("## Contents")[1].split("\n## ")[0], "").map((h) => h.slice(1)));
    for (const h of headings(guide).filter((h) => h.level === 2 && h.id !== "contents")) {
      expect(listed, h.text).toContain(h.id);
    }
  });

  it("the guide speaks to users: no project history or design files", () => {
    expect(guide).not.toMatch(/\bphase \d/i);
    expect(guide).not.toMatch(/superpowers|specs\/|migration \d/i);
  });
});
