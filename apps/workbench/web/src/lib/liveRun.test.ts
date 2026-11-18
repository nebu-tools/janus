import { afterEach, beforeEach, describe, expect, it, vi } from "vite-plus/test";

import { liveRun } from "./liveRun.ts";

interface Pending {
  input: string;
  signal: AbortSignal;
  answer: (output: string) => void;
  fail: (error: unknown) => void;
}

const setup = (keep?: (output: string) => boolean) => {
  const pending: Pending[] = [];
  const results: string[] = [];
  const errors: unknown[] = [];

  const live = liveRun<string, string>({
    delay: 300,
    run: (input, signal) =>
      new Promise((answer, fail) => {
        pending.push({ input, signal, answer, fail });
      }),
    ...(keep ? { keep } : {}),
  });
  // Every answer and every failure the state ever held, in order.
  let last = live.state();
  live.subscribe(() => {
    const now = live.state();
    if (now.answer !== null && now.answer !== last.answer) results.push(now.answer);
    if (now.error !== null && now.error !== last.error) errors.push(now.error);
    last = now;
  });
  return { live, pending, results, errors };
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
    const { live, pending } = setup();
    live.submit("a");
    vi.advanceTimersByTime(200);
    live.submit("ab");
    vi.advanceTimersByTime(200);
    live.submit("abc");
    vi.advanceTimersByTime(299);
    expect(pending).toHaveLength(0);
    vi.advanceTimersByTime(1);
    expect(pending.map((p) => p.input)).toEqual(["abc"]);
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

  it("drops an answer that arrives while a later input waits for its turn", async () => {
    const { live, pending, results } = setup();
    live.submit("a");
    vi.advanceTimersByTime(300);
    live.submit("ab");
    pending[0]?.answer("A");
    await settle();
    expect(results).toEqual([]);
    vi.advanceTimersByTime(300);
    pending[1]?.answer("AB");
    await settle();
    expect(results).toEqual(["AB"]);
  });

  it("aborts the run in flight as soon as a new input comes", () => {
    const { live, pending } = setup();
    live.submit("old");
    vi.advanceTimersByTime(300);
    live.submit("new");
    expect(pending[0]?.signal.aborted).toBe(true); // before the new run starts
    vi.advanceTimersByTime(300);
    expect(pending[1]?.signal.aborted).toBe(false);
  });

  it("drops a late failure of a run that a newer input replaced", async () => {
    const { live, pending, errors, results } = setup();
    live.submit("old");
    vi.advanceTimersByTime(300);
    live.submit("new");
    pending[0]?.fail(new DOMException("aborted", "AbortError"));
    await settle();
    vi.advanceTimersByTime(300);
    pending[1]?.answer("NEW");
    await settle();
    expect(errors).toEqual([]);
    expect(results).toEqual(["NEW"]);
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

  it("delivers nothing after clear", async () => {
    const { live, pending, results } = setup();
    live.submit("a");
    vi.advanceTimersByTime(300);
    live.submit("b");
    live.clear();
    vi.advanceTimersByTime(1000);
    pending[0]?.answer("A");
    await settle();
    expect(pending).toHaveLength(1);
    expect(pending[0]?.signal.aborted).toBe(true);
    expect(results).toEqual([]);
  });

  it("is pending from the moment an input comes, and keeps the earlier answer as stale", async () => {
    const { live, pending } = setup();
    expect(live.state()).toEqual({
      input: null,
      pending: false,
      error: null,
      answer: null,
      shown: null,
      stale: false,
    });
    live.submit("a");
    expect(live.state()).toMatchObject({ input: "a", pending: true, shown: null, stale: false });
    vi.advanceTimersByTime(300);
    pending[0]?.answer("A");
    await settle();
    const shown = { input: "a", output: "A" };
    expect(live.state()).toMatchObject({ pending: false, answer: "A", shown, stale: false });

    live.submit("b"); // before its delay has passed
    expect(live.state()).toMatchObject({ input: "b", pending: true, answer: null, shown });
    expect(live.state().stale).toBe(true);
    vi.advanceTimersByTime(300);
    expect(live.state().stale).toBe(true);
    pending[1]?.answer("B");
    await settle();
    expect(live.state()).toMatchObject({
      pending: false,
      answer: "B",
      shown: { input: "b", output: "B" },
      stale: false,
    });
  });

  it("ends the pending state on a failure and leaves the earlier answer stale", async () => {
    const { live, pending } = setup();
    live.submit("a");
    vi.advanceTimersByTime(300);
    pending[0]?.answer("A");
    await settle();
    live.submit("b");
    vi.advanceTimersByTime(300);
    pending[1]?.fail("no answer"); // not an Error
    await settle();
    expect(live.state()).toMatchObject({
      input: "b",
      pending: false,
      answer: null,
      shown: { input: "a", output: "A" },
      stale: true,
    });
    expect(live.state().error).toEqual(new Error("no answer"));

    live.submit("c");
    expect(live.state()).toMatchObject({ pending: true, error: null, stale: true });
    vi.advanceTimersByTime(300);
    pending[2]?.answer("C");
    await settle();
    expect(live.state()).toMatchObject({ error: null, answer: "C", stale: false });
  });

  it("a first run that fails is not pending and shows nothing", async () => {
    const { live, pending } = setup();
    live.submit("a");
    vi.advanceTimersByTime(300);
    pending[0]?.fail(new Error("gone"));
    await settle();
    expect(live.state()).toEqual({
      input: "a",
      pending: false,
      error: new Error("gone"),
      answer: null,
      shown: null,
      stale: false,
    });
  });

  it("an answer that is not kept leaves the earlier one shown, stale", async () => {
    const { live, pending } = setup((output) => output !== "BROKEN");
    live.submit("a");
    vi.advanceTimersByTime(300);
    pending[0]?.answer("A");
    await settle();
    live.submit("b");
    vi.advanceTimersByTime(300);
    pending[1]?.answer("BROKEN");
    await settle();
    expect(live.state()).toMatchObject({
      pending: false,
      answer: "BROKEN",
      shown: { input: "a", output: "A" },
      stale: true,
    });
  });

  it("a run that throws at once is a failure like any other", async () => {
    const live = liveRun<string, string>({
      delay: 0,
      run: () => {
        throw new Error("at once");
      },
    });
    live.submit("a");
    await settle();
    expect(live.state()).toMatchObject({ pending: false, error: new Error("at once") });
  });

  it("clear forgets the input and what was shown, and tells its listeners", async () => {
    const { live, pending } = setup();
    live.submit("a");
    vi.advanceTimersByTime(300);
    pending[0]?.answer("A");
    await settle();
    let calls = 0;
    const end = live.subscribe(() => calls++);
    live.clear();
    expect(live.state()).toMatchObject({ input: null, shown: null, stale: false, pending: false });
    expect(calls).toBe(1);
    end();
    live.submit("b");
    expect(calls).toBe(1);
  });

  it("again runs the newest input at once, and what is shown is not stale meanwhile", async () => {
    const { live, pending } = setup();
    live.submit("a");
    vi.advanceTimersByTime(300);
    pending[0]!.answer("A");
    await settle();

    live.again();
    expect(pending).toHaveLength(2);
    expect(pending[1]!.input).toBe("a");
    expect(live.state()).toMatchObject({ pending: true, stale: false, error: null });
    expect(live.state().shown).toEqual({ input: "a", output: "A" });

    pending[1]!.answer("A2");
    await settle();
    expect(live.state()).toMatchObject({ pending: false, stale: false, answer: "A2" });
    expect(live.state().shown).toEqual({ input: "a", output: "A2" });
  });

  it("again that fails leaves what was shown, stale, with the failure", async () => {
    const { live, pending } = setup();
    live.submit("a");
    vi.advanceTimersByTime(300);
    pending[0]!.answer("A");
    await settle();

    live.again();
    pending[1]!.fail(new Error("gone"));
    await settle();
    expect(live.state()).toMatchObject({ pending: false, stale: true, answer: null });
    expect(live.state().error?.message).toBe("gone");
    expect(live.state().shown).toEqual({ input: "a", output: "A" });

    // Asking once more keeps the failure on screen until there is an answer.
    live.again();
    expect(live.state()).toMatchObject({ pending: true, stale: true });
    expect(live.state().error?.message).toBe("gone");
    pending[2]!.answer("A3");
    await settle();
    expect(live.state()).toMatchObject({ pending: false, stale: false, error: null });
  });

  it("again voids the run it replaces", async () => {
    const { live, pending, results } = setup();
    live.submit("a");
    vi.advanceTimersByTime(300);
    live.again();
    expect(pending[0]!.signal.aborted).toBe(true);
    pending[0]!.answer("late");
    pending[1]!.answer("now");
    await settle();
    expect(results).toEqual(["now"]);
  });

  it("again without an input does nothing", () => {
    const { live, pending } = setup();
    live.again();
    expect(pending).toHaveLength(0);
    expect(live.state().pending).toBe(false);
  });
});
