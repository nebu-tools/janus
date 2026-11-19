// Pairs an input with its answer. This is the one place in the client that does.
//
// A slow function runs on the newest input only. A new input aborts the run in flight at once,
// and from then on no answer to an older input is taken, also while the new input waits its
// `delay`. So `answer` is always the answer to `input`.
//
// The last answer worth showing is kept while a later input runs or fails. It is then `stale`:
// whoever draws it draws it dimmed, with the input it belongs to. A screen never works this out
// for itself.
//
// The same input can be asked again: to refresh a list, or to try once more after a failure.
// While that runs, what is shown is still the answer to the newest input, so it is not stale.
// If it fails, what is shown is from before the failure, and it is stale.
import { useEffect, useMemo, useSyncExternalStore } from "react";
import type { DependencyList } from "react";

export interface LiveState<I, O> {
  /** The newest input. Null before the first one and after `clear`. */
  input: I | null;
  /** The newest input has no answer yet. */
  pending: boolean;
  /** Why the run for the newest input failed. Null while it runs and once it answered. */
  error: Error | null;
  /** The answer to the newest input. Null until it is there. */
  answer: O | null;
  /** The last answer kept for showing, and the input it is the answer to. */
  shown: { input: I; output: O } | null;
  /** `shown` is not the answer to the newest input. */
  stale: boolean;
}

export interface LiveRun<I, O> {
  /** Take a new input. Every earlier answer is void from now; it runs once `delay` ms pass
   * without another. */
  submit(input: I): void;
  /** Run the newest input again, now. What is shown and the last failure stay until it answers. */
  again(): void;
  /** Forget everything: no input, nothing shown, and every answer still on its way ignored. */
  clear(): void;
  state(): LiveState<I, O>;
  /** Call `listener` after every change of the state. Returns the function that ends it. */
  subscribe(listener: () => void): () => void;
}

export interface LiveRunOptions<I, O> {
  delay: number;
  run: (input: I, signal: AbortSignal) => Promise<O>;
  /** Whether an answer replaces what is shown. An answer that is not kept leaves the earlier
   * one in place, stale. Every answer is kept when this is left out. */
  keep?: (output: O) => boolean;
}

const EMPTY: LiveState<never, never> = {
  input: null,
  pending: false,
  error: null,
  answer: null,
  shown: null,
  stale: false,
};

/** The state once `input` is the newest input and nothing has answered it. */
function waiting<I, O>(state: LiveState<I, O>, input: I): LiveState<I, O> {
  const { shown } = state;
  return { input, pending: true, error: null, answer: null, shown, stale: shown !== null };
}

export function liveRun<I, O>(options: LiveRunOptions<I, O>): LiveRun<I, O> {
  const keep = options.keep ?? (() => true);
  const listeners = new Set<() => void>();
  let state: LiveState<I, O> = EMPTY;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let newest = 0;
  let running: AbortController | undefined;

  const set = (next: LiveState<I, O>) => {
    state = next;
    for (const listener of listeners) listener();
  };

  // Void every answer still on its way, and stop the run in flight.
  const drop = () => {
    clearTimeout(timer);
    newest++;
    running?.abort();
    running = undefined;
  };

  const start = (input: I, mine: number) => {
    const controller = new AbortController();
    running = controller;
    new Promise<O>((resolve) => resolve(options.run(input, controller.signal))).then(
      (output) => {
        if (mine !== newest) return;
        const shown = keep(output) ? { input, output } : state.shown;
        const stale = shown !== null && shown.output !== output;
        set({ input, pending: false, error: null, answer: output, shown, stale });
      },
      (reason: unknown) => {
        if (mine !== newest) return;
        const error = reason instanceof Error ? reason : new Error(String(reason));
        set({ ...waiting(state, input), pending: false, error });
      },
    );
  };

  return {
    submit(input) {
      drop();
      const mine = newest;
      set(waiting(state, input));
      timer = setTimeout(() => start(input, mine), options.delay);
    },
    again() {
      const { input } = state;
      if (input === null) return;
      drop();
      set({ ...state, pending: true });
      start(input, newest);
    },
    clear() {
      drop();
      if (state !== EMPTY) set(EMPTY);
    },
    state: () => state,
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

/**
 * The live state for `input` as it changes; null is no input. `make` is called again when
 * `deps` change, and the run it replaces is dropped.
 *
 * The state returned is for the `input` of this very render: an input that was not handed on
 * yet is already pending, and what is shown is already stale.
 */
export function useLiveRun<I, O>(
  input: I | null,
  make: () => LiveRunOptions<I, O>,
  deps: DependencyList,
): LiveState<I, O> & Pick<LiveRun<I, O>, "again"> {
  // oxlint-disable-next-line react-hooks/exhaustive-deps -- the caller lists what `make` reads
  const live = useMemo(() => liveRun(make()), deps);
  useEffect(() => {
    if (input === null) live.clear();
    else live.submit(input);
  }, [live, input]);
  useEffect(() => () => live.clear(), [live]);
  const state = useSyncExternalStore(live.subscribe, live.state);
  const now = Object.is(state.input, input)
    ? state
    : input === null
      ? (EMPTY as LiveState<I, O>)
      : waiting(state, input);
  return { ...now, again: live.again };
}
