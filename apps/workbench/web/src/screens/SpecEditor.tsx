// Write a spec and see what it extracts from the open document as you type.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, message } from "../api/client.ts";
import type { DocumentRow, ExtractOut, FieldOut, Inspection, SpecRow } from "../api/client.ts";
import { useAnnounce } from "../lib/announce.tsx";
import { useDraft } from "../lib/drafts.ts";
import { fieldLabel, groupFields, outcome } from "../lib/fields.ts";
import type { FieldGroup } from "../lib/fields.ts";
import { formatValue } from "../lib/format.ts";
import { useLiveRun } from "../lib/liveRun.ts";
import { useShortcuts } from "../lib/shortcuts.tsx";
import { Dialog } from "../ui/Dialog.tsx";
import { Editor } from "../ui/Editor.tsx";
import { Failure, Old } from "../ui/Failure.tsx";
import { PageScroller } from "../ui/PageScroller.tsx";
import type { PageScrollerHandle, ScrollerPage } from "../ui/PageScroller.tsx";
import type { PageBox } from "../ui/PageView.tsx";

const STARTER = `name: My spec
fields:
  # A label field reads the value printed after a label.
  number: { label: "Invoice No." }
`;

const TONE: Record<FieldOut["status"], "good" | "warn" | "bad"> = {
  extracted: "good",
  ambiguous: "warn",
  incomplete: "warn",
  unconfirmed: "warn",
  missing: "bad",
  invalid: "bad",
};
const TONE_COLOR = { good: "var(--page-good)", warn: "var(--page-warn)", bad: "var(--page-bad)" };
// A status is never told by colour alone: a cell that is not plainly extracted carries a mark.
const MARK = { good: "", warn: "?", bad: "!" };

const NONE: readonly FieldOut[] = [];
const NO_PAGES: readonly ScrollerPage[] = [];
const NO_SPECS: readonly SpecRow[] = [];

const shownValue = (field: FieldOut) => formatValue(field.value) || field.printed || "";

