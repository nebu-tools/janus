// The documents the workbench holds. PDFs are added here and read by the server.
import { useCallback, useEffect, useRef, useState } from "react";
import type { DragEvent } from "react";

import { api, message } from "../api/client.ts";
import type { DocumentRow } from "../api/client.ts";
import { formatBytes, formatSeconds } from "../lib/format.ts";
import { Link } from "../ui/nav.tsx";

const active = (row: DocumentRow) => row.status === "queued" || row.status === "reading";

export function Documents() {
  const [rows, setRows] = useState<DocumentRow[] | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [sending, setSending] = useState(0);
  const [dragging, setDragging] = useState(false);
  const chooser = useRef<HTMLInputElement>(null);
  const depth = useRef(0);

  const refresh = useCallback(
    () =>
      api.documents().then(setRows, (error: unknown) => {
        setNotice(`The list could not be loaded: ${message(error)}`);
        setRows((current) => current ?? []);
      }),
    [],
  );

  // One status call covers every document. It repeats only while one is being read.
  const reading = rows?.some(active) ?? false;
  useEffect(() => {
    const first = setTimeout(refresh, 0);
    const timer = reading ? setInterval(refresh, 600) : undefined;
    return () => {
      clearTimeout(first);
      clearInterval(timer);
    };
  }, [reading, refresh]);

  const add = async (files: File[]) => {
    if (files.length === 0) return;
    setNotice(null);
    setSending((n) => n + files.length);
    const problems: string[] = [];
    for (const file of files) {
      try {
        await api.addDocument(file);
      } catch (error) {
        problems.push(`${file.name}: ${message(error)}`);
      }
      setSending((n) => n - 1);
      await refresh();
    }
    if (problems.length > 0) setNotice(problems.join("\n"));
  };

  const remove = async (row: DocumentRow) => {
    try {
      await api.deleteDocument(row.id);
    } catch (error) {
      setNotice(`${row.name} could not be removed: ${message(error)}`);
    }
    await refresh();
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
        <span className="quiet" role="status">
          {sending > 0 ? `Sending ${sending} ${sending === 1 ? "file" : "files"}` : ""}
        </span>
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
        <button type="button" className="button primary" onClick={() => chooser.current?.click()}>
          Choose PDFs
        </button>
      </div>
      {notice !== null ? (
        <p className="notice" role="alert">
          {notice}
        </p>
      ) : null}
      {rows === null ? null : rows.length === 0 ? (
        <div className="empty dropzone">
          <h2>No documents yet</h2>
          <p>
            Drop a PDF anywhere on this page, or choose one. Janus reads it and lists it here. Then
            open it to see its words, lines and tables.
          </p>
        </div>
      ) : (
        <table className="doctable">
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
              <Row key={row.id} row={row} onRemove={() => void remove(row)} />
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

function Row({ row, onRemove }: { row: DocumentRow; onRemove: () => void }) {
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
            <progress max={row.pages ?? 1} value={row.pages ? read : 0} aria-label="Pages read" />
            <span className="quiet">
              {row.pages ? `${read} of ${row.pages} pages` : "Counting pages"}
            </span>
          </span>
        )}
      </td>
      <td className="actions">
        {status === "ready" ? (
          <Link to={{ screen: "spec", document: row.id }} className="button">
            Write a spec
          </Link>
        ) : null}
        <button
          type="button"
          className="button"
          onClick={onRemove}
          aria-label={`Remove ${row.name}`}
        >
          Remove
        </button>
      </td>
    </tr>
  );
}
