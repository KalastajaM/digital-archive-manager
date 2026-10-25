import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CARD_DRAG_TYPE } from "./components/useCardLayout";
import {
  COLLECTION_DRAG_TYPE,
  DRAG_TYPE,
  dragSelection,
  readDragCollection,
  readBrowseDrag,
  readDragFiles,
  SPECIAL_DRAG_TYPE,
  setDragCollection,
  setDragFiles,
  useDropTarget,
} from "./dnd";
import { dataTransfer } from "./test-utils";

/** A drag event as the browser hands it to a listener: only ``dataTransfer`` matters. */
const dragEvent = (dt: ReturnType<typeof dataTransfer>) => ({ dataTransfer: dt }) as unknown as DragEvent;

describe("rows of the app's own folders", () => {
  it("drag with their own type: no file target outside Browse sees them as files", () => {
    const dt = dataTransfer();
    setDragFiles(dragEvent(dt), ["l1"], "a.pdf", undefined, true);
    expect(dt.types).toContain(SPECIAL_DRAG_TYPE);
    expect(dt.types).not.toContain(DRAG_TYPE);
    expect(readDragFiles(dragEvent(dt))).toBeNull();
    expect(readBrowseDrag(dragEvent(dt))).toEqual({ kind: "files", ids: ["l1"], special: true });
    document.dispatchEvent(new Event("dragend"));
  });

  it("a refused drop is reported, and the browser is still allowed to deliver it", () => {
    const onRefused = vi.fn();
    const onDrop = vi.fn();
    function Refusing() {
      const target = useDropTarget({ accept: () => "Not here", onDrop, onRefused });
      return <div data-testid="t" {...target.props} />;
    }
    render(<Refusing />);
    const dt = dataTransfer();
    setDragFiles(dragEvent(dt), ["f1"], "a.pdf");
    fireEvent.dragOver(screen.getByTestId("t"), { dataTransfer: dt });
    expect(dt.dropEffect).not.toBe("none");
    fireEvent.drop(screen.getByTestId("t"), { dataTransfer: dt });
    expect(onRefused).toHaveBeenCalledWith("Not here", ["f1"]);
    expect(onDrop).not.toHaveBeenCalled();
    document.dispatchEvent(new Event("dragend"));
  });
});

describe("dnd payload", () => {
  it("round-trips the ids through the drag data", () => {
    const dt = dataTransfer();
    setDragFiles(dragEvent(dt), ["f1", "f2"], "a.pdf");
    expect(dt.types).toContain(DRAG_TYPE);
    expect(JSON.parse(dt.data[DRAG_TYPE])).toEqual({ ids: ["f1", "f2"] });
    expect(dt.data["text/plain"]).toBe("2 files");
    expect(readDragFiles(dragEvent(dt))).toEqual(["f1", "f2"]);
    document.dispatchEvent(new Event("dragend"));
  });

  it("while hovering (data hidden) the ids of a drag started here are still known; dragend forgets them", () => {
    const dt = dataTransfer({ protectedMode: true });
    setDragFiles(dragEvent(dt), ["f1"], "a.pdf");
    expect(dt.data["text/plain"]).toBe("a.pdf");
    expect(readDragFiles(dragEvent(dt))).toEqual(["f1"]);
    document.dispatchEvent(new Event("dragend"));
    expect(readDragFiles(dragEvent(dt))).toBeNull();
  });

  it("draws a drag image naming the file, or the count", () => {
    const dt = dataTransfer();
    const images: string[] = [];
    dt.setDragImage = (el?: Element) => {
      images.push(el?.textContent ?? "");
    };
    setDragFiles(dragEvent(dt), ["f1"], "a.pdf");
    setDragFiles(dragEvent(dt), ["f1", "f2", "f3"], "a.pdf");
    expect(images).toEqual(["a.pdf", "3 files"]);
    document.dispatchEvent(new Event("dragend"));
  });

  it("ignores drags from elsewhere and malformed payloads", () => {
    const foreign = dataTransfer();
    foreign.setData("text/plain", "hello");
    expect(readDragFiles(dragEvent(foreign))).toBeNull();
    for (const raw of ["not json", "{}", '{"ids":[]}', '{"ids":[1,2]}', '{"ids":"f1"}']) {
      const dt = dataTransfer();
      dt.setData(DRAG_TYPE, raw);
      expect(readDragFiles(dragEvent(dt))).toBeNull();
    }
  });

  it("dragSelection drags the whole selection when the row is in it, else that row alone", () => {
    expect(dragSelection(["a", "b"], "b")).toEqual(["a", "b"]);
    expect(dragSelection(["a", "b"], "c")).toEqual(["c"]);
    expect(dragSelection([], "c")).toEqual(["c"]);
  });
});

