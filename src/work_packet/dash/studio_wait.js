// A studio frame that draws after load (a chart) holds the renderer until it is
// done: studio_chart.js sets window.__studioReady = true (docs/studio-plan.md S3.1).
// Vega's warnings are kept for the render's checks (S3.5).
window.__studioReady = false;
window.__studioWarnings = [];
