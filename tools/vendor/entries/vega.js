// Vega, Vega-Lite and vega-embed in one module. Charts run under the board's CSP
// (script-src 'self', no unsafe-eval) through vega-interpreter: pass
// { ast: true, expr: expressionInterpreter } to embed().
export * as vega from "vega";
export * as vegaLite from "vega-lite";
export { default as embed } from "vega-embed";
export { expressionInterpreter } from "vega-interpreter";
