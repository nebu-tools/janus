// What Janus read from a document: its pages with words, lines, headings and tables drawn on
// them, the tables with their first rows, and every place a searched phrase is printed.
import { useCallback, useEffect, useRef, useState } from "react";

import { api, message } from "../api/client.ts";
import type { Box, DocumentRow, Hit, Inspection, PageLayout } from "../api/client.ts";
import { useAnnounce } from "../lib/announce.tsx";
import { useLiveRun } from "../lib/liveRun.ts";
import { useShortcuts } from "../lib/shortcuts.tsx";
import { Failure, Old } from "../ui/Failure.tsx";
import { PageScroller } from "../ui/PageScroller.tsx";
import type { PageScrollerHandle } from "../ui/PageScroller.tsx";
import type { PageBox } from "../ui/PageView.tsx";

const LAYERS = [
  { key: "words", name: "Words", color: "var(--page-words)" },
  { key: "lines", name: "Lines", color: "var(--page-lines)" },
  { key: "headings", name: "Headings", color: "var(--page-headings)" },
  { key: "tables", name: "Tables", color: "var(--page-tables)" },
  { key: "cells", name: "Table cells", color: "var(--page-cells)" },
] as const;

type LayerKey = (typeof LAYERS)[number]["key"];
const COLOR = Object.fromEntries(LAYERS.map((l) => [l.key, l.color])) as Record<LayerKey, string>;
const HIT_COLOR = "var(--page-hits)";
const NO_HITS: readonly Hit[] = [];