export function SpecEditor({ document }: { document: DocumentRow }) {
  const announce = useAnnounce();
  const { draft, setDraft, other, loadOther, keepMine, unstored, dismissUnstored } = useDraft(
    document.id,
  );
  const [note, setNote] = useState("");
  const [unsaved, setUnsaved] = useState<string | null>(null);
  const [listOpen, setListOpen] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const scroller = useRef<PageScrollerHandle>(null);
  const results = useRef<HTMLDivElement>(null);

  const loaded = useLiveRun<string, Inspection>(
    document.id,
    () => ({ delay: 0, run: (id, signal) => api.inspect(id, undefined, signal) }),
    [],
  );
  const pages = loaded.shown?.output.pages ?? NO_PAGES;

  const specs = useLiveRun<"all", SpecRow[]>(
    "all",
    () => ({ delay: 0, run: (_, signal) => api.specs(signal) }),
    [],
  );

  // An empty editor runs nothing and shows nothing. While a spec does not load, the last
  // results stay in place, stale, under its problem.
  const blank = draft.text.trim() === "";
  const run = useLiveRun<string, ExtractOut>(
    blank ? null : draft.text,
    () => ({
      delay: 300,
      run: (text, signal) => api.extract(document.id, text, signal),
      keep: (out) => !out.problem,
    }),
    [document.id],
  );
  const fields = run.shown?.output.fields ?? NONE;
  const problem = run.answer?.problem ?? null;
  const stale = run.stale;
  const groups = useMemo(() => groupFields(fields), [fields]);
  const byPath = useMemo(() => new Map(fields.map((f) => [f.path, f])), [fields]);

  // The end of a run is said once: what the spec extracted, or that it has a problem.
  const answer = run.answer;
  useEffect(() => {
    if (!answer) return;
    announce(
      answer.problem
        ? "The spec has a problem. The results are for the earlier text."
        : outcome(groupFields(answer.fields ?? NONE)),
    );
  }, [answer, announce]);

  const select = useCallback(
    (path: string) => {
      setSelected(path);
      const field = byPath.get(path);
      const box = field?.boxes?.[0] ?? field?.candidates?.[0]?.boxes[0];
      if (box) scroller.current?.show(box.page, box.y0);
    },
    [byPath],
  );

  const pickBox = useCallback((path: string) => {
    setSelected(path);
    const row = results.current?.querySelector(`[data-path="${CSS.escape(path)}"]`);
    row?.scrollIntoView({ block: "nearest" });
  }, []);

  const parents = useMemo(
    () => new Set(groups.filter((g) => g.records.length > 0).map((g) => g.field.path)),
    [groups],
  );
  const boxes = useCallback(
    (page: number): PageBox[] => {
      const list: PageBox[] = [];
      const old = stale ? ", for the earlier text" : "";
      for (const field of fields) {
        const mine = field.path === selected;
        // A records field covers its cells, so it is drawn only when it is the one selected.
        if (parents.has(field.path) && !mine) continue;
        const label = `Field ${fieldLabel(field, shownValue(field))}${old}`;
        const color = TONE_COLOR[TONE[field.status]];
        for (const box of field.boxes ?? []) {
          if (box.page !== page) continue;
          const look = mine ? "strong" : field.path === hovered ? "wash" : "outline";
          list.push({ id: field.path, ...box, color, label, look, selected: mine, old: stale });
        }
        if (!mine) continue;
        for (const candidate of field.candidates ?? []) {
          for (const box of candidate.boxes) {
            if (box.page !== page) continue;
            list.push({
              id: field.path,
              ...box,
              color: TONE_COLOR.warn,
              label: `Field ${field.path}, one of the places: ${candidate.printed}${old}`,
              look: "wash",
              old: stale,
            });
          }
        }
      }
      return list;
    },
    [fields, parents, selected, hovered, stale],
  );

  const image = useCallback((page: number) => api.pageImage(document.id, page), [document.id]);

  const refreshSpecs = specs.again;
  const save = async () => {
    const name = draft.name.trim();
    setNote("");
    if (name === "") {
      setUnsaved("Give the spec a name first.");
      return;
    }
    try {
      const text = draft.text;
      await api.saveSpec(name, text);
      setDraft((d) => ({ ...d, base: text }));
      setUnsaved(null);
      setNote(`Saved as ${name}`);
      announce(`Saved as ${name}`);
      refreshSpecs();
    } catch (e) {
      setUnsaved(`Not saved: ${message(e)}`);
    }
  };

  const opened = (spec: { name: string; text: string }) => {
    setDraft({ text: spec.text, name: spec.name, base: spec.text });
    setSelected(null);
    setUnsaved(null);
    setNote(`Opened ${spec.name}`);
    setListOpen(false);
    announce(`Opened ${spec.name}`);
  };

  useShortcuts([
    { key: "mod+s", does: "Save the spec", run: () => void save() },
    { key: "mod+Enter", does: "Run the spec now", run: run.again },
    { key: "]", does: "Next page", run: () => scroller.current?.step(1) },
    { key: "[", does: "Previous page", run: () => scroller.current?.step(-1) },
  ]);

  return (
    <div className="spec">
      <h1 className="visually-hidden">Spec editor for {document.name}</h1>
      <section className="spec-edit" aria-label="Spec">
        <div className="spec-tools">
          <input
            className="field"
            aria-label="Spec name"
            placeholder="Spec name"
            maxLength={80}
            value={draft.name}
            onChange={(event) => {
              const name = event.currentTarget.value;
              setDraft((d) => ({ ...d, name }));
            }}
          />
          <button type="button" className="button primary" onClick={() => void save()}>
            Save
          </button>
          <button type="button" className="button" onClick={() => setListOpen(true)}>
            Saved specs
          </button>
          {unsaved !== null ? (
            <p className="notice failure spec-unsaved" role="alert" data-testid="save-failure">
              {unsaved}
            </p>
          ) : null}
        </div>
        {other !== null ? (
          <div className="bar-note" role="alert" data-testid="other-tab">
            <p>
              Another tab changed the unsaved text of this document. This tab has stopped storing
              its own.
            </p>
            <button type="button" className="button" onClick={loadOther}>
              Load the other tab's text
            </button>
            <button type="button" className="button" onClick={keepMine}>
              Keep this text
            </button>
          </div>
        ) : null}
        {unstored ? (
          <div className="bar-note" role="alert" data-testid="unstored">
            <p>
              The browser cannot store unsaved text. It is kept only while this page stays open.
            </p>
            <button type="button" className="button" onClick={dismissUnstored}>
              Understood
            </button>
          </div>
        ) : null}
        <Editor
          value={draft.text}
          onChange={(text) => setDraft((d) => (d.text === text ? d : { ...d, text }))}
          problem={problem ? { message: problem.message, line: problem.line ?? null } : null}
          label="Spec, in YAML"
          placeholder="name: My spec"
        />
        <p className="quiet spec-foot">
          {note || "Tab indents. Press Escape, then Tab, to leave the editor."}
        </p>
      </section>

      <section className="spec-results" aria-label="Results" ref={results}>
        <div className="results-head">
          <h2>Results</h2>
          <span className="quiet" data-testid="run-status">
            {run.pending ? "Running." : !stale && groups.length > 0 ? outcome(groups) : ""}
          </span>
        </div>
        {loaded.error !== null ? (
          <Failure
            what="The pages could not be loaded"
            why={loaded.error.message}
            again={loaded.again}
            testId="pages-failure"
          />
        ) : null}
        {run.error !== null ? (
          <Failure
            what="The spec could not be run"
            why={run.error.message}
            again={run.again}
            againLabel="Run again"
            testId="run-failure"
          />
        ) : null}
        {problem ? (
          <p className="notice" role="alert" data-testid="spec-problem">
            {problem.line ? `Line ${problem.line}: ` : ""}
            {problem.message}
          </p>
        ) : null}
        {stale ? <Old testId="old-results">These results are for the earlier text.</Old> : null}
        {blank ? (
          <div className="empty results-empty">
            <p>
              Write a spec on the left. Each field it names appears here with its status and value,
              shortly after you stop typing.
            </p>
            <button
              type="button"
              className="button"
              onClick={() => setDraft((d) => ({ ...d, text: STARTER }))}
            >
              Insert a starting spec
            </button>
          </div>
        ) : (
          <ul className="fields" data-stale={stale}>
            {groups.map((group) => (
              <FieldItem
                key={group.field.path}
                group={group}
                selected={selected}
                onSelect={select}
                onHover={setHovered}
              />
            ))}
          </ul>
        )}
      </section>

      <PageScroller
        ref={scroller}
        pages={pages}
        image={image}
        boxes={boxes}
        onBoxActive={setHovered}
        onBoxChoose={pickBox}
        explain={api.whyNot}
      />

      <Dialog title="Saved specs" open={listOpen} onClose={() => setListOpen(false)}>
        <SavedSpecs
          specs={specs.shown?.output ?? NO_SPECS}
          loading={specs.shown === null && specs.pending}
          failure={specs.error?.message ?? null}
          again={refreshSpecs}
          onOpened={opened}
        />
      </Dialog>
    </div>
  );
}

