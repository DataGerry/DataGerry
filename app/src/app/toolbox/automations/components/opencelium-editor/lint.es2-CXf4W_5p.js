import { C as CodeMirror } from "./codemirror.es-BKAcH5QB.js";
import { a4 as GraphQLNonNull, q as GraphQLList, n as GraphQLInputObjectType, G as GraphQLEnumType, a8 as GraphQLScalarType } from "./index-C3ZYzSYT.js";
import "react";
import "react-dom";
var __defProp = Object.defineProperty;
var __name = (target, value) => __defProp(target, "name", { value, configurable: true });
function jsonParse(str) {
  string = str;
  strLen = str.length;
  start = end = lastEnd = -1;
  ch();
  lex();
  const ast = parseObj();
  expect("EOF");
  return ast;
}
__name(jsonParse, "jsonParse");
let string;
let strLen;
let start;
let end;
let lastEnd;
let code;
let kind;
function parseObj() {
  const nodeStart = start;
  const members = [];
  expect("{");
  if (!skip("}")) {
    do {
      members.push(parseMember());
    } while (skip(","));
    expect("}");
  }
  return {
    kind: "Object",
    start: nodeStart,
    end: lastEnd,
    members
  };
}
__name(parseObj, "parseObj");
function parseMember() {
  const nodeStart = start;
  const key = kind === "String" ? curToken() : null;
  expect("String");
  expect(":");
  const value = parseVal();
  return {
    kind: "Member",
    start: nodeStart,
    end: lastEnd,
    key,
    value
  };
}
__name(parseMember, "parseMember");
function parseArr() {
  const nodeStart = start;
  const values = [];
  expect("[");
  if (!skip("]")) {
    do {
      values.push(parseVal());
    } while (skip(","));
    expect("]");
  }
  return {
    kind: "Array",
    start: nodeStart,
    end: lastEnd,
    values
  };
}
__name(parseArr, "parseArr");
function parseVal() {
  switch (kind) {
    case "[":
      return parseArr();
    case "{":
      return parseObj();
    case "String":
    case "Number":
    case "Boolean":
    case "Null":
      const token = curToken();
      lex();
      return token;
  }
  expect("Value");
}
__name(parseVal, "parseVal");
function curToken() {
  return { kind, start, end, value: JSON.parse(string.slice(start, end)) };
}
__name(curToken, "curToken");
function expect(str) {
  if (kind === str) {
    lex();
    return;
  }
  let found;
  if (kind === "EOF") {
    found = "[end of file]";
  } else if (end - start > 1) {
    found = "`" + string.slice(start, end) + "`";
  } else {
    const match = string.slice(start).match(/^.+?\b/);
    found = "`" + (match ? match[0] : string[start]) + "`";
  }
  throw syntaxError(`Expected ${str} but found ${found}.`);
}
__name(expect, "expect");
class JSONSyntaxError extends Error {
  constructor(message, position) {
    super(message);
    this.position = position;
  }
}
__name(JSONSyntaxError, "JSONSyntaxError");
function syntaxError(message) {
  return new JSONSyntaxError(message, { start, end });
}
__name(syntaxError, "syntaxError");
function skip(k) {
  if (kind === k) {
    lex();
    return true;
  }
}
__name(skip, "skip");
function ch() {
  if (end < strLen) {
    end++;
    code = end === strLen ? 0 : string.charCodeAt(end);
  }
  return code;
}
__name(ch, "ch");
function lex() {
  lastEnd = end;
  while (code === 9 || code === 10 || code === 13 || code === 32) {
    ch();
  }
  if (code === 0) {
    kind = "EOF";
    return;
  }
  start = end;
  switch (code) {
    case 34:
      kind = "String";
      return readString();
    case 45:
    case 48:
    case 49:
    case 50:
    case 51:
    case 52:
    case 53:
    case 54:
    case 55:
    case 56:
    case 57:
      kind = "Number";
      return readNumber();
    case 102:
      if (string.slice(start, start + 5) !== "false") {
        break;
      }
      end += 4;
      ch();
      kind = "Boolean";
      return;
    case 110:
      if (string.slice(start, start + 4) !== "null") {
        break;
      }
      end += 3;
      ch();
      kind = "Null";
      return;
    case 116:
      if (string.slice(start, start + 4) !== "true") {
        break;
      }
      end += 3;
      ch();
      kind = "Boolean";
      return;
  }
  kind = string[start];
  ch();
}
__name(lex, "lex");
function readString() {
  ch();
  while (code !== 34 && code > 31) {
    if (code === 92) {
      code = ch();
      switch (code) {
        case 34:
        case 47:
        case 92:
        case 98:
        case 102:
        case 110:
        case 114:
        case 116:
          ch();
          break;
        case 117:
          ch();
          readHex();
          readHex();
          readHex();
          readHex();
          break;
        default:
          throw syntaxError("Bad character escape sequence.");
      }
    } else if (end === strLen) {
      throw syntaxError("Unterminated string.");
    } else {
      ch();
    }
  }
  if (code === 34) {
    ch();
    return;
  }
  throw syntaxError("Unterminated string.");
}
__name(readString, "readString");
function readHex() {
  if (code >= 48 && code <= 57 || code >= 65 && code <= 70 || code >= 97 && code <= 102) {
    return ch();
  }
  throw syntaxError("Expected hexadecimal digit.");
}
__name(readHex, "readHex");
function readNumber() {
  if (code === 45) {
    ch();
  }
  if (code === 48) {
    ch();
  } else {
    readDigits();
  }
  if (code === 46) {
    ch();
    readDigits();
  }
  if (code === 69 || code === 101) {
    code = ch();
    if (code === 43 || code === 45) {
      ch();
    }
    readDigits();
  }
}
__name(readNumber, "readNumber");
function readDigits() {
  if (code < 48 || code > 57) {
    throw syntaxError("Expected decimal digit.");
  }
  do {
    ch();
  } while (code >= 48 && code <= 57);
}
__name(readDigits, "readDigits");
CodeMirror.registerHelper("lint", "graphql-variables", (text, options, editor) => {
  if (!text) {
    return [];
  }
  let ast;
  try {
    ast = jsonParse(text);
  } catch (error) {
    if (error instanceof JSONSyntaxError) {
      return [lintError(editor, error.position, error.message)];
    }
    throw error;
  }
  const variableToType = options.variableToType;
  if (!variableToType) {
    return [];
  }
  return validateVariables(editor, variableToType, ast);
});
function validateVariables(editor, variableToType, variablesAST) {
  const errors = [];
  variablesAST.members.forEach((member) => {
    var _a;
    if (member) {
      const variableName = (_a = member.key) === null || _a === void 0 ? void 0 : _a.value;
      const type = variableToType[variableName];
      if (!type) {
        errors.push(lintError(editor, member.key, `Variable "$${variableName}" does not appear in any GraphQL query.`));
      } else {
        validateValue(type, member.value).forEach(([node, message]) => {
          errors.push(lintError(editor, node, message));
        });
      }
    }
  });
  return errors;
}
__name(validateVariables, "validateVariables");
function validateValue(type, valueAST) {
  if (!type || !valueAST) {
    return [];
  }
  if (type instanceof GraphQLNonNull) {
    if (valueAST.kind === "Null") {
      return [[valueAST, `Type "${type}" is non-nullable and cannot be null.`]];
    }
    return validateValue(type.ofType, valueAST);
  }
  if (valueAST.kind === "Null") {
    return [];
  }
  if (type instanceof GraphQLList) {
    const itemType = type.ofType;
    if (valueAST.kind === "Array") {
      const values = valueAST.values || [];
      return mapCat(values, (item) => validateValue(itemType, item));
    }
    return validateValue(itemType, valueAST);
  }
  if (type instanceof GraphQLInputObjectType) {
    if (valueAST.kind !== "Object") {
      return [[valueAST, `Type "${type}" must be an Object.`]];
    }
    const providedFields = /* @__PURE__ */ Object.create(null);
    const fieldErrors = mapCat(valueAST.members, (member) => {
      var _a;
      const fieldName = (_a = member === null || member === void 0 ? void 0 : member.key) === null || _a === void 0 ? void 0 : _a.value;
      providedFields[fieldName] = true;
      const inputField = type.getFields()[fieldName];
      if (!inputField) {
        return [
          [
            member.key,
            `Type "${type}" does not have a field "${fieldName}".`
          ]
        ];
      }
      const fieldType = inputField ? inputField.type : void 0;
      return validateValue(fieldType, member.value);
    });
    Object.keys(type.getFields()).forEach((fieldName) => {
      if (!providedFields[fieldName]) {
        const fieldType = type.getFields()[fieldName].type;
        if (fieldType instanceof GraphQLNonNull) {
          fieldErrors.push([
            valueAST,
            `Object of type "${type}" is missing required field "${fieldName}".`
          ]);
        }
      }
    });
    return fieldErrors;
  }
  if (type.name === "Boolean" && valueAST.kind !== "Boolean" || type.name === "String" && valueAST.kind !== "String" || type.name === "ID" && valueAST.kind !== "Number" && valueAST.kind !== "String" || type.name === "Float" && valueAST.kind !== "Number" || type.name === "Int" && (valueAST.kind !== "Number" || (valueAST.value | 0) !== valueAST.value)) {
    return [[valueAST, `Expected value of type "${type}".`]];
  }
  if (type instanceof GraphQLEnumType || type instanceof GraphQLScalarType) {
    if (valueAST.kind !== "String" && valueAST.kind !== "Number" && valueAST.kind !== "Boolean" && valueAST.kind !== "Null" || isNullish(type.parseValue(valueAST.value))) {
      return [[valueAST, `Expected value of type "${type}".`]];
    }
  }
  return [];
}
__name(validateValue, "validateValue");
function lintError(editor, node, message) {
  return {
    message,
    severity: "error",
    type: "validation",
    from: editor.posFromIndex(node.start),
    to: editor.posFromIndex(node.end)
  };
}
__name(lintError, "lintError");
function isNullish(value) {
  return value === null || value === void 0 || value !== value;
}
__name(isNullish, "isNullish");
function mapCat(array, mapper) {
  return Array.prototype.concat.apply([], array.map(mapper));
}
__name(mapCat, "mapCat");