export function Inspect({ document }: { document: DocumentRow }) {
  const announce = useAnnounce();
  const loaded = useLiveRun<string, Inspection>(
    document.id,
    () => ({ delay: 0, run: (id, signal) => api.inspect(id, undefined, signal) }),
    [],
  );
  const inspection = loaded.shown?.output ?? null;
  const [layouts, setLayouts] = useState<ReadonlyMap<number, PageLayout>>(new Map());
  // The pages whose boxes did not load, and why the last of them did not.
  const [unread, setUnread] = useState<{ pages: readonly number[]; why: string } | null>(null);
  const [shown, setShown] = useState<ReadonlySet<LayerKey>>(new Set(["headings", "tables"]));
  const [query, setQuery] = useState("");
  // The hit chosen in the list, and the list it was chosen in. Another list has none chosen.
  const [pick, setPick] = useState<{ hits: readonly Hit[]; index: number } | null>(null);
  const scroller = useRef<PageScrollerHandle>(null);
  const field = useRef<HTMLInputElement>(null);
  const asked = useRef(new Set<number>());

  const layout = useCallback(
    (page: number) => {
      if (asked.current.has(page)) return;
      asked.current.add(page);
      api.pageLayout(document.id, page).then(
        (answer) => setLayouts((current) => new Map(current).set(page, answer)),
        (e: unknown) => {
          asked.current.delete(page);
          setUnread((now) => ({
            pages: [...new Set([...(now?.pages ?? []), page])].sort((a, b) => a - b),
            why: message(e),
          }));
        },
      );
    },
    [document.id],
  );

  const onRange = useCallback(
    (first: number, last: number) => {
      for (let page = first; page <= last; page++) layout(page);
    },
    [layout],
  );

  const phrase = query.trim();
  const search = useLiveRun<string, Inspection>(
    phrase === "" ? null : phrase,
    () => ({ delay: 200, run: (text, signal) => api.inspect(document.id, text, signal) }),
    [document.id],
  );
  const hits = search.shown?.output.hits ?? NO_HITS;
  const picked = pick?.hits === hits ? pick.index : null;
  // Hits kept from an earlier phrase, while the phrase typed runs or after it failed.
  const old = search.stale ? `for the earlier phrase "${search.shown?.input}"` : null;

  // The end of a search is said once: how many places, or none.
  const answered = search.answer;
  useEffect(() => {
    if (!answered) return;
    const n = answered.hits?.length ?? 0;
    announce(n === 0 ? "Nothing prints the phrase" : `${count(n, "place")} found`);
  }, [answered, announce]);

  const choose = useCallback(
    (index: number) => {
      const hit = hits[index];
      if (!hit || old !== null) return;
      setPick({ hits, index });
      scroller.current?.show(hit.page, hit.box.y0);
      announce(`Place ${index + 1} of ${hits.length}, page ${hit.page}: ${hit.text}`);
    },
    [hits, old, announce],
  );
  const step = (delta: number) => {
    if (hits.length === 0) return;
    choose(picked === null ? (delta > 0 ? 0 : hits.length - 1) : wrap(picked + delta, hits.length));
  };

  useShortcuts([
    { key: "/", does: "Go to the phrase field", run: () => field.current?.focus() },
    { key: "n", does: "Next place the phrase is printed", run: () => step(1) },
    { key: "p", does: "Previous place the phrase is printed", run: () => step(-1) },
    { key: "]", does: "Next page", run: () => scroller.current?.step(1) },
    { key: "[", does: "Previous page", run: () => scroller.current?.step(-1) },
  ]);

  const boxes = useCallback(
    (page: number): PageBox[] => {
      const list: PageBox[] = [];
      const read = layouts.get(page);
      if (read) {
        const words = read.words;
        const printed = (box: Box) => {
          const text = words
            .filter((w) => inside(w.box, box))
            .map((w) => w.text)
            .join(" ");
          return text === "" ? "empty" : text;
        };
        if (shown.has("tables")) {
          for (const t of read.tables) {
            const label = `Table ${t.id}, ${t.rows} rows, ${t.cols} columns`;
            list.push({ id: `table:${t.id}`, ...t.box, color: COLOR.tables, label, look: "wash" });
          }
        }
        if (shown.has("cells")) {
          for (const c of read.cells) {
            const at = `${c.table_id} row ${c.row}, column ${c.col}`;
            const label = `Cell, row ${c.row}, column ${c.col} of ${c.table_id}: ${printed(c.box)}`;
            list.push({ id: `cell:${at}`, ...c.box, color: COLOR.cells, label });
          }
        }
        if (shown.has("lines")) {
          read.lines.forEach((line, i) => {
            const set = `${line.size ?? "?"} pt${line.bold ? ", bold" : ""}`;
            const label = `Line, ${set}: ${printed(line.box)}`;
            list.push({ id: `line:${i}`, ...line.box, color: COLOR.lines, label });
          });
        }
        if (shown.has("words")) {
          words.forEach((word, i) => {
            const label = `Word: ${word.text}`;
            list.push({ id: `word:${i}`, ...word.box, color: COLOR.words, label });
          });
        }
      }
      if (shown.has("headings")) {
        inspection?.headings.forEach((h, i) => {
          if (h.page !== page) return;
          const label = `Heading, ${h.size} pt: ${h.text}`;
          list.push({ id: `heading:${i}`, ...h.box, color: COLOR.headings, label, look: "wash" });
        });
      }
      hits.forEach((hit, i) => {
        if (hit.page !== page) return;
        const label = `Phrase: ${hit.text}, ${where(hit)}${old === null ? "" : `, ${old}`}`;
        list.push({
          id: `hit:${i}`,
          ...hit.box,
          color: HIT_COLOR,
          label,
          look: i === picked ? "strong" : "wash",
          selected: i === picked,
          old: old !== null,
        });
      });
      return list;
    },
    [layouts, shown, inspection, hits, picked, old],
  );

  // Choosing a phrase box on a page chooses its place in the list.
  const onBoxChoose = useCallback(
    (id: string) => {
      if (id.startsWith("hit:")) choose(Number(id.slice(4)));
    },
    [choose],
  );

  const image = useCallback((page: number) => api.pageImage(document.id, page), [document.id]);

  if (inspection === null) {
    return (
      <div className="empty">
        <h1>Inspect {document.name}</h1>
        {loaded.error !== null ? (
          <Failure
            what="This document could not be opened"
            why={loaded.error.message}
            again={loaded.again}
            testId="inspection-failure"
          />
        ) : (
          <p>Opening the document.</p>
        )}
      </div>
    );
  }

  const toggle = (key: LayerKey) =>
    setShown((current) => {
      const next = new Set(current);
      if (!next.delete(key)) next.add(key);
      return next;
    });

  return (
    <div className="inspect">
      <h1 className="visually-hidden">Inspect {document.name}</h1>
      <PageScroller
        ref={scroller}
        pages={inspection.pages}
        image={image}
        boxes={boxes}
        onRange={onRange}
        onBoxChoose={onBoxChoose}
        explain={api.whyNot}
      />
      <section className="side" aria-label="What Janus read">
        <p className="quiet side-summary">
          {count(inspection.pages.length, "page")}, {count(inspection.tables.length, "table")}, read
          with {inspection.engine}.
        </p>

        <section className="side-section">
          <h2 id="find-title">Find a phrase</h2>
          <input
            ref={field}
            type="search"
            className="field"
            aria-labelledby="find-title"
            aria-describedby="find-status"
            placeholder="Total due"
            value={query}
            onChange={(event) => setQuery(event.currentTarget.value)}
          />
          {search.error !== null ? (
            <Failure
              what={`The search for "${phrase}" failed`}
              why={search.error.message}
              again={search.again}
              againLabel="Search again"
              testId="find-error"
            />
          ) : null}
          <p className="quiet find-status" id="find-status">
            {phrase === ""
              ? "Shows every line and cell that prints the phrase."
              : search.pending
                ? "Searching"
                : search.error !== null
                  ? ""
                  : hits.length === 0
                    ? `Nothing prints "${phrase}". A label locator would not find it.`
                    : `${count(hits.length, "place")}. A label locator needs the phrase to begin its line or cell.`}
          </p>
          {old !== null ? (
            <Old testId="old-hits">
              {count(hits.length, "place")} {old}.
            </Old>
          ) : null}
          {hits.length > 0 ? (
            <ol className="hits" data-stale={search.stale}>
              {hits.map((hit, i) => (
                <li key={i}>
                  <button
                    type="button"
                    className="hit"
                    aria-pressed={i === picked}
                    onClick={() => {
                      setPick({ hits, index: i });
                      scroller.current?.show(hit.page, hit.box.y0);
                    }}
                  >
                    <span className="hit-text">{hit.text}</span>
                    <span className="hit-where">
                      <span>Page {hit.page}</span>
                      <span className="tag" data-tone={hit.starts_line ? "good" : "warn"}>
                        {where(hit)}
                      </span>
                      {hit.cell !== null ? <code>{hit.cell}</code> : null}
                    </span>
                  </button>
                </li>
              ))}
            </ol>
          ) : null}
        </section>

        <section className="side-section">
          <h2>Draw on the pages</h2>
          <ul className="layers">
            {LAYERS.map((layer) => (
              <li key={layer.key}>
                <label className="layer">
                  <input
                    type="checkbox"
                    checked={shown.has(layer.key)}
                    onChange={() => toggle(layer.key)}
                  />
                  <span className="swatch" style={{ color: layer.color }} />
                  {layer.name}
                </label>
              </li>
            ))}
          </ul>
          {unread !== null ? (
            <Failure
              what={`The boxes of ${pagesNamed(unread.pages)} could not be loaded`}
              why={unread.why}
              again={() => {
                const { pages } = unread;
                setUnread(null);
                pages.forEach(layout);
              }}
              againLabel="Load them again"
              testId="layout-failure"
            />
          ) : null}
        </section>

        <section className="side-section">
          <h2>Tables</h2>
          {inspection.tables.length === 0 ? (
            <p className="quiet">
              Janus found no ruled table. A <code>records</code> field can still read rows that line
              up under a header.
            </p>
          ) : (
            <ul className="tables">
              {inspection.tables.map((table) => (
                <li key={table.id} className="tablecard">
                  <button
                    type="button"
                    className="tablecard-head"
                    onClick={() => {
                      scroller.current?.show(table.page);
                      announce(`Page ${table.page} of ${inspection.pages.length}`);
                    }}
                  >
                    <code>{table.id}</code>
                    <span className="quiet">
                      page {table.page}, {table.rows} rows, {table.cols} columns
                    </span>
                  </button>
                  <div
                    className="preview-wrap"
                    tabIndex={0}
                    role="group"
                    aria-label={`First rows of ${table.id}`}
                  >
                    <table className="preview">
                      <tbody>
                        {table.preview.map((cells, r) => (
                          <tr key={r}>
                            {cells.map((cell, c) => (
                              <td key={c}>{cell}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </section>
    </div>
  );
}

const where = (hit: Hit) => {
  const unit = hit.cell === null ? "line" : "cell";
  return hit.starts_line ? `begins its ${unit}` : `inside a ${unit}`;
};

const count = (n: number, noun: string) => `${n} ${noun}${n === 1 ? "" : "s"}`;
const wrap = (index: number, length: number) => ((index % length) + length) % length;
const pagesNamed = (pages: readonly number[]) =>
  pages.length === 1 ? `page ${pages[0]}` : `pages ${pages.join(", ")}`;

/** Whether the middle of `inner` lies in `outer`. */
function inside(inner: Box, outer: Box): boolean {
  const x = (inner.x0 + inner.x1) / 2;
  const y = (inner.y0 + inner.y1) / 2;
  return x >= outer.x0 && x <= outer.x1 && y >= outer.y0 && y <= outer.y1;
}
