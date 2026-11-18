// The spec editor: CodeMirror 6 with YAML highlighting and a mark on the line that fails.
import { indentWithTab } from "@codemirror/commands";
import { yaml } from "@codemirror/lang-yaml";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { lintGutter, setDiagnostics } from "@codemirror/lint";
import { EditorView, keymap, placeholder } from "@codemirror/view";
import { tags } from "@lezer/highlight";
import { basicSetup } from "codemirror";
import { useEffect, useRef } from "react";

export interface Problem {
  message: string;
  /** From 1. Without a line the message belongs to the whole spec. */
  line: number | null;
}

interface Props {
  value: string;
  onChange: (text: string) => void;
  problem: Problem | null;
  label: string;
  placeholder: string;
}

// Colours come from the page's variables, so the editor follows light and dark with it.
const highlight = HighlightStyle.define([
  { tag: [tags.propertyName, tags.definition(tags.propertyName)], color: "var(--ink)" },
  { tag: [tags.string, tags.content, tags.special(tags.string)], color: "var(--moss-text)" },
  { tag: [tags.number, tags.bool, tags.null, tags.atom], color: "var(--marmalade-text)" },
  { tag: [tags.comment, tags.lineComment], color: "var(--ink-3)", fontStyle: "italic" },
  { tag: [tags.punctuation, tags.separator, tags.bracket, tags.meta], color: "var(--ink-3)" },
  { tag: tags.keyword, color: "var(--jam-text)" },
]);

const theme = EditorView.theme({
  "&": { height: "100%", fontSize: "13px", backgroundColor: "transparent", color: "var(--ink)" },
  "&.cm-focused": { outline: "none" },
  ".cm-scroller": {
    fontFamily: "var(--mono)",
    lineHeight: "1.65",
    overflow: "auto",
  },
  ".cm-content": { padding: "12px 0", caretColor: "var(--ink)" },
  ".cm-cursor": { borderLeftColor: "var(--ink)" },
  ".cm-gutters": {
    backgroundColor: "transparent",
    color: "var(--ink-3)",
    border: "none",
  },
  ".cm-activeLine": { backgroundColor: "var(--wash)" },
  ".cm-activeLineGutter": { backgroundColor: "var(--wash)", color: "var(--ink-2)" },
  "&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-selectionBackground":
    { backgroundColor: "var(--selection)" },
  ".cm-placeholder": { color: "var(--ink-3)" },
  ".cm-lintRange-error": {
    backgroundImage: "none",
    textDecoration: "underline wavy var(--jam)",
    textUnderlineOffset: "3px",
  },
  ".cm-lint-marker-error": {
    content: "''",
    width: "8px",
    height: "8px",
    marginTop: "7px",
    borderRadius: "50%",
    backgroundColor: "var(--jam)",
  },
  ".cm-tooltip": {
    border: "1px solid var(--rule)",
    backgroundColor: "var(--raised)",
    color: "var(--ink)",
  },
  ".cm-diagnostic-error": { borderLeftColor: "var(--jam)" },
  ".cm-panels": { backgroundColor: "var(--raised)", color: "var(--ink)" },
});

export function Editor(props: Props) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const onChange = useRef(props.onChange);
  onChange.current = props.onChange;

  useEffect(() => {
    if (!host.current) return;
    const editor = new EditorView({
      parent: host.current,
      doc: props.value,
      extensions: [
        basicSetup,
        keymap.of([indentWithTab]),
        yaml(),
        syntaxHighlighting(highlight),
        lintGutter(),
        EditorView.lineWrapping,
        theme,
        placeholder(props.placeholder),
        EditorView.contentAttributes.of({ "aria-label": props.label }),
        EditorView.updateListener.of((update) => {
          if (update.docChanged) onChange.current(update.state.doc.toString());
        }),
      ],
    });
    view.current = editor;
    return () => {
      editor.destroy();
      view.current = null;
    };
    // The editor is made once; later values arrive through the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Text set from outside, such as a saved spec being opened.
  useEffect(() => {
    const editor = view.current;
    if (editor && editor.state.doc.toString() !== props.value) {
      editor.dispatch({
        changes: { from: 0, to: editor.state.doc.length, insert: props.value },
      });
    }
  }, [props.value]);

  const line = props.problem?.line ?? null;
  const text = props.problem?.message ?? "";
  useEffect(() => {
    const editor = view.current;
    if (!editor) return;
    const { doc } = editor.state;
    if (line === null || line < 1) {
      editor.dispatch(setDiagnostics(editor.state, []));
      return;
    }
    const at = doc.line(Math.min(line, doc.lines));
    const from = at.from + (at.text.length - at.text.trimStart().length);
    editor.dispatch(
      setDiagnostics(editor.state, [
        { from, to: Math.max(at.to, from), severity: "error", message: text },
      ]),
    );
  }, [line, text, props.value]);

  return <div ref={host} className="editor" />;
}
