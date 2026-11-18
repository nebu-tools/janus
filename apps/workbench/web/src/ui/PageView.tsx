// One page of a document with boxes drawn over it.
//
// This file and PageView.css stand alone: they import nothing else from the workbench. Box
// coordinates are in the page's own units, the same units as `width` and `height`, with the
// origin at the top left.
//
// The boxes of a page are one list with one tab stop. The keyboard moves an active box through
// it, and the pointer and the keyboard report to the caller through the same two callbacks.
import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { KeyboardEvent } from "react";

import "./PageView.css";

export interface PageBox {
  /** Returned by the events. Boxes that share an id are one thing drawn in several places. */
  id: string;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  /** Any CSS colour. */
  color: string;
  /** What the box is and holds: "Word: Invoice". It is the box's name for a screen reader, and
   * it is shown while the pointer is over the box or the keyboard is on it. */
  label: string;
  /** How the box is drawn. "outline" is the default. */
  look?: "outline" | "wash" | "strong";
  /** The box is the one chosen. */
  selected?: boolean;
  /** The box belongs to an answer that is no longer current. It is drawn dimmed and dashed;
   * the label says what it belongs to. */
  old?: boolean;
}

export interface PageViewProps {
  /** The page image. It is stretched over the whole page. */
  src: string;
  /** The page's size, in the units the boxes use. */
  width: number;
  height: number;
  boxes: readonly PageBox[];
  /** What the page is called: "Page 3". */
  name: string;
  /** The pointer or the keyboard came to a box, or left the boxes (null). */
  onBoxActive?: (id: string | null) => void;
  /** A box was clicked, or Enter or Space was pressed on it. */
  onBoxChoose?: (id: string) => void;
  /** Page Up (-1) or Page Down (1) was pressed on this page. */
  onPage?: (delta: -1 | 1) => void;
  /** Says why the image at `src` did not load, in words. Left out, the page says only that it
   * did not load. */
  explain?: (src: string) => Promise<string>;
  /** How long the image may take to load, in ms. */
  deadline?: number;
}

type Rect = Pick<PageBox, "x0" | "y0" | "x1" | "y1">;

/** The order the boxes are read in: row after row from the top, each row from the left. Boxes
 * whose tops are close, measured by the lower of the two, are one row. Returns indexes. */
export function readingOrder(boxes: readonly Rect[]): number[] {
  const byTop = boxes.map((_, i) => i).sort((a, b) => boxes[a]!.y0 - boxes[b]!.y0);
  const order: number[] = [];
  let row: number[] = [];
  const flush = () => {
    row.sort((a, b) => boxes[a]!.x0 - boxes[b]!.x0 || boxes[b]!.y1 - boxes[a]!.y1 || a - b);
    order.push(...row);
    row = [];
  };
  for (const index of byTop) {
    const first = row[0] === undefined ? undefined : boxes[row[0]];
    const box = boxes[index]!;
    const lower = first ? Math.min(first.y1 - first.y0, box.y1 - box.y0) : 0;
    if (first && box.y0 - first.y0 >= Math.max(lower, 1) / 2) flush();
    row.push(index);
  }
  flush();
  return order;
}

/** The box nearest to `boxes[from]` above it (-1) or below it (1): the one with the least
 * distance, where a step to the side counts three times a step up or down. */
export function nearest(boxes: readonly Rect[], from: number, direction: -1 | 1): number | null {
  const here = boxes[from];
  if (!here) return null;
  const middle = (box: Rect) => (box.y0 + box.y1) / 2;
  let best: number | null = null;
  let least = Infinity;
  boxes.forEach((box, index) => {
    const dy = (middle(box) - middle(here)) * direction;
    if (index === from || dy <= 0.5) return;
    const aside = Math.max(box.x0 - here.x1, here.x0 - box.x1, 0);
    const distance = dy + 3 * aside;
    if (distance < least) {
      least = distance;
      best = index;
    }
  });
  return best;
}

const place = (box: Rect) => `${box.x0}:${box.y0}:${box.x1}:${box.y1}`;

type Failed = { why: string } | null;

interface ImageProps {
  src: string;
  name: string;
  explain: ((src: string) => Promise<string>) | undefined;
  deadline: number;
}

/** The image of the page, or what stands in its place when it did not load. */
function PageImage({ src, name, explain, deadline }: ImageProps) {
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState<Failed>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (loaded || failed) return;
    const timer = setTimeout(
      () => setFailed({ why: `it did not load in ${deadline / 1000} seconds` }),
      deadline,
    );
    return () => clearTimeout(timer);
  }, [loaded, failed, attempt, deadline]);

  if (failed !== null) {
    return (
      <div className="pageview-failed" role="alert">
        <p>
          {name} could not be shown{failed.why === "" ? "." : `: ${failed.why}`}
        </p>
        <button
          type="button"
          onClick={() => {
            setFailed(null);
            setLoaded(false);
            setAttempt((n) => n + 1);
          }}
        >
          Load {name} again
        </button>
      </div>
    );
  }
  return (
    <img
      key={attempt}
      className="pageview-image"
      // A new address for the same image, so the browser asks for it again.
      src={attempt === 0 ? src : `${src}#again-${attempt}`}
      alt={name}
      draggable={false}
      decoding="async"
      data-loaded={loaded}
      onLoad={() => setLoaded(true)}
      onError={() => {
        setFailed({ why: "" });
        void explain?.(src).then((why) => setFailed((now) => (now ? { why } : now)));
      }}
    />
  );
}

