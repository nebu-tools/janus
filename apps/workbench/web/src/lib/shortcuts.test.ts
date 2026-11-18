import { afterEach, beforeEach, describe, expect, it, vi } from "vite-plus/test";

import { keyName, matchShortcut, takesText } from "./shortcuts.tsx";
import type { Shortcut } from "./shortcuts.tsx";

// The tests run without a browser. These stand in for the elements a key can land on.
class FakeElement {
  isContentEditable = false;
}
class FakeInput extends FakeElement {
  type: string;
  constructor(type = "text") {
    super();
    this.type = type;
  }
}
class FakeTextArea extends FakeElement {}
class FakeSelect extends FakeElement {}

const list: Shortcut[] = [
  { key: "n", does: "Next", run: () => {} },
  { key: "/", does: "Search", run: () => {} },
  { key: "mod+s", does: "Save", run: () => {} },
  { key: "mod+Enter", does: "Run", run: () => {} },
];

const press = (key: string, more: Partial<KeyboardEvent> = {}) => ({
  key,
  ctrlKey: false,
  metaKey: false,
  altKey: false,
  target: new FakeElement() as unknown as EventTarget,
  ...more,
});
const field = () => new FakeInput() as unknown as EventTarget;

describe("shortcuts", () => {
  beforeEach(() => {
    vi.stubGlobal("HTMLElement", FakeElement);
    vi.stubGlobal("HTMLInputElement", FakeInput);
    vi.stubGlobal("HTMLTextAreaElement", FakeTextArea);
    vi.stubGlobal("HTMLSelectElement", FakeSelect);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("a plain key is a shortcut outside a text field", () => {
    expect(matchShortcut(list, press("n"), false)?.does).toBe("Next");
    expect(matchShortcut(list, press("/"), false)?.does).toBe("Search");
    expect(matchShortcut(list, press("x"), false)).toBeUndefined();
  });

  it("a plain key typed into a text field is text", () => {
    expect(matchShortcut(list, press("n", { target: field() }), false)).toBeUndefined();
    const area = new FakeTextArea() as unknown as EventTarget;
    expect(matchShortcut(list, press("/", { target: area }), false)).toBeUndefined();
    const editor = new FakeElement();
    editor.isContentEditable = true;
    const target = editor as unknown as EventTarget;
    expect(matchShortcut(list, press("n", { target }), false)).toBeUndefined();
  });

  it("a checkbox and a button take no text", () => {
    expect(takesText(new FakeInput("checkbox") as unknown as EventTarget)).toBe(false);
    expect(takesText(new FakeInput("search") as unknown as EventTarget)).toBe(true);
    expect(takesText(new FakeSelect() as unknown as EventTarget)).toBe(true);
    expect(takesText(null)).toBe(false);
  });

  it("a chord with Ctrl or Command works in a text field too", () => {
    expect(matchShortcut(list, press("s", { ctrlKey: true, target: field() }), false)?.does).toBe(
      "Save",
    );
    expect(matchShortcut(list, press("S", { metaKey: true }), false)?.does).toBe("Save");
    expect(matchShortcut(list, press("Enter", { ctrlKey: true }), false)?.does).toBe("Run");
  });

  it("a key held with Ctrl is not the plain key", () => {
    expect(matchShortcut(list, press("n", { ctrlKey: true }), false)).toBeUndefined();
    expect(matchShortcut(list, press("n", { altKey: true }), false)).toBeUndefined();
  });

  it("AltGr, which reports Ctrl and Alt together, types a plain key", () => {
    expect(matchShortcut(list, press("/", { ctrlKey: true, altKey: true }), false)?.does).toBe(
      "Search",
    );
  });

  it("nothing is a shortcut while a dialog is open", () => {
    expect(matchShortcut(list, press("n"), true)).toBeUndefined();
    expect(matchShortcut(list, press("s", { ctrlKey: true }), true)).toBeUndefined();
  });

  it("the shortcut named last wins a key two screens name", () => {
    const both = [...list, { key: "n", does: "Newer", run: () => {} }];
    expect(matchShortcut(both, press("n"), false)?.does).toBe("Newer");
  });

  it("prints a key as its caps", () => {
    expect(keyName("n")).toEqual(["N"]);
    expect(keyName("mod+Enter")).toEqual(["Ctrl", "Enter"]);
  });
});
