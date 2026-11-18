// Runs a slow function on the newest input only.
//
// `submit` waits until no new input has come for `delay` ms, then calls `run`. An answer is
// delivered only if no later run has started since, so an old answer that arrives late can
// never replace a newer one. A run that is replaced has its signal aborted.

export interface LiveRun<I> {
  /** Take a new input. It runs once `delay` ms pass without another. */
  submit(input: I): void;
  /** Drop the waiting input and ignore every answer still on its way. */
  cancel(): void;
}

export interface LiveRunOptions<I, O> {
  delay: number;
  run: (input: I, signal: AbortSignal) => Promise<O>;
  /** A run has started for `input`. */
  onStart?: (input: I) => void;
  /** The newest run answered. */
  onResult: (output: O, input: I) => void;
  /** The newest run failed. */
  onError: (error: unknown, input: I) => void;
}

export function liveRun<I, O>(options: LiveRunOptions<I, O>): LiveRun<I> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let newest = 0;
  let running: AbortController | undefined;

  const start = (input: I) => {
    const mine = ++newest;
    running?.abort();
    const controller = new AbortController();
    running = controller;
    options.onStart?.(input);
    options.run(input, controller.signal).then(
      (output) => {
        if (mine === newest) options.onResult(output, input);
      },
      (error: unknown) => {
        if (mine === newest) options.onError(error, input);
      },
    );
  };

  return {
    submit(input) {
      clearTimeout(timer);
      timer = setTimeout(() => start(input), options.delay);
    },
    cancel() {
      clearTimeout(timer);
      newest++;
      running?.abort();
      running = undefined;
    },
  };
}
