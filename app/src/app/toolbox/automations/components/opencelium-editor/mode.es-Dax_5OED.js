import { C as CodeMirror } from "./codemirror.es-D9skb9Tx.js";
import { a5 as ParseRules, a6 as LexRules, a7 as isIgnored } from "./index-DWZ7s-gK.js";
import { o as onlineParser } from "./onlineParser.es-CST0Y-zo.js";
import "react";
import "react-dom";
var __defProp = Object.defineProperty;
var __name = (target, value) => __defProp(target, "name", { value, configurable: true });
function indent(state, textAfter) {
  var _a, _b;
  const levels = state.levels;
  const level = !levels || levels.length === 0 ? state.indentLevel : levels[levels.length - 1] - (((_a = this.electricInput) === null || _a === void 0 ? void 0 : _a.test(textAfter)) ? 1 : 0);
  return (level || 0) * (((_b = this.config) === null || _b === void 0 ? void 0 : _b.indentUnit) || 0);
}
__name(indent, "indent");
const graphqlModeFactory = /* @__PURE__ */ __name((config) => {
  const parser = onlineParser({
    eatWhitespace: (stream) => stream.eatWhile(isIgnored),
    lexRules: LexRules,
    parseRules: ParseRules,
    editorConfig: { tabSize: config.tabSize }
  });
  return {
    config,
    startState: parser.startState,
    token: parser.token,
    indent,
    electricInput: /^\s*[})\]]/,
    fold: "brace",
    lineComment: "#",
    closeBrackets: {
      pairs: '()[]{}""',
      explode: "()[]{}"
    }
  };
}, "graphqlModeFactory");
CodeMirror.defineMode("graphql", graphqlModeFactory);