export function PageView(props: PageViewProps) {
  const { src, width, height, boxes, name, onBoxActive, onBoxChoose, onPage, explain } = props;
  const deadline = props.deadline ?? 30_000;
  const base = useId();
  const list = useRef<HTMLDivElement>(null);
  // The boxes in reading order, each with its place in the caller's order: a later box is
  // drawn over an earlier one.
  const ordered = useMemo(
    () => readingOrder(boxes).map((index) => ({ box: boxes[index]!, index })),
    [boxes],
  );
  // The box the keyboard is on is remembered by what and where it is, so it survives a new list
  // of boxes that still holds it.
  const [mark, setMark] = useState<string | null>(null);
  const [engaged, setEngaged] = useState(false);
  const [over, setOver] = useState<PageBox | null>(null);

  const markOf = (box: PageBox) => `${box.id}|${place(box)}`;
  const found = ordered.findIndex(({ box }) => markOf(box) === mark);
  const at = ordered.length === 0 ? -1 : Math.max(found, 0);
  const active = engaged ? (ordered[at]?.box ?? null) : null;

  useEffect(() => {
    if (at < 0 || !engaged) return;
    list.current?.children[at]?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [at, engaged]);

  const go = (to: number | null) => {
    const next = to === null ? undefined : ordered[to];
    if (!next) return;
    setMark(markOf(next.box));
    setEngaged(true);
    onBoxActive?.(next.box.id);
  };

  const onKeyDown = (event: KeyboardEvent) => {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    const rects = ordered.map(({ box }) => box);
    const from = engaged ? at : -1;
    switch (event.key) {
      case "ArrowRight":
        go(Math.min(from + 1, ordered.length - 1));
        break;
      case "ArrowLeft":
        go(Math.max(from - 1, 0));
        break;
      case "ArrowDown":
        go(from < 0 ? at : (nearest(rects, from, 1) ?? from));
        break;
      case "ArrowUp":
        go(from < 0 ? at : (nearest(rects, from, -1) ?? from));
        break;
      case "Home":
        go(0);
        break;
      case "End":
        go(ordered.length - 1);
        break;
      case "PageDown":
      case "PageUp":
        if (!onPage) return;
        onPage(event.key === "PageDown" ? 1 : -1);
        break;
      case "Enter":
      case " ":
        if (!active) return;
        onBoxChoose?.(active.id);
        break;
      case "Escape":
        if (!engaged) return;
        setEngaged(false);
        onBoxActive?.(null);
        break;
      default:
        return;
    }
    event.preventDefault();
  };

  const shown = over ?? active;
  const below = shown !== null && shown.y0 / height < 0.06;
  return (
    <div className="pageview" style={{ aspectRatio: `${width} / ${height}` }}>
      <PageImage key={src} src={src} name={name} explain={explain} deadline={deadline} />
      {ordered.length > 0 ? (
        <div
          ref={list}
          className="pageview-boxes"
          role="listbox"
          tabIndex={0}
          aria-label={`${name}, ${ordered.length} ${ordered.length === 1 ? "box" : "boxes"}`}
          aria-activedescendant={active ? `${base}-${at}` : undefined}
          onKeyDown={onKeyDown}
          onFocus={() => {
            if (at < 0) return;
            setEngaged(true);
            onBoxActive?.(ordered[at]!.box.id);
          }}
          onBlur={() => {
            setEngaged(false);
            onBoxActive?.(null);
          }}
        >
          {ordered.map(({ box, index }, position) => (
            <div
              key={`${box.id}:${index}`}
              id={`${base}-${position}`}
              className="pageview-box"
              role="option"
              aria-label={box.label}
              aria-selected={box.selected === true}
              data-look={box.look ?? "outline"}
              data-box={box.id}
              data-old={box.old ? true : undefined}
              data-active={active === box ? true : undefined}
              data-clickable={onBoxChoose ? true : undefined}
              style={{
                color: box.color,
                zIndex: index,
                left: `${(box.x0 / width) * 100}%`,
                top: `${(box.y0 / height) * 100}%`,
                width: `${(Math.max(box.x1 - box.x0, 0) / width) * 100}%`,
                height: `${(Math.max(box.y1 - box.y0, 0) / height) * 100}%`,
              }}
              onPointerEnter={() => {
                setOver(box);
                onBoxActive?.(box.id);
              }}
              onPointerLeave={() => {
                setOver((now) => (now === box ? null : now));
                onBoxActive?.(active ? active.id : null);
              }}
              onPointerDown={() => setMark(markOf(box))}
              onClick={() => onBoxChoose?.(box.id)}
            />
          ))}
        </div>
      ) : null}
      {shown && shown.label !== "" ? (
        <div
          className="pageview-label"
          aria-hidden="true"
          data-below={below}
          style={{
            left: `${(Math.min(shown.x0, width * 0.7) / width) * 100}%`,
            top: `${((below ? shown.y1 : shown.y0) / height) * 100}%`,
          }}
        >
          {shown.label}
        </div>
      ) : null}
    </div>
  );
}