describe("collection drags", () => {
  it("carry their own type: never files, never a card, and the other way round", () => {
    const dt = dataTransfer();
    setDragCollection(dragEvent(dt), 7, "Sauna");
    expect(COLLECTION_DRAG_TYPE).toBe("application/x-dam-collection");
    expect(dt.types).toEqual([COLLECTION_DRAG_TYPE]);
    expect(JSON.parse(dt.data[COLLECTION_DRAG_TYPE])).toEqual({ id: 7 });
    expect(readDragCollection(dragEvent(dt))).toBe(7);
    expect(readDragFiles(dragEvent(dt))).toBeNull();
    document.dispatchEvent(new Event("dragend"));

    const files = dataTransfer();
    setDragFiles(dragEvent(files), ["f1"], "a.pdf");
    expect(readDragCollection(dragEvent(files))).toBeNull();
    document.dispatchEvent(new Event("dragend"));

    const card = dataTransfer();
    card.setData(CARD_DRAG_TYPE, "7");
    expect(readDragCollection(dragEvent(card))).toBeNull();
    expect(readDragFiles(dragEvent(card))).toBeNull();
    // a collection type beside files or a card is not a collection drag
    const mixed = dataTransfer();
    mixed.setData(COLLECTION_DRAG_TYPE, '{"id":7}');
    mixed.setData(DRAG_TYPE, '{"ids":["f1"]}');
    expect(readDragCollection(dragEvent(mixed))).toBeNull();
  });

  it("while hovering (data hidden) the collection of a drag started here is known; dragend forgets it", () => {
    const dt = dataTransfer({ protectedMode: true });
    setDragCollection(dragEvent(dt), 7, "Sauna");
    expect(readDragCollection(dragEvent(dt))).toBe(7);
    document.dispatchEvent(new Event("dragend"));
    expect(readDragCollection(dragEvent(dt))).toBeNull();
  });

  it("ignores malformed payloads", () => {
    for (const raw of ["not json", "{}", '{"id":"7"}', '{"id":1.5}', '{"id":-1}']) {
      const dt = dataTransfer();
      dt.setData(COLLECTION_DRAG_TYPE, raw);
      expect(readDragCollection(dragEvent(dt))).toBeNull();
    }
  });

  it("a files drop target ignores a collection drag", () => {
    const onDrop = vi.fn();
    render(<Target name="t" accept={() => true} onDrop={onDrop} />);
    const dt = dataTransfer();
    setDragCollection(dragEvent(dt), 7, "Sauna");
    expect(fireEvent.dragEnter(screen.getByTestId("t"), { dataTransfer: dt })).toBe(true); // not taken
    expect(screen.getByTestId("t")).not.toHaveAttribute("data-drop");
    fireEvent.drop(screen.getByTestId("t"), { dataTransfer: dt });
    expect(onDrop).not.toHaveBeenCalled();
    document.dispatchEvent(new Event("dragend"));
  });
});

