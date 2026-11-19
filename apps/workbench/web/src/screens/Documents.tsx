// The documents the workbench holds. PDFs are added here and read by the server.
import { useEffect, useRef, useState } from "react";
import type { DragEvent } from "react";

import { api, message } from "../api/client.ts";
import type { DocumentRow } from "../api/client.ts";
import { useAnnounce } from "../lib/announce.tsx";
import { formatBytes, formatSeconds } from "../lib/format.ts";
import { useLiveRun } from "../lib/liveRun.ts";
import { Failure, Old } from "../ui/Failure.tsx";
import { Link } from "../ui/nav.tsx";

const active = (row: DocumentRow) => row.status === "queued" || row.status === "reading";
const files = (n: number) => `${n} ${n === 1 ? "file" : "files"}`;

export function Documents() {
  const announce = useAnnounce();
  const list = useLiveRun<"all", DocumentRow[]>(
    "all",
    () => ({ delay: 0, run: (_, signal) => api.documents(signal) }),
    [],
  );
  const rows = list.shown?.output ?? null;
  const [problems, setProblems] = useState<readonly string[]>([]);
  const [unremoved, setUnremoved] = useState<ReadonlyMap<string, string>>(new Map());
  const [sending, setSending] = useState(0);
  const [dragging, setDragging] = useState(false);
  const chooser = useRef<HTMLInputElement>(null);
  const choose = useRef<HTMLButtonElement>(null);
  const table = useRef<HTMLTableElement>(null);
  const depth = useRef(0);

  // One status call covers every document. It repeats only while one is being read, and stops
  // after a failure until the person asks again.
  const reading = rows?.some(active) ?? false;
  const { again, pending, error } = list;
  useEffect(() => {
    if (!reading || error !== null || pending) return;
    const timer = setTimeout(again, 600);
    return () => clearTimeout(timer);
  }, [reading, error, pending, again]);

  // A read that ended is said once, by name.
  const before = useRef(new Map<string, DocumentRow["status"]>());
  useEffect(() => {
    if (!rows) return;
    const ended: string[] = [];
    for (const row of rows) {
      const was = before.current.get(row.id);
      if ((was === "queued" || was === "reading") && row.status === "ready") {
        ended.push(`${row.name} is ready`);
      }
      if ((was === "queued" || was === "reading") && row.status === "failed") {
        ended.push(`${row.name} could not be read`);
      }
    }
    before.current = new Map(rows.map((row) => [row.id, row.status]));
    if (ended.length > 0) announce(ended.join(". "));
  }, [rows, announce]);

  const add = async (chosen: File[]) => {
    if (chosen.length === 0) return;
    setProblems([]);
    setSending((n) => n + chosen.length);
    const failed: string[] = [];
    for (const file of chosen) {
      try {
        await api.addDocument(file);
      } catch (e) {
        failed.push(`${file.name} was not added: ${message(e)}`);
      }
      setSending((n) => n - 1);
      again();
    }
    setProblems(failed);
    const added = chosen.length - failed.length;
    if (added > 0) announce(`${files(added)} added`);
  };

  const remove = async (row: DocumentRow) => {
    setUnremoved((now) => without(now, row.id));
    try {
      await api.deleteDocument(row.id);
    } catch (e) {
      setUnremoved((now) => new Map(now).set(row.id, message(e)));
      return;
    }
    // The keyboard stays in the list: on the row that takes this one's place, or the one above.
    const buttons = [...(table.current?.querySelectorAll<HTMLElement>("[data-remove]") ?? [])];
    const at = buttons.findIndex((b) => b.dataset.remove === row.id);
    (buttons[at + 1] ?? buttons[at - 1] ?? choose.current)?.focus();
    announce(`${row.name} removed`);
    again();
  };

  const hasFiles = (event: DragEvent) => event.dataTransfer.types.includes("Files");
  const drop = {
    onDragEnter: (event: DragEvent) => {
      if (!hasFiles(event)) return;
      depth.current++;
      setDragging(true);
    },
    onDragLeave: (event: DragEvent) => {
      if (!hasFiles(event)) return;
      depth.current = Math.max(depth.current - 1, 0);
      if (depth.current === 0) setDragging(false);
    },
    onDragOver: (event: DragEvent) => {
      if (hasFiles(event)) event.preventDefault();
    },
    onDrop: (event: DragEvent) => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      depth.current = 0;
      setDragging(false);
      void add([...event.dataTransfer.files]);
    },
  };

  return (
    <div className="documents" data-dragging={dragging} {...drop}>
      <div className="documents-head">
        <h1>Documents</h1>
        <span className="quiet">{sending > 0 ? `Sending ${files(sending)}` : ""}</span>
        <input
          ref={chooser}
          type="file"
          accept="application/pdf,.pdf"
          multiple
          hidden
          onChange={(event) => {
            void add([...(event.currentTarget.files ?? [])]);
            event.currentTarget.value = "";
          }}
        />
        <button
          ref={choose}
          type="button"
          className="button primary"
          onClick={() => chooser.current?.click()}
        >
          Choose PDFs
        </button>
      </div>
      {problems.length > 0 ? (
        <div className="notice failure" role="alert" data-testid="upload-failure">
          {problems.map((problem) => (
            <p key={problem}>{problem}</p>
          ))}
        </div>
      ) : null}
      {error !== null ? (
        <Failure
          what="The list could not be loaded"
          why={error.message}
          again={again}
          testId="list-failure"
        />
      ) : null}
      {list.stale && error !== null ? (
        <Old testId="old-list">This list is from before the failure.</Old>
      ) : null}
      {rows === null ? (
        error === null ? (
          <p className="quiet documents-foot">Loading the list.</p>
        ) : null
      ) : rows.length === 0 ? (
        <div className="empty dropzone">
          <h2>No documents yet</h2>
          <p>
            Drop a PDF anywhere on this page, or choose one. Janus reads it and lists it here. Then
            open it to see its words, lines and tables.
          </p>
        </div>
      ) : (
        <table className="doctable" ref={table} data-stale={list.stale && error !== null}>
          <caption className="visually-hidden">Documents, the last one added first</caption>
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col" className="num">
                Pages
              </th>
              <th scope="col" className="num">
                Tables
              </th>
              <th scope="col">Engine</th>
              <th scope="col" className="num">
                Read in
              </th>
              <th scope="col">Status</th>
              <th scope="col">
                <span className="visually-hidden">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <Row
                key={row.id}
                row={row}
                unremoved={unremoved.get(row.id) ?? null}
                onRemove={() => void remove(row)}
              />
            ))}
          </tbody>
        </table>
      )}
      {rows !== null && rows.length > 0 ? (
        <p className="quiet documents-foot">Drop more PDFs anywhere on this page.</p>
      ) : null}
      {dragging ? <div className="dropveil">Drop to add</div> : null}
    </div>
  );
}

