// The text typed for a document, kept in the browser's storage under the document's hash until
// it is saved or equals the spec it came from.
//
// Two tabs can hold the same document. Storage has one place for it, so the tab that wrote last
// would win without a word. Here a tab that sees the other one write a different text stops
// writing, and says so, until the person picks one of the two texts.
//
// Storage can be full or switched off. Then the text lives only as long as the page, and the
// editor says that once.
import { useCallback, useEffect, useState, useSyncExternalStore } from "react";

export interface Draft {
  text: string;
  name: string;
  /** The text of the spec last opened or saved; null when there was none. */
  base: string | null;
}

const EMPTY: Draft = { text: "", name: "", base: null };
const key = (document: string) => `janus.draft.${document}`;

/** The draft in a stored value, or null when the value holds none. */
export function parseDraft(raw: string | null): Draft | null {
  try {
    const value: unknown = JSON.parse(raw ?? "null");
    const { text, name, base } = (value ?? {}) as Partial<Record<keyof Draft, unknown>>;
    if (typeof text === "string" && typeof name === "string") {
      return { text, name, base: typeof base === "string" ? base : null };
    }
  } catch {
    // Not a draft.
  }
  return null;
}

/** Nothing a person typed would be lost with this draft: it equals the spec it came from. */
const settled = (draft: Draft) => draft.text === (draft.base ?? "");

// Whether the browser refused to store a draft. It is one fact for the whole page, said once
// however many documents are opened.
let refused = false;
let told = false;
const listeners = new Set<() => void>();
const tell = () => {
  for (const listener of listeners) listener();
};
const unstoredNow = () => refused && !told;
const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

/** Do something with the storage. When it throws, the page knows the text is not stored. */
function stored<T>(use: () => T, otherwise: T): T {
  try {
    return use();
  } catch {
    if (!refused) {
      refused = true;
      tell();
    }
    return otherwise;
  }
}

export interface DraftState {
  draft: Draft;
  setDraft: (next: Draft | ((now: Draft) => Draft)) => void;
  /** The text another tab holds for this document, while it differs from this tab's and the
   * person has not chosen. This tab writes nothing while it is set. */
  other: Draft | null;
  /** Take the other tab's text. */
  loadOther: () => void;
  /** Keep this tab's text and store it over the other tab's. */
  keepMine: () => void;
  /** The browser cannot store the text, and this was not said before. */
  unstored: boolean;
  /** The person read that the text cannot be stored. */
  dismissUnstored: () => void;
}

interface Held {
  draft: Draft;
  /** What another tab stored for this document, while it differs from `draft`. */
  other: Draft | null;
}

export function useDraft(document: string): DraftState {
  const unstored = useSyncExternalStore(subscribe, unstoredNow);
  const [held, setHeld] = useState<Held>(() => ({
    draft: stored(() => parseDraft(localStorage.getItem(key(document))), null) ?? EMPTY,
    other: null,
  }));
  const { draft, other } = held;

  // Typing this tab's text into what the other tab holds ends the choice: there is one text.
  const setDraft = useCallback((next: Draft | ((now: Draft) => Draft)) => {
    setHeld((now) => {
      const draft = typeof next === "function" ? next(now.draft) : next;
      if (draft === now.draft) return now;
      return { draft, other: now.other?.text === draft.text ? null : now.other };
    });
  }, []);

  useEffect(() => {
    if (other !== null) return;
    stored(() => {
      if (settled(draft)) localStorage.removeItem(key(document));
      else localStorage.setItem(key(document), JSON.stringify(draft));
    }, undefined);
  }, [document, draft, other]);

  useEffect(() => {
    // The browser sends this to every tab but the one that wrote.
    const onStorage = (event: StorageEvent) => {
      const area = stored(() => localStorage, null);
      if (area === null || event.storageArea !== area || event.key !== key(document)) return;
      const theirs = parseDraft(event.newValue);
      // Nothing stored: the other tab holds nothing unsaved. The same text: nothing to choose.
      setHeld((now) => ({
        draft: now.draft,
        other: theirs === null || theirs.text === now.draft.text ? null : theirs,
      }));
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [document]);

  return {
    draft,
    setDraft,
    other,
    loadOther: () => setHeld((now) => ({ draft: now.other ?? now.draft, other: null })),
    keepMine: () => setHeld((now) => ({ draft: now.draft, other: null })),
    unstored,
    dismissUnstored: () => {
      told = true;
      tell();
    },
  };
}