interface SavedProps {
  specs: readonly SpecRow[];
  loading: boolean;
  /** Why the list could not be loaded. What is listed is then from before. */
  failure: string | null;
  again: () => void;
  onOpened: (spec: { name: string; text: string }) => void;
}

/** The saved specs, each with the buttons that open and delete it. */
function SavedSpecs({ specs, loading, failure, again, onOpened }: SavedProps) {
  const announce = useAnnounce();
  const [asking, setAsking] = useState<string | null>(null);
  // The spec whose question was answered with "Keep": the keyboard goes back to its Delete.
  const [kept, setKept] = useState<string | null>(null);
  const [failed, setFailed] = useState<{ name: string; text: string } | null>(null);
  const list = useRef<HTMLUListElement>(null);

  const open = async (name: string) => {
    setFailed(null);
    try {
      onOpened(await api.spec(name));
    } catch (e) {
      setFailed({ name, text: `Not opened: ${message(e)}` });
    }
  };

  const remove = async (name: string) => {
    setFailed(null);
    try {
      await api.deleteSpec(name);
    } catch (e) {
      setFailed({ name, text: `Not deleted: ${message(e)}` });
      return;
    }
    setAsking(null);
    announce(`Deleted ${name}`);
    // The row is gone; the keyboard goes to the list it was in.
    list.current?.focus();
    again();
  };

  return (
    <>
      {failure !== null ? (
        <Failure
          what="The saved specs could not be loaded"
          why={failure}
          again={again}
          testId="specs-failure"
        />
      ) : null}
      {failure !== null && specs.length > 0 ? (
        <Old testId="old-specs">This list is from before the failure.</Old>
      ) : null}
      {loading ? <p className="quiet">Loading the saved specs.</p> : null}
      {!loading && failure === null && specs.length === 0 ? (
        <p className="quiet">No spec is saved yet. Name the spec and press Save.</p>
      ) : null}
      <ul
        className="saved"
        ref={list}
        tabIndex={-1}
        aria-label="Saved specs"
        data-stale={failure !== null}
      >
        {specs.map((spec) => (
          <li key={spec.name} className="saved-row">
            <span className="saved-name">{spec.name}</span>
            {asking === spec.name ? (
              <>
                <span className="quiet">Delete it?</span>
                <button
                  key="yes"
                  type="button"
                  className="button"
                  autoFocus
                  aria-label={`Yes, delete ${spec.name}`}
                  onClick={() => void remove(spec.name)}
                >
                  Delete
                </button>
                <button
                  key="keep"
                  type="button"
                  className="button"
                  aria-label={`Keep ${spec.name}`}
                  onClick={() => {
                    setAsking(null);
                    setKept(spec.name);
                  }}
                >
                  Keep
                </button>
              </>
            ) : (
              <>
                <button
                  key="open"
                  type="button"
                  className="button"
                  aria-label={`Open ${spec.name}`}
                  onClick={() => void open(spec.name)}
                >
                  Open
                </button>
                <button
                  key="delete"
                  type="button"
                  className="button"
                  aria-label={`Delete ${spec.name}`}
                  autoFocus={kept === spec.name}
                  onClick={() => {
                    setFailed(null);
                    setKept(null);
                    setAsking(spec.name);
                  }}
                >
                  Delete
                </button>
              </>
            )}
            {failed?.name === spec.name ? (
              <p className="notice failure saved-failure" role="alert">
                {failed.text}
              </p>
            ) : null}
          </li>
        ))}
      </ul>
    </>
  );
}

