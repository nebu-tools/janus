// The keyboard shortcuts: one listener, one rule for when a key is a shortcut, and the list the
// help sheet shows.
//
// A plain key ("n", "/", "?") is a shortcut only while no text field has focus and no dialog is
// open, so it can always be typed. A chord with Ctrl or Command ("mod+s") types nothing and
// works in a text field too.
import { createContext, use, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

export interface Shortcut {
  /** `event.key` of a plain key, or "mod+" and a key for a chord with Ctrl or Command. */
  key: string;
  /** What it does, for the help sheet. */
  does: string;
  run: () => void;
}

interface Registry {
  add(list: readonly Shortcut[]): () => void;
  all: readonly Shortcut[];
}

const ShortcutsContext = createContext<Registry | null>(null);

const TEXT_INPUTS = new Set(["checkbox", "radio", "button", "submit", "reset", "file", "range"]);

/** Whether typing into `target` writes text, or picks from a list. */
export function takesText(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  if (target instanceof HTMLInputElement) return !TEXT_INPUTS.has(target.type);
  return target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement;
}

/** The shortcut `event` asks for, if it asks for one now. */
export function matchShortcut(
  list: readonly Shortcut[],
  event: Pick<KeyboardEvent, "key" | "ctrlKey" | "metaKey" | "altKey" | "target">,
  dialogOpen: boolean,
): Shortcut | undefined {
  const chord = (event.ctrlKey || event.metaKey) && !event.altKey;
  if (chord) {
    if (dialogOpen) return undefined;
    const key = `mod+${event.key.length === 1 ? event.key.toLowerCase() : event.key}`;
    return list.findLast((s) => s.key === key);
  }
  // AltGr, which some layouts need for "[" and "]", reports Ctrl and Alt together.
  if (event.metaKey || event.altKey !== event.ctrlKey) return undefined;
  if (dialogOpen || takesText(event.target)) return undefined;
  return list.findLast((s) => s.key === event.key);
}

export function ShortcutsProvider({ children }: { children: ReactNode }) {
  const [all, setAll] = useState<readonly Shortcut[]>([]);
  const current = useRef(all);
  useEffect(() => {
    current.current = all;
  }, [all]);

  const add = useCallback((list: readonly Shortcut[]) => {
    setAll((now) => [...now, ...list]);
    return () => setAll((now) => now.filter((s) => !list.includes(s)));
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.isComposing) return;
      const open = document.querySelector("dialog[open]") !== null;
      const shortcut = matchShortcut(current.current, event, open);
      if (!shortcut) return;
      event.preventDefault();
      event.stopPropagation();
      shortcut.run();
    };
    // Before anything inside the page sees the key: the editor has its own use for some chords.
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, []);

  const registry = useMemo(() => ({ add, all }), [add, all]);
  return <ShortcutsContext value={registry}>{children}</ShortcutsContext>;
}

function useRegistry(): Registry {
  const registry = use(ShortcutsContext);
  if (!registry) throw new Error("shortcuts need a ShortcutsProvider above them");
  return registry;
}

/** Shortcuts that work while the component that names them is on screen. `run` may change
 * from one render to the next; `key` and `does` are read once. */
export function useShortcuts(list: readonly Shortcut[]): void {
  const { add } = useRegistry();
  const latest = useRef(list);
  useEffect(() => {
    latest.current = list;
  });
  const shape = list.map((s) => `${s.key}\n${s.does}`).join("\n\n");
  useEffect(() => {
    const stable = latest.current.map((s, i) => ({
      key: s.key,
      does: s.does,
      run: () => latest.current[i]?.run(),
    }));
    return add(stable);
  }, [add, shape]);
}

/** Every shortcut that works now, in the order the screens named them. */
export function useShortcutList(): readonly Shortcut[] {
  return useRegistry().all;
}

const MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

/** A key as it is printed on the help sheet: "mod+s" is "Ctrl S", or "⌘ S" on a Mac. */
export function keyName(key: string): string[] {
  const names: Record<string, string> = { Enter: "Enter", Escape: "Esc", " ": "Space" };
  const name = (k: string) => names[k] ?? (k.length === 1 ? k.toUpperCase() : k);
  if (key.startsWith("mod+")) return [MAC ? "⌘" : "Ctrl", name(key.slice(4))];
  return [name(key)];
}
