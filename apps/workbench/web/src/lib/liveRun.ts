// Runs a slow function on the newest input only.
//
// `submit` aborts the run in flight at once, and from then on no answer to an older input is
// delivered, also while the new input waits. The new input runs once `delay` ms pass without
// another. So an answer that is delivered is always the answer to the newest input.

export interface LiveRun<I> {
  /** Take a new input. Every earlier answer is void from now; it runs once `delay` ms pass
   * without another. */
  submit(input: I): void;
  /** Drop the waiting input and ignore every answer still on its way. */
  cancel(): void;
}

export interface LiveRunOptions<I, O> {
  delay: number;
  run: (input: I, signal: AbortSignal) => Promise<O>;
  /** The run for the newest input answered. */
  onResult: (output: O, input: I) => void;
  /** The run for the newest input failed. */
  onError: (error: unknown, input: I) => void;
}

export function liveRun<I, O>(options: LiveRunOptions<I, O>): LiveRun<I> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let newest = 0;
  let running: AbortController | undefined;

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
      drop();
      const mine = newest;
      timer = setTimeout(() => start(input, mine), options.delay);
    },
    cancel: drop,
  };
}
