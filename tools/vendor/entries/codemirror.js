// CodeMirror 6 for the studio's editor tabs (docs/studio-v2.md §4).
// One bundle: the core, the languages a packet usually holds, search and the
// merge view (shown when a save finds the file changed underneath).

export { EditorView, keymap, lineNumbers, Decoration, ViewPlugin, WidgetType, gutter, GutterMarker } from "@codemirror/view";
export { EditorState, Compartment, StateField, StateEffect, RangeSet } from "@codemirror/state";
export { basicSetup, minimalSetup } from "codemirror";
export { indentWithTab, undo, redo } from "@codemirror/commands";
export { openSearchPanel } from "@codemirror/search";
export { MergeView, unifiedMergeView } from "@codemirror/merge";
export { syntaxHighlighting, defaultHighlightStyle, HighlightStyle } from "@codemirror/language";

import { StreamLanguage } from "@codemirror/language";
import { markdown } from "@codemirror/lang-markdown";
import { python } from "@codemirror/lang-python";
import { json } from "@codemirror/lang-json";
import { yaml } from "@codemirror/lang-yaml";
import { shell } from "@codemirror/legacy-modes/mode/shell";
import { toml } from "@codemirror/legacy-modes/mode/toml";
import { verilog } from "@codemirror/legacy-modes/mode/verilog";
import { c, cpp } from "@codemirror/legacy-modes/mode/clike";
import { diff } from "@codemirror/legacy-modes/mode/diff";
import { cmake } from "@codemirror/legacy-modes/mode/cmake";

const stream = (p) => () => StreamLanguage.define(p);

// File extension (or whole name) -> a function giving the language extension.
export const LANGUAGES = {
  md: markdown, markdown: markdown,
  py: python, pyi: python,
  json: json, jsonl: json,
  yaml: yaml, yml: yaml,
  toml: stream(toml),
  sh: stream(shell), bash: stream(shell), envrc: stream(shell),
  v: stream(verilog), sv: stream(verilog), svh: stream(verilog), vh: stream(verilog),
  c: stream(c), h: stream(c), cc: stream(cpp), cpp: stream(cpp), hpp: stream(cpp), cxx: stream(cpp),
  diff: stream(diff), patch: stream(diff),
  "CMakeLists.txt": stream(cmake), cmake: stream(cmake),
};

export function languageFor(name) {
  const base = name.split("/").pop();
  if (LANGUAGES[base]) return LANGUAGES[base]();
  const dot = base.lastIndexOf(".");
  const ext = dot < 0 ? "" : base.slice(dot + 1).toLowerCase();
  return LANGUAGES[ext] ? LANGUAGES[ext]() : [];
}
