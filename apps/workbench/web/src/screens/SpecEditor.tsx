// Write a spec and see what it extracts from the open document as you type.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, message } from "../api/client.ts";
import type { DocumentRow, ExtractOut, FieldOut, PageSummary, SpecRow } from "../api/client.ts";
import { groupFields, tally } from "../lib/fields.ts";
import type { FieldGroup } from "../lib/fields.ts";
import { formatValue } from "../lib/format.ts";
import { liveRun } from "../lib/liveRun.ts";
import { Editor } from "../ui/Editor.tsx";
import { PageScroller } from "../ui/PageScroller.tsx";
import type { PageScrollerHandle } from "../ui/PageScroller.tsx";
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
const TONE_COLOR = { good: "var(--moss)", warn: "var(--marmalade)", bad: "var(--jam)" };

interface Draft {
  text: string;
  name: string;
}
// What was typed for each document, kept while the page stays open.
const drafts = new Map<string, Draft>();
const NONE: readonly FieldOut[] = [];

export function SpecEditor({ document }: { document: DocumentRow }) {
  const [draft, setDraft] = useState<Draft>(
    () => drafts.get(document.id) ?? { text: "", name: "" },
  );
  const [lastAnswer, setAnswer] = useState<ExtractOut | null>(null);
  // While a spec does not load, the last results stay in place under the error.
  const [lastFields, setFields] = useState<readonly FieldOut[]>(NONE);
  const [busy, setRunning] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [pages, setPages] = useState<readonly PageSummary[]>([]);
  const [saved, setSaved] = useState<readonly SpecRow[]>([]);
  const [saveNote, setSaveNote] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const scroller = useRef<PageScrollerHandle>(null);
  const results = useRef<HTMLDivElement>(null);

  useEffect(() => {
    drafts.set(document.id, draft);
  }, [document.id, draft]);

  useEffect(() => {
    api.inspect(document.id).then(
      (inspection) => setPages(inspection.pages),
      (e: unknown) => setFailure(message(e)),
    );
    api.specs().then(setSaved, () => {});
  }, [document.id]);

  const runner = useMemo(
    () =>
      liveRun<string, ExtractOut>({
        delay: 300,
        run: (text, signal) => api.extract(document.id, text, signal),
        onStart: () => setRunning(true),
        onResult: (out) => {
          setAnswer(out);
          if (!out.problem) setFields(out.fields ?? []);
          setFailure(null);
          setRunning(false);
        },
        onError: (e) => {
          setFailure(message(e));
          setRunning(false);
        },
      }),
    [document.id],
  );
  useEffect(() => () => runner.cancel(), [runner]);

  const blank = draft.text.trim() === "";
  useEffect(() => {
    if (blank) runner.cancel();
    else runner.submit(draft.text);
  }, [draft.text, blank, runner]);

  // An empty editor shows nothing, whatever the last run answered.
  const answer = blank ? null : lastAnswer;
  const fields = blank ? NONE : lastFields;
  const running = !blank && busy;
  const problem = answer?.problem ?? null;
  const groups = useMemo(() => groupFields(fields), [fields]);
  const byPath = useMemo(() => new Map(fields.map((f) => [f.path, f])), [fields]);

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
      for (const field of fields) {
        const mine = field.path === selected;
        // A records field covers its cells, so it is drawn only when it is the one selected.
        if (parents.has(field.path) && !mine) continue;
        const label = `${field.path}: ${formatValue(field.value) || field.status}`;
        const color = TONE_COLOR[TONE[field.status]];
        for (const box of field.boxes ?? []) {
          if (box.page !== page) continue;
          const look = mine ? "strong" : field.path === hovered ? "wash" : "outline";
          list.push({ id: field.path, ...box, color, label, look });
        }
        if (!mine) continue;
        for (const candidate of field.candidates ?? []) {
          for (const box of candidate.boxes) {
            if (box.page !== page) continue;
            const text = `${field.path}, one of the places: ${candidate.printed}`;
            list.push({
              id: field.path,
              ...box,
              color: TONE_COLOR.warn,
              label: text,
              look: "wash",
            });
          }
        }
      }
      return list;
    },
    [fields, parents, selected, hovered],
  );

  const image = useCallback((page: number) => api.pageImage(document.id, page), [document.id]);

  const save = async () => {
    const name = draft.name.trim();
    if (name === "") {
      setSaveNote("Give the spec a name first.");
      return;
    }
    try {
      await api.saveSpec(name, draft.text);
      setSaved(await api.specs());
      setSaveNote(`Saved as ${name}`);
    } catch (e) {
      setSaveNote(`Not saved: ${message(e)}`);
    }
  };

  const open = async (name: string) => {
    try {
      const spec = await api.spec(name);
      setDraft({ text: spec.text, name: spec.name });
      setSelected(null);
      setSaveNote("");
    } catch (e) {
      setSaveNote(`Not opened: ${message(e)}`);
    }
  };

  return (
    <div className="spec">
      <section
        className="spec-edit"
        aria-label="Spec"
        onKeyDown={(event) => {
          if ((event.ctrlKey || event.metaKey) && event.key === "s") {
            event.preventDefault();
            void save();
          }
        }}
      >
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
          <select
            className="field"
            aria-label="Open a saved spec"
            value=""
            disabled={saved.length === 0}
            onChange={(event) => void open(event.currentTarget.value)}
          >
            <option value="">{saved.length === 0 ? "No saved specs" : "Open a saved spec"}</option>
            {saved.map((spec) => (
              <option key={spec.name} value={spec.name}>
                {spec.name}
              </option>
            ))}
          </select>
        </div>
        <Editor
          value={draft.text}
          onChange={(text) => setDraft((d) => (d.text === text ? d : { ...d, text }))}
          problem={problem ? { message: problem.message, line: problem.line ?? null } : null}
          label="Spec, in YAML"
          placeholder="name: My spec"
        />
        <p className="quiet spec-foot" role="status">
          {saveNote || "Tab indents. Press Escape, then Tab, to leave the editor."}
        </p>
      </section>

      <section className="spec-results" aria-label="Results" ref={results}>
        <div className="results-head">
          <h2>Results</h2>
          <span className="quiet" role="status">
            {running ? "Running" : groups.length > 0 && !problem ? tally(groups) : ""}
          </span>
        </div>
        {failure !== null ? (
          <p className="notice" role="alert">
            The spec could not be run: {failure}
          </p>
        ) : null}
        {problem ? (
          <p className="notice" role="alert" data-testid="spec-problem">
            {problem.line ? `Line ${problem.line}: ` : ""}
            {problem.message}
          </p>
        ) : null}
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
          <ul className="fields" data-stale={problem !== null || failure !== null}>
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

      <PageScroller ref={scroller} pages={pages} image={image} boxes={boxes} onBoxClick={pickBox} />
    </div>
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
        <div className="records-wrap">
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
                          title={
                            cell.status === "extracted" ? undefined : cell.message || cell.status
                          }
                          onClick={() => onSelect(cell.path)}
                        >
                          {formatValue(cell.value) || cell.printed || cell.status}
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