interface ItemProps {
  group: FieldGroup;
  selected: string | null;
  onSelect: (path: string) => void;
  onHover: (path: string | null) => void;
}

function FieldItem({ group, selected, onSelect, onHover }: ItemProps) {
  const { field, columns, records } = group;
  const value = formatValue(field.value);
  return (
    <li className="fielditem">
      <button
        type="button"
        className="fieldrow"
        data-path={field.path}
        aria-pressed={selected === field.path}
        onClick={() => onSelect(field.path)}
        onPointerEnter={() => onHover(field.path)}
        onPointerLeave={() => onHover(null)}
        onFocus={() => onHover(field.path)}
        onBlur={() => onHover(null)}
      >
        <span className="fieldrow-top">
          <span className="fieldname">{field.path}</span>
          <span className="tag" data-tone={TONE[field.status]}>
            {field.status}
          </span>
        </span>
        {value !== "" ? <span className="fieldvalue">{value}</span> : null}
        {field.message ? <span className="fieldmessage">{field.message}</span> : null}
        {(field.suggestions ?? []).map((suggestion) => (
          <span key={suggestion} className="fieldmessage">
            Close to it: {suggestion}
          </span>
        ))}
      </button>
      {records.length > 0 ? (
        <div
          className="records-wrap"
          tabIndex={0}
          role="group"
          aria-label={`Records of ${field.path}`}
        >
          <table className="records">
            <thead>
              <tr>
                {columns.map((column) => (
                  <th key={column} scope="col">
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {records.map((cells, r) => (
                <tr key={r}>
                  {cells.map((cell, c) => (
                    <td key={columns[c]}>
                      {cell ? (
                        <button
                          type="button"
                          className="cellbutton"
                          data-path={cell.path}
                          data-tone={TONE[cell.status]}
                          aria-pressed={selected === cell.path}
                          // The whole of it for a screen reader: where the cell is, what it
                          // holds, its status and what the library said about it.
                          aria-label={`${columns[c]}, row ${r + 1}: ${
                            shownValue(cell) || "no value"
                          }, ${cell.status}${cell.message ? `. ${cell.message}` : ""}`}
                          title={
                            cell.status === "extracted" ? undefined : cell.message || cell.status
                          }
                          onClick={() => onSelect(cell.path)}
                        >
                          {MARK[TONE[cell.status]] !== "" ? (
                            <span className="cellmark" aria-hidden="true">
                              {MARK[TONE[cell.status]]}
                            </span>
                          ) : null}
                          {shownValue(cell) || cell.status}
                        </button>
                      ) : null}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </li>
  );
}
