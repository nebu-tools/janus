import { useEffect, useState } from "react";

import logo from "../../../../assets/branding/janus-logo.webp";
import { api, message } from "./api/client.ts";
import type { DocumentRow } from "./api/client.ts";
import { Documents } from "./screens/Documents.tsx";
import { Inspect } from "./screens/Inspect.tsx";
import { SpecEditor } from "./screens/SpecEditor.tsx";
import { Link, NavProvider, useNav } from "./ui/nav.tsx";

export function App() {
  return (
    <NavProvider>
      <Shell />
    </NavProvider>
  );
}

function Shell() {
  const { route } = useNav();
  const document = route.screen === "documents" ? null : route.document;
  const found = useDocument(document);
  const row = found.state === "found" ? found.row : null;
  return (
    <div className="shell">
      <header className="bar">
        <Link to={{ screen: "documents" }} className="brand">
          <img src={logo} alt="" width={30} height={30} />
          <span>Janus workbench</span>
        </Link>
        {document !== null ? (
          <>
            <span className="bar-document" title={row?.name}>
              {row?.name ?? ""}
            </span>
            <nav className="tabs" aria-label="Views of this document">
              <Link
                to={{ screen: "inspect", document }}
                aria-current={route.screen === "inspect" ? "page" : undefined}
              >
                Inspect
              </Link>
              <Link
                to={{ screen: "spec", document }}
                aria-current={route.screen === "spec" ? "page" : undefined}
              >
                Spec editor
              </Link>
            </nav>
          </>
        ) : null}
      </header>
      <main className="main">
        {route.screen === "documents" ? (
          <Documents />
        ) : found.state === "loading" ? null : found.state === "found" &&
          found.row.status === "ready" ? (
          route.screen === "inspect" ? (
            <Inspect key={found.row.id} document={found.row} />
          ) : (
            <SpecEditor key={found.row.id} document={found.row} />
          )
        ) : (
          <NotOpen found={found} />
        )}
      </main>
    </div>
  );
}

type Found =
  | { state: "loading" }
  | { state: "found"; row: DocumentRow }
  | { state: "absent" }
  | { state: "failed"; error: string };

/** The row of the open document. It is asked for again while the document is being read. */
function useDocument(document: string | null): Found {
  const [found, setFound] = useState<Found>({ state: "loading" });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (document === null) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    api.documents(controller.signal).then(
      (rows) => {
        const row = rows.find((r) => r.id === document);
        setFound(row ? { state: "found", row } : { state: "absent" });
        if (row && (row.status === "queued" || row.status === "reading")) {
          timer = setTimeout(() => setTick((t) => t + 1), 800);
        }
      },
      (error: unknown) => {
        if (!controller.signal.aborted) setFound({ state: "failed", error: message(error) });
      },
    );
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [document, tick]);
  const stale = found.state === "found" && found.row.id !== document;
  return document === null || stale ? { state: "loading" } : found;
}

function NotOpen({ found }: { found: Found }) {
  const back = <Link to={{ screen: "documents" }}>Go to the documents</Link>;
  if (found.state === "failed") {
    return (
      <div className="empty">
        <h1>The server did not answer</h1>
        <p>{found.error}</p>
        <p>Check that `janus-workbench serve` is still running, then load this page again.</p>
      </div>
    );
  }
  if (found.state === "found" && found.row.status === "failed") {
    return (
      <div className="empty">
        <h1>This file could not be read</h1>
        <p>{found.row.error}</p>
        <p>{back}</p>
      </div>
    );
  }
  if (found.state === "found") {
    const { pages, pages_read: read = 0 } = found.row;
    return (
      <div className="empty">
        <h1>Janus is reading this document</h1>
        <p>
          {pages ? `${read} of ${pages} pages read.` : "Counting its pages."} It opens here when the
          read ends.
        </p>
        <p>{back}</p>
      </div>
    );
  }
  return (
    <div className="empty">
      <h1>This document is not here</h1>
      <p>It may have been removed. Add it again from the documents.</p>
      <p>{back}</p>
    </div>
  );
}
