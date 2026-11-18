import { useEffect, useRef, useState } from "react";

import logo from "../../../../assets/branding/janus-logo.webp";
import { api } from "./api/client.ts";
import type { DocumentRow } from "./api/client.ts";
import { Announcer } from "./lib/announce.tsx";
import { useLiveRun } from "./lib/liveRun.ts";
import { keyName, ShortcutsProvider, useShortcutList, useShortcuts } from "./lib/shortcuts.tsx";
import { Documents } from "./screens/Documents.tsx";
import { Inspect } from "./screens/Inspect.tsx";
import { SpecEditor } from "./screens/SpecEditor.tsx";
import { Dialog } from "./ui/Dialog.tsx";
import { Failure } from "./ui/Failure.tsx";
import { Link, NavProvider, useNav } from "./ui/nav.tsx";

export function App() {
  return (
    <NavProvider>
      <ShortcutsProvider>
        <Shell />
      </ShortcutsProvider>
    </NavProvider>
  );
}

const SCREEN = { documents: "Documents", inspect: "Inspect", spec: "Spec editor" };

function Shell() {
  const { route } = useNav();
  const document = route.screen === "documents" ? null : route.document;
  const found = useDocument(document);
  const row = found.state === "found" ? found.row : null;
  const main = useRef<HTMLElement>(null);
  const [help, setHelp] = useState(false);

  useShortcuts([{ key: "?", does: "Show this list", run: () => setHelp(true) }]);

  // A new screen has a new title, and the keyboard starts at its top. The first screen leaves
  // focus where the browser put it.
  const name = row?.name;
  useEffect(() => {
    window.document.title = `${SCREEN[route.screen]}${name ? `: ${name}` : ""} · Janus workbench`;
  }, [route.screen, name]);
  const first = useRef(true);
  useEffect(() => {
    if (first.current) first.current = false;
    else main.current?.focus();
  }, [route.screen, document]);

  return (
    <div className="shell">
      <a
        className="skip"
        href="#main"
        onClick={(event) => {
          event.preventDefault();
          main.current?.focus();
        }}
      >
        Skip to the main region
      </a>
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
        <button
          type="button"
          className="button help-button"
          aria-label="Keyboard shortcuts"
          title="Keyboard shortcuts"
          onClick={() => setHelp(true)}
        >
          ?
        </button>
      </header>
      <main className="main" id="main" tabIndex={-1} ref={main}>
        {/* One live region for each screen. */}
        <Announcer key={route.screen}>
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
        </Announcer>
      </main>
      <Dialog title="Keyboard shortcuts" open={help} onClose={() => setHelp(false)}>
        <Help />
      </Dialog>
    </div>
  );
}

const ON_A_PAGE: readonly (readonly [string, string])[] = [
  ["Tab", "Go into a page, to the box last active there"],
  ["← →", "Previous and next box, in reading order"],
  ["↑ ↓", "Nearest box above and below"],
  ["Home End", "First and last box of the page"],
  ["Page Up, Page Down", "Previous and next page"],
  ["Enter, Space", "Choose the box, as a click does"],
  ["Esc", "Leave the boxes; the page keeps the keyboard"],
];

/** Every shortcut that works on the screen that is open. */
function Help() {
  const shortcuts = useShortcutList();
  return (
    <>
      <h3>On this screen</h3>
      <dl className="keys">
        {shortcuts.map((shortcut) => (
          <div key={shortcut.key}>
            <dt>
              {keyName(shortcut.key).map((part) => (
                <kbd key={part}>{part}</kbd>
              ))}
            </dt>
            <dd>{shortcut.does}</dd>
          </div>
        ))}
      </dl>
      <p className="quiet">
        A key without Ctrl does nothing while you type in a field. Press Escape, then Tab, to leave
        the spec editor.
      </p>
      <h3>On a page with boxes</h3>
      <dl className="keys">
        {ON_A_PAGE.map(([keys, does]) => (
          <div key={keys}>
            <dt>
              <kbd>{keys}</kbd>
            </dt>
            <dd>{does}</dd>
          </div>
        ))}
      </dl>
    </>
  );
}

type Found =
  | { state: "loading" }
  | { state: "found"; row: DocumentRow }
  | { state: "absent" }
  | { state: "failed"; error: string; again: () => void };

/** The row of the open document. It is asked for again while the document is being read. */
function useDocument(document: string | null): Found {
  const list = useLiveRun<string, DocumentRow[]>(
    document,
    () => ({ delay: 0, run: (_, signal) => api.documents(signal) }),
    [],
  );
  const { again, pending, error, shown } = list;
  const row = shown?.input === document ? shown.output.find((r) => r.id === document) : undefined;
  const reading = row?.status === "queued" || row?.status === "reading";
  useEffect(() => {
    if (!reading || error !== null || pending) return;
    const timer = setTimeout(again, 800);
    return () => clearTimeout(timer);
  }, [reading, error, pending, again]);

  if (document === null) return { state: "loading" };
  if (error !== null) return { state: "failed", error: error.message, again };
  if (shown?.input !== document) return { state: "loading" };
  return row ? { state: "found", row } : { state: "absent" };
}

function NotOpen({ found }: { found: Found }) {
  const back = <Link to={{ screen: "documents" }}>Go to the documents</Link>;
  if (found.state === "failed") {
    return (
      <div className="empty">
        <h1>This document could not be opened</h1>
        <Failure
          what="The list of documents could not be loaded"
          why={found.error}
          again={found.again}
          testId="document-failure"
        />
        <p>Check that `janus-workbench serve` is still running.</p>
        <p>{back}</p>
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
