// A document's pages in one scroller. Only the pages near the viewport are in the DOM, and
// every page has its place before its image loads, so a long document scrolls evenly.
import {
  memo,
  useCallback,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { Ref } from "react";

import { pageAt, stackPages, visibleRange } from "../lib/windowing.ts";
import type { PageBox } from "./PageView.tsx";
import { PageView } from "./PageView.tsx";

export interface ScrollerPage {
  number: number;
  width: number;
  height: number;
}

export interface PageScrollerHandle {
  /** Bring a page into view; with `y` (in page units), bring that height of it into view. */
  show(page: number, y?: number): void;
}

interface Props {
  ref?: Ref<PageScrollerHandle>;
  pages: readonly ScrollerPage[];
  image: (page: number) => string;
  boxes: (page: number) => readonly PageBox[];
  /** The pages now drawn, so their data can be fetched. */
  onRange?: (first: number, last: number) => void;
  onBoxEnter?: (id: string) => void;
  onBoxLeave?: (id: string) => void;
  onBoxClick?: (id: string) => void;
}

interface SlotProps extends Omit<Props, "ref" | "pages" | "onRange"> {
  page: ScrollerPage;
  top: number;
  height: number;
  width: number;
}

// Scrolling draws the scroller again. A page whose place, image and boxes are the same is
// left alone, and its boxes are worked out once.
const Slot = memo(function Slot(props: SlotProps) {
  const { page, top, height, width, image, boxes, onBoxEnter, onBoxLeave, onBoxClick } = props;
  const list = useMemo(() => boxes(page.number), [boxes, page.number]);
  return (
    <div className="scroller-page" data-page={page.number} style={{ top, height, width }}>
      <PageView
        src={image(page.number)}
        width={page.width}
        height={page.height}
        boxes={list}
        alt={`Page ${page.number}`}
        {...(onBoxEnter ? { onBoxEnter } : {})}
        {...(onBoxLeave ? { onBoxLeave } : {})}
        {...(onBoxClick ? { onBoxClick } : {})}
      />
    </div>
  );
});

interface Seen {
  first: number;
  last: number;
  current: number;
}

const GAP = 20;
const MAX_WIDTH = 920;
const OVERSCAN = 700;

export function PageScroller(props: Props) {
  const { ref, pages, image, boxes, onRange, onBoxEnter, onBoxLeave, onBoxClick } = props;
  const scroller = useRef<HTMLDivElement>(null);
  const [view, setView] = useState({ width: 0, height: 0 });
  // Which pages are drawn and which one the middle of the view is on. Scrolling changes this
  // only when it crosses a page, so most scroll events draw nothing again.
  const [seen, setSeen] = useState<Seen>({ first: 0, last: -1, current: 0 });

  useLayoutEffect(() => {
    const element = scroller.current;
    if (!element) return;
    const measure = () =>
      setView((v) =>
        v.width === element.clientWidth && v.height === element.clientHeight
          ? v
          : { width: element.clientWidth, height: element.clientHeight },
      );
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const pageWidth = Math.max(Math.min(view.width - 2 * GAP, MAX_WIDTH), 0);
  const stack = useMemo(() => stackPages(pages, pageWidth, GAP), [pages, pageWidth]);

  const look = useCallback(() => {
    const top = scroller.current?.scrollTop ?? 0;
    const [first, last] = pageWidth > 0 ? visibleRange(stack, top, view.height, OVERSCAN) : [0, -1];
    const current = pageAt(stack, top + view.height / 2);
    setSeen((s) =>
      s.first === first && s.last === last && s.current === current ? s : { first, last, current },
    );
  }, [stack, pageWidth, view.height]);
  useLayoutEffect(look, [look]);
  const { first, last } = seen;

  const firstNumber = pages[first]?.number;
  const lastNumber = pages[last]?.number;
  useEffect(() => {
    if (firstNumber !== undefined && lastNumber !== undefined) onRange?.(firstNumber, lastNumber);
  }, [firstNumber, lastNumber, onRange]);

  useImperativeHandle(
    ref,
    () => ({
      show(number, y) {
        const element = scroller.current;
        const index = pages.findIndex((p) => p.number === number);
        const page = pages[index];
        if (!element || !page) return;
        const top = stack.tops[index] ?? 0;
        const height = stack.heights[index] ?? 0;
        const target =
          y === undefined ? top - GAP : top + (y / page.height) * height - element.clientHeight / 3;
        element.scrollTo({ top: Math.max(target, 0) });
      },
    }),
    [pages, stack],
  );

  const current = pages[seen.current]?.number;
  const drawn = [];
  for (let index = first; index <= last; index++) {
    const page = pages[index];
    if (!page) continue;
    drawn.push(
      <Slot
        key={page.number}
        page={page}
        top={stack.tops[index] ?? 0}
        height={stack.heights[index] ?? 0}
        width={pageWidth}
        image={image}
        boxes={boxes}
        {...(onBoxEnter ? { onBoxEnter } : {})}
        {...(onBoxLeave ? { onBoxLeave } : {})}
        {...(onBoxClick ? { onBoxClick } : {})}
      />,
    );
  }

  return (
    <div className="scroller-frame">
      <div
        ref={scroller}
        className="scroller"
        tabIndex={0}
        role="group"
        aria-label="Pages"
        onScroll={look}
      >
        <div className="scroller-content" style={{ height: stack.total }}>
          {drawn}
        </div>
      </div>
      {current !== undefined ? (
        <div className="scroller-count" aria-live="off">
          Page {current} of {pages.length}
        </div>
      ) : null}
    </div>
  );
}
