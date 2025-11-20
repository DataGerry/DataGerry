import { C as CodeMirror } from "./codemirror.es-nbiXx07Y.js";
import { a9 as p, aa as list2, ab as t, ac as opt } from "./index-rB_RgBMf.js";
import { o as onlineParser } from "./onlineParser.es-BLvsVcCc.js";
import "react";
import "react-dom";
var __defProp = Object.defineProperty;
var __name = (target, value) => __defProp(target, "name", { value, configurable: true });
CodeMirror.defineMode("graphql-variables", (config) => {
  const parser = onlineParser({
    eatWhitespace: (stream) => stream.eatSpace(),
    lexRules: LexRules,
    parseRules: ParseRules,
    editorConfig: { tabSize: config.tabSize }
  });
  return {
    config,
    startState: parser.startState,
    token: parser.token,
    indent,
    electricInput: /^\s*[}\]]/,
    fold: "brace",
    closeBrackets: {
      pairs: '[]{}""',
      explode: "[]{}"
    }
  };
});
function indent(state, textAfter) {
  var _a, _b;
  const levels = state.levels;
  const level = !levels || levels.length === 0 ? state.indentLevel : levels[levels.length - 1] - (((_a = this.electricInput) === null || _a === void 0 ? void 0 : _a.test(textAfter)) ? 1 : 0);
  return (level || 0) * (((_b = this.config) === null || _b === void 0 ? void 0 : _b.indentUnit) || 0);
}
__name(indent, "indent");
const LexRules = {
  Punctuation: /^\[|]|\{|\}|:|,/,
  Number: /^-?(?:0|(?:[1-9][0-9]*))(?:\.[0-9]*)?(?:[eE][+-]?[0-9]+)?/,
  String: /^"(?:[^"\\]|\\(?:"|\/|\\|b|f|n|r|t|u[0-9a-fA-F]{4}))*"?/,
  Keyword: /^true|false|null/
};
const ParseRules = {
  Document: [p("{"), list2("Variable", opt(p(","))), p("}")],
  Variable: [namedKey("variable"), p(":"), "Value"],
  Value(token) {
    switch (token.kind) {
      case "Number":
        return "NumberValue";
      case "String":
        return "StringValue";
      case "Punctuation":
        switch (token.value) {
          case "[":
            return "ListValue";
          case "{":
            return "ObjectValue";
        }
        return null;
      case "Keyword":
        switch (token.value) {
          case "true":
          case "false":
            return "BooleanValue";
          case "null":
            return "NullValue";
        }
        return null;
    }
  },
  NumberValue: [t("Number", "number")],
  StringValue: [t("String", "string")],
  BooleanValue: [t("Keyword", "builtin")],
  NullValue: [t("Keyword", "keyword")],
  ListValue: [p("["), list2("Value", opt(p(","))), p("]")],
  ObjectValue: [p("{"), list2("ObjectField", opt(p(","))), p("}")],
  ObjectField: [namedKey("attribute"), p(":"), "Value"]
};
function namedKey(style) {
  return {
    style,
    match: (token) => token.kind === "String",
    update(state, token) {
      state.name = token.value.slice(1, -1);
    }
  };
}
__name(namedKey, "namedKey");
