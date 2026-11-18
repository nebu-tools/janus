import { afterEach, beforeEach, describe, expect, it, vi } from "vite-plus/test";

import { liveRun } from "./liveRun.ts";

interface Pending {
  input: string;
  signal: AbortSignal;
  answer: (output: string) => void;
  fail: (error: unknown) => void;
}

const setup = () => {
  const pending: Pending[] = [];
  const results: string[] = [];
  const errors: unknown[] = [];
  const started: string[] = [];
  const live = liveRun<string, string>({
    delay: 300,
    run: (input, signal) =>
      new Promise((answer, fail) => {
        pending.push({ input, signal, answer, fail });
      }),
    onStart: (input) => started.push(input),
    onResult: (output) => results.push(output),
    onError: (error) => errors.push(error),
  });
  return { live, pending, results, errors, started };
};

const settle = () => vi.advanceTimersByTimeAsync(0);

describe("liveRun", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("waits 300 ms after the last input before it runs", () => {
    const { live, pending } = setup();
    live.submit("a");
    vi.advanceTimersByTime(299);
    expect(pending).toHaveLength(0);
    vi.advanceTimersByTime(1);
    expect(pending.map((p) => p.input)).toEqual(["a"]);
  });

  it("runs once for a burst of inputs, with the last one", () => {
    const { live, pending, started } = setup();
    live.submit("a");
    vi.advanceTimersByTime(200);
    live.submit("ab");
    vi.advanceTimersByTime(200);
    live.submit("abc");
    vi.advanceTimersByTime(299);
    expect(pending).toHaveLength(0);
    vi.advanceTimersByTime(1);
    expect(pending.map((p) => p.input)).toEqual(["abc"]);
    expect(started).toEqual(["abc"]);
  });

  it("delivers the answer of the newest run", async () => {
    const { live, pending, results } = setup();
    live.submit("a");
    vi.advanceTimersByTime(300);
    pending[0]?.answer("A");
    await settle();
    expect(results).toEqual(["A"]);
  });

  it("drops an older answer that arrives after a newer one", async () => {
    const { live, pending, results } = setup();
    live.submit("old");
    vi.advanceTimersByTime(300);
    live.submit("new");
    vi.advanceTimersByTime(300);
    pending[1]?.answer("NEW");
    await settle();
    pending[0]?.answer("OLD");
    await settle();
    expect(results).toEqual(["NEW"]);
  });

  it("drops an older answer that arrives while the newer run is still out", async () => {
    const { live, pending, results } = setup();
    live.submit("old");
    vi.advanceTimersByTime(300);
    live.submit("new");
    vi.advanceTimersByTime(300);
    pending[0]?.answer("OLD");
    await settle();
    expect(results).toEqual([]);
    pending[1]?.answer("NEW");
    await settle();
    expect(results).toEqual(["NEW"]);
  });

  it("keeps the answer of a run while a later input is still waiting", async () => {
    const { live, pending, results } = setup();
    live.submit("a");
    vi.advanceTimersByTime(300);
    live.submit("ab");
    pending[0]?.answer("A");
    await settle();
    expect(results).toEqual(["A"]);
  });

  it("aborts the run it replaces", () => {
    const { live, pending } = setup();
    live.submit("old");
    vi.advanceTimersByTime(300);
    live.submit("new");
    vi.advanceTimersByTime(300);
    expect(pending[0]?.signal.aborted).toBe(true);
    expect(pending[1]?.signal.aborted).toBe(false);
  });

  it("drops the failure of an older run and reports the newest one", async () => {
    const { live, pending, errors, results } = setup();
    live.submit("old");
    vi.advanceTimersByTime(300);
    live.submit("new");
    vi.advanceTimersByTime(300);
    pending[0]?.fail(new Error("old failed"));
    await settle();
    expect(errors).toEqual([]);
    pending[1]?.fail(new Error("new failed"));
    await settle();
    expect(errors).toEqual([new Error("new failed")]);
    expect(results).toEqual([]);
  });

  it("delivers nothing after cancel", async () => {
    const { live, pending, results } = setup();
    live.submit("a");
    vi.advanceTimersByTime(300);
    live.submit("b");
    live.cancel();
    vi.advanceTimersByTime(1000);
    pending[0]?.answer("A");
    await settle();
    expect(pending).toHaveLength(1);
    expect(pending[0]?.signal.aborted).toBe(true);
    expect(results).toEqual([]);
  });
});
