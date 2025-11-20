import { C as CodeMirror } from "./codemirror.es-DeWroV-8.js";
import { f as forEachState } from "./forEachState.es-Bu9VKDOE.js";
import { g as getNamedType, n as GraphQLInputObjectType, G as GraphQLEnumType, c as GraphQLBoolean, o as getNullableType, q as GraphQLList } from "./index-BL2fvCQ5.js";
import "react";
import "react-dom";
var __defProp = Object.defineProperty;
var __name = (target, value) => __defProp(target, "name", { value, configurable: true });
function hintList(cursor, token, list) {
  const hints = filterAndSortList(list, normalizeText(token.string));
  if (!hints) {
    return;
  }
  const tokenStart = token.type !== null && /"|\w/.test(token.string[0]) ? token.start : token.end;
  return {
    list: hints,
    from: { line: cursor.line, ch: tokenStart },
    to: { line: cursor.line, ch: token.end }
  };
}
__name(hintList, "hintList");
function filterAndSortList(list, text) {
  if (!text) {
    return filterNonEmpty(list, (entry) => !entry.isDeprecated);
  }
  const byProximity = list.map((entry) => ({
    proximity: getProximity(normalizeText(entry.text), text),
    entry
  }));
  const conciseMatches = filterNonEmpty(filterNonEmpty(byProximity, (pair) => pair.proximity <= 2), (pair) => !pair.entry.isDeprecated);
  const sortedMatches = conciseMatches.sort((a, b) => (a.entry.isDeprecated ? 1 : 0) - (b.entry.isDeprecated ? 1 : 0) || a.proximity - b.proximity || a.entry.text.length - b.entry.text.length);
  return sortedMatches.map((pair) => pair.entry);
}
__name(filterAndSortList, "filterAndSortList");
function filterNonEmpty(array, predicate) {
  const filtered = array.filter(predicate);
  return filtered.length === 0 ? array : filtered;
}
__name(filterNonEmpty, "filterNonEmpty");
function normalizeText(text) {
  return text.toLowerCase().replace(/\W/g, "");
}
__name(normalizeText, "normalizeText");
function getProximity(suggestion, text) {
  let proximity = lexicalDistance(text, suggestion);
  if (suggestion.length > text.length) {
    proximity -= suggestion.length - text.length - 1;
    proximity += suggestion.indexOf(text) === 0 ? 0 : 0.5;
  }
  return proximity;
}
__name(getProximity, "getProximity");
function lexicalDistance(a, b) {
  let i;
  let j;
  const d = [];
  const aLength = a.length;
  const bLength = b.length;
  for (i = 0; i <= aLength; i++) {
    d[i] = [i];
  }
  for (j = 1; j <= bLength; j++) {
    d[0][j] = j;
  }
  for (i = 1; i <= aLength; i++) {
    for (j = 1; j <= bLength; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost);
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) {
        d[i][j] = Math.min(d[i][j], d[i - 2][j - 2] + cost);
      }
    }
  }
  return d[aLength][bLength];
}
__name(lexicalDistance, "lexicalDistance");
CodeMirror.registerHelper("hint", "graphql-variables", (editor, options) => {
  const cur = editor.getCursor();
  const token = editor.getTokenAt(cur);
  const results = getVariablesHint(cur, token, options);
  if ((results === null || results === void 0 ? void 0 : results.list) && results.list.length > 0) {
    results.from = CodeMirror.Pos(results.from.line, results.from.ch);
    results.to = CodeMirror.Pos(results.to.line, results.to.ch);
    CodeMirror.signal(editor, "hasCompletion", editor, results, token);
  }
  return results;
});
function getVariablesHint(cur, token, options) {
  const state = token.state.kind === "Invalid" ? token.state.prevState : token.state;
  const kind = state.kind;
  const step = state.step;
  if (kind === "Document" && step === 0) {
    return hintList(cur, token, [{ text: "{" }]);
  }
  const variableToType = options.variableToType;
  if (!variableToType) {
    return;
  }
  const typeInfo = getTypeInfo(variableToType, token.state);
  if (kind === "Document" || kind === "Variable" && step === 0) {
    const variableNames = Object.keys(variableToType);
    return hintList(cur, token, variableNames.map((name) => ({
      text: `"${name}": `,
      type: variableToType[name]
    })));
  }
  if (kind === "ObjectValue" || kind === "ObjectField" && step === 0) {
    if (typeInfo.fields) {
      const inputFields = Object.keys(typeInfo.fields).map((fieldName) => typeInfo.fields[fieldName]);
      return hintList(cur, token, inputFields.map((field) => ({
        text: `"${field.name}": `,
        type: field.type,
        description: field.description
      })));
    }
  }
  if (kind === "StringValue" || kind === "NumberValue" || kind === "BooleanValue" || kind === "NullValue" || kind === "ListValue" && step === 1 || kind === "ObjectField" && step === 2 || kind === "Variable" && step === 2) {
    const namedInputType = typeInfo.type ? getNamedType(typeInfo.type) : void 0;
    if (namedInputType instanceof GraphQLInputObjectType) {
      return hintList(cur, token, [{ text: "{" }]);
    } else if (namedInputType instanceof GraphQLEnumType) {
      const values = namedInputType.getValues();
      return hintList(cur, token, values.map((value) => ({
        text: `"${value.name}"`,
        type: namedInputType,
        description: value.description
      })));
    } else if (namedInputType === GraphQLBoolean) {
      return hintList(cur, token, [
        { text: "true", type: GraphQLBoolean, description: "Not false." },
        { text: "false", type: GraphQLBoolean, description: "Not true." }
      ]);
    }
  }
}
__name(getVariablesHint, "getVariablesHint");
function getTypeInfo(variableToType, tokenState) {
  const info = {
    type: null,
    fields: null
  };
  forEachState(tokenState, (state) => {
    if (state.kind === "Variable") {
      info.type = variableToType[state.name];
    } else if (state.kind === "ListValue") {
      const nullableType = info.type ? getNullableType(info.type) : void 0;
      info.type = nullableType instanceof GraphQLList ? nullableType.ofType : null;
    } else if (state.kind === "ObjectValue") {
      const objectType = info.type ? getNamedType(info.type) : void 0;
      info.fields = objectType instanceof GraphQLInputObjectType ? objectType.getFields() : null;
    } else if (state.kind === "ObjectField") {
      const objectField = state.name && info.fields ? info.fields[state.name] : null;
      info.type = objectField === null || objectField === void 0 ? void 0 : objectField.type;
    }
  });
  return info;
}
__name(getTypeInfo, "getTypeInfo");