function Target({
  name,
  accept,
  onDrop,
  children,
}: {
  name: string;
  accept: (ids: string[]) => boolean | string;
  onDrop: (ids: string[]) => void;
  children?: React.ReactNode;
}) {
  const drop = useDropTarget({ accept, onDrop });
  return (
    <div data-testid={name} {...drop.props}>
      {children}
    </div>
  );
}

describe("nested drop targets", () => {
  function setup(inner: boolean | string) {
    const outerDrop = vi.fn();
    const innerDrop = vi.fn();
    render(
      <Target name="outer" accept={() => true} onDrop={outerDrop}>
        <span data-testid="plain">row</span>
        <Target name="inner" accept={() => inner} onDrop={innerDrop}>
          <span data-testid="child">folder</span>
        </Target>
      </Target>,
    );
    const dt = dataTransfer();
    setDragFiles(dragEvent(dt), ["f1"], "a.pdf");
    return { dt, outerDrop, innerDrop };
  }

  it("a drop on an inner target that accepts never reaches the outer one", () => {
    const { dt, outerDrop, innerDrop } = setup(true);
    fireEvent.dragEnter(screen.getByTestId("plain"), { dataTransfer: dt });
    expect(screen.getByTestId("outer")).toHaveAttribute("data-drop", "over");
    fireEvent.dragEnter(screen.getByTestId("child"), { dataTransfer: dt });
    fireEvent.dragLeave(screen.getByTestId("plain"), { dataTransfer: dt });
    expect(screen.getByTestId("inner")).toHaveAttribute("data-drop", "over");
    expect(screen.getByTestId("outer")).not.toHaveAttribute("data-drop");
    fireEvent.drop(screen.getByTestId("child"), { dataTransfer: dt });
    expect(innerDrop).toHaveBeenCalledWith(["f1"], expect.anything());
    expect(outerDrop).not.toHaveBeenCalled();
    document.dispatchEvent(new Event("dragend"));
  });

  it("leaving the inner target back into the outer one highlights the outer again", () => {
    const { dt } = setup(true);
    fireEvent.dragEnter(screen.getByTestId("child"), { dataTransfer: dt });
    fireEvent.dragEnter(screen.getByTestId("plain"), { dataTransfer: dt });
    fireEvent.dragLeave(screen.getByTestId("child"), { dataTransfer: dt });
    expect(screen.getByTestId("inner")).not.toHaveAttribute("data-drop");
    expect(screen.getByTestId("outer")).toHaveAttribute("data-drop", "over");
    act(() => {
      document.dispatchEvent(new Event("dragend"));
    });
    expect(screen.getByTestId("outer")).not.toHaveAttribute("data-drop");
  });

  it("a refused inner drop is not passed on to the outer target", () => {
    const { dt, outerDrop, innerDrop } = setup("Already here");
    fireEvent.dragEnter(screen.getByTestId("child"), { dataTransfer: dt });
    expect(screen.getByTestId("inner")).toHaveAttribute("data-drop", "refused");
    expect(screen.getByTestId("inner")).toHaveAttribute("data-tip", "Already here");
    expect(fireEvent.drop(screen.getByTestId("child"), { dataTransfer: dt })).toBe(false);
    expect(innerDrop).not.toHaveBeenCalled();
    expect(outerDrop).not.toHaveBeenCalled();
    document.dispatchEvent(new Event("dragend"));
  });

  it("an inner target that ignores the drag leaves it to the outer one", () => {
    const { dt, outerDrop, innerDrop } = setup(false);
    fireEvent.dragEnter(screen.getByTestId("child"), { dataTransfer: dt });
    expect(screen.getByTestId("outer")).toHaveAttribute("data-drop", "over");
    fireEvent.drop(screen.getByTestId("child"), { dataTransfer: dt });
    expect(outerDrop).toHaveBeenCalledWith(["f1"], expect.anything());
    expect(innerDrop).not.toHaveBeenCalled();
    document.dispatchEvent(new Event("dragend"));
  });
});
