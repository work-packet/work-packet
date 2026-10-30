// Excalidraw with its React, for templates/sketch.html and the render page
// (docs/interactive-tasks.md §4.1). Set window.EXCALIDRAW_ASSET_PATH to this
// folder first, so the fonts load from fonts/ here. Mermaid conversion is in
// mermaid-to-excalidraw.js.
export * as React from "react";
export { createRoot } from "react-dom/client";
export {
  Excalidraw, exportToSvg, exportToBlob, convertToExcalidrawElements,
  reconcileElements, restoreElements, serializeAsJSON, getSceneVersion,
} from "@excalidraw/excalidraw";