function without<K, V>(map: ReadonlyMap<K, V>, key: K): ReadonlyMap<K, V> {
  if (!map.has(key)) return map;
  const next = new Map(map);
  next.delete(key);
  return next;
}

interface RowProps {
  row: DocumentRow;
  /** Why the last try to remove it failed. */
  unremoved: string | null;
  onRemove: () => void;
}

function Row({ row, unremoved, onRemove }: RowProps) {
  const status = row.status ?? "queued";
  const read = row.pages_read ?? 0;
  return (
    <tr data-status={status}>
      <th scope="row">
        {status === "ready" ? (
          <Link to={{ screen: "inspect", document: row.id }} className="docname">
            {row.name}
          </Link>
        ) : (
          <span className="docname">{row.name}</span>
        )}
        <span className="quiet docsize">{formatBytes(row.size)}</span>
        {status === "failed" ? <span className="docerror">{row.error}</span> : null}
      </th>
      <td className="num">{row.pages ?? ""}</td>
      <td className="num">{row.tables ?? ""}</td>
      <td>{row.engine ?? ""}</td>
      <td className="num">
        {typeof row.read_seconds === "number" ? formatSeconds(row.read_seconds) : ""}
      </td>
      <td className="status">
        {status === "ready" ? (
          <span className="state" data-tone="good">
            Ready
          </span>
        ) : status === "failed" ? (
          <span className="state" data-tone="bad">
            Failed
          </span>
        ) : status === "queued" ? (
          <span className="state">Waiting</span>
        ) : (
          <span className="progress">
            <progress
              max={row.pages ?? 1}
              value={row.pages ? read : 0}
              aria-label={`Pages of ${row.name} read`}
            />
            <span className="quiet">
              {row.pages ? `${read} of ${row.pages} pages` : "Counting pages"}
            </span>
          </span>
        )}
      </td>
      <td className="actions">
        {status === "ready" ? (
          <Link
            to={{ screen: "spec", document: row.id }}
            className="button"
            aria-label={`Write a spec for ${row.name}`}
          >
            Write a spec
          </Link>
        ) : null}
        <button
          type="button"
          className="button"
          data-remove={row.id}
          onClick={onRemove}
          aria-label={`Remove ${row.name}`}
        >
          Remove
        </button>
        {unremoved !== null ? (
          <p className="rowerror" role="alert">
            Not removed: {unremoved}
          </p>
        ) : null}
      </td>
    </tr>
  );
}
