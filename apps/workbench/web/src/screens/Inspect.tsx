// What Janus read from a document: its pages with words, lines, headings and tables drawn on
// them, the tables with their first rows, and every place a searched phrase is printed.
import { useCallback, useEffect, useRef, useState } from "react";

import { api, message } from "../api/client.ts";
import type { DocumentRow, Hit, Inspection, PageLayout } from "../api/client.ts";
import { useLiveRun } from "../lib/liveRun.ts";
import { PageScroller } from "../ui/PageScroller.tsx";
import type { PageScrollerHandle } from "../ui/PageScroller.tsx";
import type { PageBox } from "../ui/PageView.tsx";

const LAYERS = [
  { key: "words", name: "Words", color: "var(--layer-words)" },
  { key: "lines", name: "Lines", color: "var(--layer-lines)" },
  { key: "headings", name: "Headings", color: "var(--layer-headings)" },
  { key: "tables", name: "Tables", color: "var(--layer-tables)" },
  { key: "cells", name: "Table cells", color: "var(--layer-cells)" },
] as const;

type LayerKey = (typeof LAYERS)[number]["key"];
const COLOR = Object.fromEntries(LAYERS.map((l) => [l.key, l.color])) as Record<LayerKey, string>;
const HIT_COLOR = "var(--layer-hits)";
const NO_HITS: readonly Hit[] = [];

export function Inspect({ document }: { document: DocumentRow }) {
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [layouts, setLayouts] = useState<ReadonlyMap<number, PageLayout>>(new Map());
  const [shown, setShown] = useState<ReadonlySet<LayerKey>>(new Set(["headings", "tables"]));
  const [query, setQuery] = useState("");
  // The hit chosen in the list, and the list it was chosen in. Another list has none chosen.
  const [pick, setPick] = useState<{ hits: readonly Hit[]; index: number } | null>(null);
  const scroller = useRef<PageScrollerHandle>(null);
  const asked = useRef(new Set<number>());

  useEffect(() => {
    api.inspect(document.id).then(setInspection, (e: unknown) => setError(message(e)));
  }, [document.id]);

  const onRange = useCallback(
    (first: number, last: number) => {
      for (let page = first; page <= last; page++) {
        if (asked.current.has(page)) continue;
        asked.current.add(page);
        api.pageLayout(document.id, page).then(
          (layout) => setLayouts((current) => new Map(current).set(page, layout)),
          () => asked.current.delete(page),
        );
      }
    },
    [document.id],
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
  const boxes = useCallback(
    (page: number): PageBox[] => {
      const list: PageBox[] = [];
      const layout = layouts.get(page);
      if (layout) {
        if (shown.has("tables")) {
          for (const t of layout.tables) {
            const label = `Table ${t.id}, ${t.rows} rows, ${t.cols} columns`;
            list.push({ id: `table:${t.id}`, ...t.box, color: COLOR.tables, label, look: "wash" });
          }
        }
        if (shown.has("cells")) {
          for (const c of layout.cells) {
            const label = `${c.table_id} row ${c.row}, column ${c.col}`;
            list.push({ id: `cell:${label}`, ...c.box, color: COLOR.cells, label });
          }
        }
        if (shown.has("lines")) {
          layout.lines.forEach((line, i) => {
            const set = `${line.size ?? "?"} pt${line.bold ? ", bold" : ""}`;
            list.push({ id: `line:${i}`, ...line.box, color: COLOR.lines, label: `Line, ${set}` });
          });
        }
        if (shown.has("words")) {
          layout.words.forEach((word, i) => {
            list.push({ id: `word:${i}`, ...word.box, color: COLOR.words, label: word.text });
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
        const label = `${hit.text} (${where(hit)})${old === null ? "" : `, ${old}`}`;
        const look = i === picked ? "strong" : "wash";
        list.push({ id: `hit:${i}`, ...hit.box, color: HIT_COLOR, label, look, old: old !== null });
      });
      return list;
    },
    [layouts, shown, inspection, hits, picked, old],
  );

  const image = useCallback((page: number) => api.pageImage(document.id, page), [document.id]);

  if (error !== null && inspection === null) {
    return (
      <div className="empty">
        <h1>This document could not be opened</h1>
        <p>{error}</p>
      </div>
    );
  }
  if (inspection === null) return null;

  const toggle = (key: LayerKey) =>
    setShown((current) => {
      const next = new Set(current);
      if (!next.delete(key)) next.add(key);
      return next;
    });

  return (
    <div className="inspect">
      <PageScroller
        ref={scroller}
        pages={inspection.pages}
        image={image}
        boxes={boxes}
        onRange={onRange}
      />
      <aside className="side" aria-label="What Janus read">
        <p className="quiet side-summary">
          {count(inspection.pages.length, "page")}, {count(inspection.tables.length, "table")}, read
          with {inspection.engine}.
        </p>

        <section className="side-section">
          <h2 id="find-title">Find a phrase</h2>
          <input
            type="search"
            className="field"
            aria-labelledby="find-title"
            placeholder="Total due"
            value={query}
            onChange={(event) => setQuery(event.currentTarget.value)}
          />
          {search.error !== null ? (
            <p className="notice find-error" role="alert">
              The search for "{phrase}" failed: {search.error.message}
            </p>
          ) : null}
          <p className="quiet find-status" role="status">
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
            <p className="old-label" data-testid="old-hits">
              {count(hits.length, "place")} {old}.
            </p>
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
                    onClick={() => scroller.current?.show(table.page)}
                  >
                    <code>{table.id}</code>
                    <span className="quiet">
                      page {table.page}, {table.rows} rows, {table.cols} columns
                    </span>
                  </button>
                  <div className="preview-wrap">
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
      </aside>
    </div>
  );
}

const where = (hit: Hit) => {
  const unit = hit.cell === null ? "line" : "cell";
  return hit.starts_line ? `begins its ${unit}` : `inside a ${unit}`;
};

const count = (n: number, noun: string) => `${n} ${noun}${n === 1 ? "" : "s"}`;
