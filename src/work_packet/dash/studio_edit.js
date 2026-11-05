// The studio's editor (docs/studio-v2.md §4): CodeMirror 6 from the vendored
// bundle, wrapped so studio_files.js needs only text in and text out. Loaded
// with import() when the first text tab opens; if the bundle is not built the
// import fails and studio_files.js falls back to a plain textarea.
import {
  EditorView, EditorState, Compartment, keymap, basicSetup, indentWithTab,
  MergeView, languageFor,
} from "/static/vendor/codemirror/codemirror.js";

const theme = EditorView.theme({
  "&": { height: "100%", fontSize: "13px", backgroundColor: "var(--panel)", color: "var(--ink)" },
  ".cm-scroller": { fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace" },
  ".cm-gutters": { backgroundColor: "var(--bg)", color: "var(--muted)", borderRight: "1px solid var(--line)" },
  ".cm-activeLine, .cm-activeLineGutter": { backgroundColor: "color-mix(in srgb, var(--link) 7%, transparent)" },
  "&.cm-focused": { outline: "none" },
  ".cm-cursor": { borderLeftColor: "var(--ink)" },
});

// An editor in `parent`: {text, name, readOnly, onChange(), onSave()}. Returns
// {getText, setText, focus, destroy}.
export function makeEditor(parent, o) {
  const ro = new Compartment();
  const view = new EditorView({
    parent,
    state: EditorState.create({
      doc: o.text || "",
      extensions: [
        basicSetup, theme, languageFor(o.name || ""),
        keymap.of([indentWithTab, { key: "Mod-s", preventDefault: true, run: () => { if (o.onSave) o.onSave(); return true; } }]),
        ro.of([EditorState.readOnly.of(!!o.readOnly), EditorView.editable.of(!o.readOnly)]),
        EditorView.updateListener.of((u) => { if (u.docChanged && o.onChange) o.onChange(); }),
      ],
    }),
  });
  return {
    getText: () => view.state.doc.toString(),
    setText: (t) => {
      // Keep the cursor where it can be: a reload after an outside change.
      const head = Math.min(view.state.selection.main.head, t.length);
      view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: t }, selection: { anchor: head } });
    },
    focus: () => view.focus(),
    destroy: () => view.destroy(),
  };
}

// Your text beside what the file holds now: `mine` (left, editable) and
// `theirs` (right, read-only), with the differences marked and a revert arrow
// per chunk. Returns {getText (your side), destroy}.
export function makeMerge(parent, o) {
  const lang = languageFor(o.name || "");
  const mv = new MergeView({
    parent,
    a: { doc: o.mine, extensions: [basicSetup, theme, lang] },
    b: { doc: o.theirs, extensions: [basicSetup, theme, lang, EditorState.readOnly.of(true), EditorView.editable.of(false)] },
    revertControls: "b-to-a",
    highlightChanges: true,
    gutter: true,
  });
  return { getText: () => mv.a.state.doc.toString(), destroy: () => mv.destroy() };
}
