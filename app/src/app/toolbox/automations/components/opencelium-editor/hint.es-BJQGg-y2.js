import { C as CodeMirror } from "./codemirror.es-DewG80bB.js";
import "./show-hint.es-D8fss2vN.js";
import { R as RuleKinds, C as CompletionItemKind, g as getNamedType, i as isInterfaceType, a as isCompositeType, T as TypeNameMetaFieldDef, S as SchemaMetaFieldDef, b as TypeMetaFieldDef, I as InsertTextFormat, G as GraphQLEnumType, c as GraphQLBoolean, d as isAbstractType, e as assertAbstractType, f as doTypesOverlap, v as visit, p as parse, h as isInputType, j as isListType, k as isNonNullType, K as Kind, D as DirectiveLocation, l as GraphQLInterfaceType, m as GraphQLObjectType, n as GraphQLInputObjectType, o as getNullableType, q as GraphQLList } from "./index-CgthTIXf.js";
import { P as Position, C as CharacterStream } from "./Range.es-CexH2elC.js";
import { o as onlineParser } from "./onlineParser.es-CqH_b6K3.js";
import { S as SchemaMetaFieldDef$1, T as TypeMetaFieldDef$1, a as TypeNameMetaFieldDef$1 } from "./introspection.es-B-0en2tI.js";
import "react";
import "react-dom";
var __defProp = Object.defineProperty;
var __name = (target, value) => __defProp(target, "name", { value, configurable: true });
function getDefinitionState(tokenState) {
  let definitionState;
  forEachState(tokenState, (state) => {
    switch (state.kind) {
      case "Query":
      case "ShortQuery":
      case "Mutation":
      case "Subscription":
      case "FragmentDefinition":
        definitionState = state;
        break;
    }
  });
  return definitionState;
}
__name(getDefinitionState, "getDefinitionState");
function getFieldDef(schema, type, fieldName) {
  if (fieldName === SchemaMetaFieldDef$1.name && schema.getQueryType() === type) {
    return SchemaMetaFieldDef$1;
  }
  if (fieldName === TypeMetaFieldDef$1.name && schema.getQueryType() === type) {
    return TypeMetaFieldDef$1;
  }
  if (fieldName === TypeNameMetaFieldDef$1.name && isCompositeType(type)) {
    return TypeNameMetaFieldDef$1;
  }
  if ("getFields" in type) {
    return type.getFields()[fieldName];
  }
  return null;
}
__name(getFieldDef, "getFieldDef");
function forEachState(stack, fn) {
  const reverseStateStack = [];
  let state = stack;
  while (state === null || state === void 0 ? void 0 : state.kind) {
    reverseStateStack.push(state);
    state = state.prevState;
  }
  for (let i = reverseStateStack.length - 1; i >= 0; i--) {
    fn(reverseStateStack[i]);
  }
}
__name(forEachState, "forEachState");
function objectValues(object) {
  const keys = Object.keys(object);
  const len = keys.length;
  const values = new Array(len);
  for (let i = 0; i < len; ++i) {
    values[i] = object[keys[i]];
  }
  return values;
}
__name(objectValues, "objectValues");
function hintList(token, list) {
  return filterAndSortList(list, normalizeText(token.string));
}
__name(hintList, "hintList");
function filterAndSortList(list, text) {
  if (!text) {
    return filterNonEmpty(list, (entry) => !entry.isDeprecated);
  }
  const byProximity = list.map((entry) => ({
    proximity: getProximity(normalizeText(entry.label), text),
    entry
  }));
  return filterNonEmpty(filterNonEmpty(byProximity, (pair) => pair.proximity <= 2), (pair) => !pair.entry.isDeprecated).sort((a, b) => (a.entry.isDeprecated ? 1 : 0) - (b.entry.isDeprecated ? 1 : 0) || a.proximity - b.proximity || a.entry.label.length - b.entry.label.length).map((pair) => pair.entry);
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
const SuggestionCommand = {
  command: "editor.action.triggerSuggest",
  title: "Suggestions"
};
const collectFragmentDefs = /* @__PURE__ */ __name((op) => {
  const externalFragments = [];
  if (op) {
    try {
      visit(parse(op), {
        FragmentDefinition(def) {
          externalFragments.push(def);
        }
      });
    } catch (_a) {
      return [];
    }
  }
  return externalFragments;
}, "collectFragmentDefs");
function getAutocompleteSuggestions(schema, queryText, cursor, contextToken, fragmentDefs, options) {
  var _a;
  const opts = Object.assign(Object.assign({}, options), { schema });
  const token = contextToken || getTokenAtPosition(queryText, cursor);
  const state = token.state.kind === "Invalid" ? token.state.prevState : token.state;
  if (!state) {
    return [];
  }
  const kind = state.kind;
  const step = state.step;
  const typeInfo = getTypeInfo(schema, token.state);
  if (kind === RuleKinds.DOCUMENT) {
    return hintList(token, [
      { label: "query", kind: CompletionItemKind.Function },
      { label: "mutation", kind: CompletionItemKind.Function },
      { label: "subscription", kind: CompletionItemKind.Function },
      { label: "fragment", kind: CompletionItemKind.Function },
      { label: "{", kind: CompletionItemKind.Constructor }
    ]);
  }
  if (kind === RuleKinds.IMPLEMENTS || kind === RuleKinds.NAMED_TYPE && ((_a = state.prevState) === null || _a === void 0 ? void 0 : _a.kind) === RuleKinds.IMPLEMENTS) {
    return getSuggestionsForImplements(token, state, schema, queryText, typeInfo);
  }
  if (kind === RuleKinds.SELECTION_SET || kind === RuleKinds.FIELD || kind === RuleKinds.ALIASED_FIELD) {
    return getSuggestionsForFieldNames(token, typeInfo, opts);
  }
  if (kind === RuleKinds.ARGUMENTS || kind === RuleKinds.ARGUMENT && step === 0) {
    const argDefs = typeInfo.argDefs;
    if (argDefs) {
      return hintList(token, argDefs.map((argDef) => {
        var _a2;
        return {
          label: argDef.name,
          insertText: argDef.name + ": ",
          command: SuggestionCommand,
          detail: String(argDef.type),
          documentation: (_a2 = argDef.description) !== null && _a2 !== void 0 ? _a2 : void 0,
          kind: CompletionItemKind.Variable,
          type: argDef.type
        };
      }));
    }
  }
  if (kind === RuleKinds.OBJECT_VALUE || kind === RuleKinds.OBJECT_FIELD && step === 0) {
    if (typeInfo.objectFieldDefs) {
      const objectFields = objectValues(typeInfo.objectFieldDefs);
      const completionKind = kind === RuleKinds.OBJECT_VALUE ? CompletionItemKind.Value : CompletionItemKind.Field;
      return hintList(token, objectFields.map((field) => {
        var _a2;
        return {
          label: field.name,
          detail: String(field.type),
          documentation: (_a2 = field.description) !== null && _a2 !== void 0 ? _a2 : void 0,
          kind: completionKind,
          type: field.type
        };
      }));
    }
  }
  if (kind === RuleKinds.ENUM_VALUE || kind === RuleKinds.LIST_VALUE && step === 1 || kind === RuleKinds.OBJECT_FIELD && step === 2 || kind === RuleKinds.ARGUMENT && step === 2) {
    return getSuggestionsForInputValues(token, typeInfo, queryText, schema);
  }
  if (kind === RuleKinds.VARIABLE && step === 1) {
    const namedInputType = getNamedType(typeInfo.inputType);
    const variableDefinitions = getVariableCompletions(queryText, schema, token);
    return hintList(token, variableDefinitions.filter((v) => v.detail === (namedInputType === null || namedInputType === void 0 ? void 0 : namedInputType.name)));
  }
  if (kind === RuleKinds.TYPE_CONDITION && step === 1 || kind === RuleKinds.NAMED_TYPE && state.prevState != null && state.prevState.kind === RuleKinds.TYPE_CONDITION) {
    return getSuggestionsForFragmentTypeConditions(token, typeInfo, schema);
  }
  if (kind === RuleKinds.FRAGMENT_SPREAD && step === 1) {
    return getSuggestionsForFragmentSpread(token, typeInfo, schema, queryText, Array.isArray(fragmentDefs) ? fragmentDefs : collectFragmentDefs(fragmentDefs));
  }
  if (kind === RuleKinds.VARIABLE_DEFINITION && step === 2 || kind === RuleKinds.LIST_TYPE && step === 1 || kind === RuleKinds.NAMED_TYPE && state.prevState && (state.prevState.kind === RuleKinds.VARIABLE_DEFINITION || state.prevState.kind === RuleKinds.LIST_TYPE || state.prevState.kind === RuleKinds.NON_NULL_TYPE)) {
    return getSuggestionsForVariableDefinition(token, schema);
  }
  if (kind === RuleKinds.DIRECTIVE) {
    return getSuggestionsForDirective(token, state, schema);
  }
  return [];
}
__name(getAutocompleteSuggestions, "getAutocompleteSuggestions");
const insertSuffix = ` {
  $1
}`;
const getInsertText = /* @__PURE__ */ __name((field) => {
  const type = field.type;
  if (isCompositeType(type)) {
    return insertSuffix;
  }
  if (isListType(type) && isCompositeType(type.ofType)) {
    return insertSuffix;
  }
  if (isNonNullType(type)) {
    if (isCompositeType(type.ofType)) {
      return insertSuffix;
    }
    if (isListType(type.ofType) && isCompositeType(type.ofType.ofType)) {
      return insertSuffix;
    }
  }
  return null;
}, "getInsertText");
function getSuggestionsForFieldNames(token, typeInfo, options) {
  var _a;
  if (typeInfo.parentType) {
    const parentType = typeInfo.parentType;
    let fields = [];
    if ("getFields" in parentType) {
      fields = objectValues(parentType.getFields());
    }
    if (isCompositeType(parentType)) {
      fields.push(TypeNameMetaFieldDef);
    }
    if (parentType === ((_a = options === null || options === void 0 ? void 0 : options.schema) === null || _a === void 0 ? void 0 : _a.getQueryType())) {
      fields.push(SchemaMetaFieldDef, TypeMetaFieldDef);
    }
    return hintList(token, fields.map((field, index) => {
      var _a2;
      const suggestion = {
        sortText: String(index) + field.name,
        label: field.name,
        detail: String(field.type),
        documentation: (_a2 = field.description) !== null && _a2 !== void 0 ? _a2 : void 0,
        deprecated: Boolean(field.deprecationReason),
        isDeprecated: Boolean(field.deprecationReason),
        deprecationReason: field.deprecationReason,
        kind: CompletionItemKind.Field,
        type: field.type
      };
      const insertText = getInsertText(field);
      if (insertText) {
        suggestion.insertText = field.name + insertText;
        suggestion.insertTextFormat = InsertTextFormat.Snippet;
        suggestion.command = SuggestionCommand;
      }
      return suggestion;
    }));
  }
  return [];
}
__name(getSuggestionsForFieldNames, "getSuggestionsForFieldNames");
function getSuggestionsForInputValues(token, typeInfo, queryText, schema) {
  const namedInputType = getNamedType(typeInfo.inputType);
  const queryVariables = getVariableCompletions(queryText, schema, token).filter((v) => v.detail === namedInputType.name);
  if (namedInputType instanceof GraphQLEnumType) {
    const values = namedInputType.getValues();
    return hintList(token, values.map((value) => {
      var _a;
      return {
        label: value.name,
        detail: String(namedInputType),
        documentation: (_a = value.description) !== null && _a !== void 0 ? _a : void 0,
        deprecated: Boolean(value.deprecationReason),
        isDeprecated: Boolean(value.deprecationReason),
        deprecationReason: value.deprecationReason,
        kind: CompletionItemKind.EnumMember,
        type: namedInputType
      };
    }).concat(queryVariables));
  } else if (namedInputType === GraphQLBoolean) {
    return hintList(token, queryVariables.concat([
      {
        label: "true",
        detail: String(GraphQLBoolean),
        documentation: "Not false.",
        kind: CompletionItemKind.Variable,
        type: GraphQLBoolean
      },
      {
        label: "false",
        detail: String(GraphQLBoolean),
        documentation: "Not true.",
        kind: CompletionItemKind.Variable,
        type: GraphQLBoolean
      }
    ]));
  }
  return queryVariables;
}
__name(getSuggestionsForInputValues, "getSuggestionsForInputValues");
function getSuggestionsForImplements(token, tokenState, schema, documentText, typeInfo) {
  if (tokenState.needsSeparator) {
    return [];
  }
  const typeMap = schema.getTypeMap();
  const schemaInterfaces = objectValues(typeMap).filter(isInterfaceType);
  const schemaInterfaceNames = schemaInterfaces.map(({ name }) => name);
  const inlineInterfaces = /* @__PURE__ */ new Set();
  runOnlineParser(documentText, (_, state) => {
    var _a, _b, _c, _d, _e;
    if (state.name) {
      if (state.kind === RuleKinds.INTERFACE_DEF && !schemaInterfaceNames.includes(state.name)) {
        inlineInterfaces.add(state.name);
      }
      if (state.kind === RuleKinds.NAMED_TYPE && ((_a = state.prevState) === null || _a === void 0 ? void 0 : _a.kind) === RuleKinds.IMPLEMENTS) {
        if (typeInfo.interfaceDef) {
          const existingType = (_b = typeInfo.interfaceDef) === null || _b === void 0 ? void 0 : _b.getInterfaces().find(({ name }) => name === state.name);
          if (existingType) {
            return;
          }
          const type = schema.getType(state.name);
          const interfaceConfig = (_c = typeInfo.interfaceDef) === null || _c === void 0 ? void 0 : _c.toConfig();
          typeInfo.interfaceDef = new GraphQLInterfaceType(Object.assign(Object.assign({}, interfaceConfig), { interfaces: [
            ...interfaceConfig.interfaces,
            type || new GraphQLInterfaceType({ name: state.name, fields: {} })
          ] }));
        } else if (typeInfo.objectTypeDef) {
          const existingType = (_d = typeInfo.objectTypeDef) === null || _d === void 0 ? void 0 : _d.getInterfaces().find(({ name }) => name === state.name);
          if (existingType) {
            return;
          }
          const type = schema.getType(state.name);
          const objectTypeConfig = (_e = typeInfo.objectTypeDef) === null || _e === void 0 ? void 0 : _e.toConfig();
          typeInfo.objectTypeDef = new GraphQLObjectType(Object.assign(Object.assign({}, objectTypeConfig), { interfaces: [
            ...objectTypeConfig.interfaces,
            type || new GraphQLInterfaceType({ name: state.name, fields: {} })
          ] }));
        }
      }
    }
  });
  const currentTypeToExtend = typeInfo.interfaceDef || typeInfo.objectTypeDef;
  const siblingInterfaces = (currentTypeToExtend === null || currentTypeToExtend === void 0 ? void 0 : currentTypeToExtend.getInterfaces()) || [];
  const siblingInterfaceNames = siblingInterfaces.map(({ name }) => name);
  const possibleInterfaces = schemaInterfaces.concat([...inlineInterfaces].map((name) => ({ name }))).filter(({ name }) => name !== (currentTypeToExtend === null || currentTypeToExtend === void 0 ? void 0 : currentTypeToExtend.name) && !siblingInterfaceNames.includes(name));
  return hintList(token, possibleInterfaces.map((type) => {
    const result = {
      label: type.name,
      kind: CompletionItemKind.Interface,
      type
    };
    if (type === null || type === void 0 ? void 0 : type.description) {
      result.documentation = type.description;
    }
    return result;
  }));
}
__name(getSuggestionsForImplements, "getSuggestionsForImplements");
function getSuggestionsForFragmentTypeConditions(token, typeInfo, schema, _kind) {
  let possibleTypes;
  if (typeInfo.parentType) {
    if (isAbstractType(typeInfo.parentType)) {
      const abstractType = assertAbstractType(typeInfo.parentType);
      const possibleObjTypes = schema.getPossibleTypes(abstractType);
      const possibleIfaceMap = /* @__PURE__ */ Object.create(null);
      possibleObjTypes.forEach((type) => {
        type.getInterfaces().forEach((iface) => {
          possibleIfaceMap[iface.name] = iface;
        });
      });
      possibleTypes = possibleObjTypes.concat(objectValues(possibleIfaceMap));
    } else {
      possibleTypes = [typeInfo.parentType];
    }
  } else {
    const typeMap = schema.getTypeMap();
    possibleTypes = objectValues(typeMap).filter(isCompositeType);
  }
  return hintList(token, possibleTypes.map((type) => {
    const namedType = getNamedType(type);
    return {
      label: String(type),
      documentation: (namedType === null || namedType === void 0 ? void 0 : namedType.description) || "",
      kind: CompletionItemKind.Field
    };
  }));
}
__name(getSuggestionsForFragmentTypeConditions, "getSuggestionsForFragmentTypeConditions");
function getSuggestionsForFragmentSpread(token, typeInfo, schema, queryText, fragmentDefs) {
  if (!queryText) {
    return [];
  }
  const typeMap = schema.getTypeMap();
  const defState = getDefinitionState(token.state);
  const fragments = getFragmentDefinitions(queryText);
  if (fragmentDefs && fragmentDefs.length > 0) {
    fragments.push(...fragmentDefs);
  }
  const relevantFrags = fragments.filter((frag) => typeMap[frag.typeCondition.name.value] && !(defState && defState.kind === RuleKinds.FRAGMENT_DEFINITION && defState.name === frag.name.value) && isCompositeType(typeInfo.parentType) && isCompositeType(typeMap[frag.typeCondition.name.value]) && doTypesOverlap(schema, typeInfo.parentType, typeMap[frag.typeCondition.name.value]));
  return hintList(token, relevantFrags.map((frag) => ({
    label: frag.name.value,
    detail: String(typeMap[frag.typeCondition.name.value]),
    documentation: `fragment ${frag.name.value} on ${frag.typeCondition.name.value}`,
    kind: CompletionItemKind.Field,
    type: typeMap[frag.typeCondition.name.value]
  })));
}
__name(getSuggestionsForFragmentSpread, "getSuggestionsForFragmentSpread");
const getParentDefinition = /* @__PURE__ */ __name((state, kind) => {
  var _a, _b, _c, _d, _e, _f, _g, _h, _j, _k;
  if (((_a = state.prevState) === null || _a === void 0 ? void 0 : _a.kind) === kind) {
    return state.prevState;
  }
  if (((_c = (_b = state.prevState) === null || _b === void 0 ? void 0 : _b.prevState) === null || _c === void 0 ? void 0 : _c.kind) === kind) {
    return state.prevState.prevState;
  }
  if (((_f = (_e = (_d = state.prevState) === null || _d === void 0 ? void 0 : _d.prevState) === null || _e === void 0 ? void 0 : _e.prevState) === null || _f === void 0 ? void 0 : _f.kind) === kind) {
    return state.prevState.prevState.prevState;
  }
  if (((_k = (_j = (_h = (_g = state.prevState) === null || _g === void 0 ? void 0 : _g.prevState) === null || _h === void 0 ? void 0 : _h.prevState) === null || _j === void 0 ? void 0 : _j.prevState) === null || _k === void 0 ? void 0 : _k.kind) === kind) {
    return state.prevState.prevState.prevState.prevState;
  }
}, "getParentDefinition");
function getVariableCompletions(queryText, schema, token) {
  let variableName = null;
  let variableType;
  const definitions = /* @__PURE__ */ Object.create({});
  runOnlineParser(queryText, (_, state) => {
    if ((state === null || state === void 0 ? void 0 : state.kind) === RuleKinds.VARIABLE && state.name) {
      variableName = state.name;
    }
    if ((state === null || state === void 0 ? void 0 : state.kind) === RuleKinds.NAMED_TYPE && variableName) {
      const parentDefinition = getParentDefinition(state, RuleKinds.TYPE);
      if (parentDefinition === null || parentDefinition === void 0 ? void 0 : parentDefinition.type) {
        variableType = schema.getType(parentDefinition === null || parentDefinition === void 0 ? void 0 : parentDefinition.type);
      }
    }
    if (variableName && variableType) {
      if (!definitions[variableName]) {
        definitions[variableName] = {
          detail: variableType.toString(),
          insertText: token.string === "$" ? variableName : "$" + variableName,
          label: variableName,
          type: variableType,
          kind: CompletionItemKind.Variable
        };
        variableName = null;
        variableType = null;
      }
    }
  });
  return objectValues(definitions);
}
__name(getVariableCompletions, "getVariableCompletions");
function getFragmentDefinitions(queryText) {
  const fragmentDefs = [];
  runOnlineParser(queryText, (_, state) => {
    if (state.kind === RuleKinds.FRAGMENT_DEFINITION && state.name && state.type) {
      fragmentDefs.push({
        kind: RuleKinds.FRAGMENT_DEFINITION,
        name: {
          kind: Kind.NAME,
          value: state.name
        },
        selectionSet: {
          kind: RuleKinds.SELECTION_SET,
          selections: []
        },
        typeCondition: {
          kind: RuleKinds.NAMED_TYPE,
          name: {
            kind: Kind.NAME,
            value: state.type
          }
        }
      });
    }
  });
  return fragmentDefs;
}
__name(getFragmentDefinitions, "getFragmentDefinitions");
function getSuggestionsForVariableDefinition(token, schema, _kind) {
  const inputTypeMap = schema.getTypeMap();
  const inputTypes = objectValues(inputTypeMap).filter(isInputType);
  return hintList(token, inputTypes.map((type) => ({
    label: type.name,
    documentation: type.description,
    kind: CompletionItemKind.Variable
  })));
}
__name(getSuggestionsForVariableDefinition, "getSuggestionsForVariableDefinition");
function getSuggestionsForDirective(token, state, schema, _kind) {
  var _a;
  if ((_a = state.prevState) === null || _a === void 0 ? void 0 : _a.kind) {
    const directives = schema.getDirectives().filter((directive) => canUseDirective(state.prevState, directive));
    return hintList(token, directives.map((directive) => ({
      label: directive.name,
      documentation: directive.description || "",
      kind: CompletionItemKind.Function
    })));
  }
  return [];
}
__name(getSuggestionsForDirective, "getSuggestionsForDirective");
function getTokenAtPosition(queryText, cursor) {
  let styleAtCursor = null;
  let stateAtCursor = null;
  let stringAtCursor = null;
  const token = runOnlineParser(queryText, (stream, state, style, index) => {
    if (index === cursor.line) {
      if (stream.getCurrentPosition() >= cursor.character) {
        styleAtCursor = style;
        stateAtCursor = Object.assign({}, state);
        stringAtCursor = stream.current();
        return "BREAK";
      }
    }
  });
  return {
    start: token.start,
    end: token.end,
    string: stringAtCursor || token.string,
    state: stateAtCursor || token.state,
    style: styleAtCursor || token.style
  };
}
__name(getTokenAtPosition, "getTokenAtPosition");
function runOnlineParser(queryText, callback) {
  const lines = queryText.split("\n");
  const parser = onlineParser();
  let state = parser.startState();
  let style = "";
  let stream = new CharacterStream("");
  for (let i = 0; i < lines.length; i++) {
    stream = new CharacterStream(lines[i]);
    while (!stream.eol()) {
      style = parser.token(stream, state);
      const code = callback(stream, state, style, i);
      if (code === "BREAK") {
        break;
      }
    }
    callback(stream, state, style, i);
    if (!state.kind) {
      state = parser.startState();
    }
  }
  return {
    start: stream.getStartOfToken(),
    end: stream.getCurrentPosition(),
    string: stream.current(),
    state,
    style
  };
}
__name(runOnlineParser, "runOnlineParser");
function canUseDirective(state, directive) {
  var _a;
  if (!state || !state.kind) {
    return false;
  }
  const kind = state.kind;
  const locations = directive.locations;
  switch (kind) {
    case RuleKinds.QUERY:
      return locations.indexOf(DirectiveLocation.QUERY) !== -1;
    case RuleKinds.MUTATION:
      return locations.indexOf(DirectiveLocation.MUTATION) !== -1;
    case RuleKinds.SUBSCRIPTION:
      return locations.indexOf(DirectiveLocation.SUBSCRIPTION) !== -1;
    case RuleKinds.FIELD:
    case RuleKinds.ALIASED_FIELD:
      return locations.indexOf(DirectiveLocation.FIELD) !== -1;
    case RuleKinds.FRAGMENT_DEFINITION:
      return locations.indexOf(DirectiveLocation.FRAGMENT_DEFINITION) !== -1;
    case RuleKinds.FRAGMENT_SPREAD:
      return locations.indexOf(DirectiveLocation.FRAGMENT_SPREAD) !== -1;
    case RuleKinds.INLINE_FRAGMENT:
      return locations.indexOf(DirectiveLocation.INLINE_FRAGMENT) !== -1;
    case RuleKinds.SCHEMA_DEF:
      return locations.indexOf(DirectiveLocation.SCHEMA) !== -1;
    case RuleKinds.SCALAR_DEF:
      return locations.indexOf(DirectiveLocation.SCALAR) !== -1;
    case RuleKinds.OBJECT_TYPE_DEF:
      return locations.indexOf(DirectiveLocation.OBJECT) !== -1;
    case RuleKinds.FIELD_DEF:
      return locations.indexOf(DirectiveLocation.FIELD_DEFINITION) !== -1;
    case RuleKinds.INTERFACE_DEF:
      return locations.indexOf(DirectiveLocation.INTERFACE) !== -1;
    case RuleKinds.UNION_DEF:
      return locations.indexOf(DirectiveLocation.UNION) !== -1;
    case RuleKinds.ENUM_DEF:
      return locations.indexOf(DirectiveLocation.ENUM) !== -1;
    case RuleKinds.ENUM_VALUE:
      return locations.indexOf(DirectiveLocation.ENUM_VALUE) !== -1;
    case RuleKinds.INPUT_DEF:
      return locations.indexOf(DirectiveLocation.INPUT_OBJECT) !== -1;
    case RuleKinds.INPUT_VALUE_DEF:
      const prevStateKind = (_a = state.prevState) === null || _a === void 0 ? void 0 : _a.kind;
      switch (prevStateKind) {
        case RuleKinds.ARGUMENTS_DEF:
          return locations.indexOf(DirectiveLocation.ARGUMENT_DEFINITION) !== -1;
        case RuleKinds.INPUT_DEF:
          return locations.indexOf(DirectiveLocation.INPUT_FIELD_DEFINITION) !== -1;
      }
  }
  return false;
}
__name(canUseDirective, "canUseDirective");
function getTypeInfo(schema, tokenState) {
  let argDef;
  let argDefs;
  let directiveDef;
  let enumValue;
  let fieldDef;
  let inputType;
  let objectTypeDef;
  let objectFieldDefs;
  let parentType;
  let type;
  let interfaceDef;
  forEachState(tokenState, (state) => {
    var _a;
    switch (state.kind) {
      case RuleKinds.QUERY:
      case "ShortQuery":
        type = schema.getQueryType();
        break;
      case RuleKinds.MUTATION:
        type = schema.getMutationType();
        break;
      case RuleKinds.SUBSCRIPTION:
        type = schema.getSubscriptionType();
        break;
      case RuleKinds.INLINE_FRAGMENT:
      case RuleKinds.FRAGMENT_DEFINITION:
        if (state.type) {
          type = schema.getType(state.type);
        }
        break;
      case RuleKinds.FIELD:
      case RuleKinds.ALIASED_FIELD: {
        if (!type || !state.name) {
          fieldDef = null;
        } else {
          fieldDef = parentType ? getFieldDef(schema, parentType, state.name) : null;
          type = fieldDef ? fieldDef.type : null;
        }
        break;
      }
      case RuleKinds.SELECTION_SET:
        parentType = getNamedType(type);
        break;
      case RuleKinds.DIRECTIVE:
        directiveDef = state.name ? schema.getDirective(state.name) : null;
        break;
      case RuleKinds.INTERFACE_DEF:
        if (state.name) {
          objectTypeDef = null;
          interfaceDef = new GraphQLInterfaceType({
            name: state.name,
            interfaces: [],
            fields: {}
          });
        }
        break;
      case RuleKinds.OBJECT_TYPE_DEF:
        if (state.name) {
          interfaceDef = null;
          objectTypeDef = new GraphQLObjectType({
            name: state.name,
            interfaces: [],
            fields: {}
          });
        }
        break;
      case RuleKinds.ARGUMENTS: {
        if (!state.prevState) {
          argDefs = null;
        } else {
          switch (state.prevState.kind) {
            case RuleKinds.FIELD:
              argDefs = fieldDef && fieldDef.args;
              break;
            case RuleKinds.DIRECTIVE:
              argDefs = directiveDef && directiveDef.args;
              break;
            case RuleKinds.ALIASED_FIELD: {
              const name = (_a = state.prevState) === null || _a === void 0 ? void 0 : _a.name;
              if (!name) {
                argDefs = null;
                break;
              }
              const field = parentType ? getFieldDef(schema, parentType, name) : null;
              if (!field) {
                argDefs = null;
                break;
              }
              argDefs = field.args;
              break;
            }
            default:
              argDefs = null;
              break;
          }
        }
        break;
      }
      case RuleKinds.ARGUMENT:
        if (argDefs) {
          for (let i = 0; i < argDefs.length; i++) {
            if (argDefs[i].name === state.name) {
              argDef = argDefs[i];
              break;
            }
          }
        }
        inputType = argDef === null || argDef === void 0 ? void 0 : argDef.type;
        break;
      case RuleKinds.ENUM_VALUE:
        const enumType = getNamedType(inputType);
        enumValue = enumType instanceof GraphQLEnumType ? enumType.getValues().find((val) => val.value === state.name) : null;
        break;
      case RuleKinds.LIST_VALUE:
        const nullableType = getNullableType(inputType);
        inputType = nullableType instanceof GraphQLList ? nullableType.ofType : null;
        break;
      case RuleKinds.OBJECT_VALUE:
        const objectType = getNamedType(inputType);
        objectFieldDefs = objectType instanceof GraphQLInputObjectType ? objectType.getFields() : null;
        break;
      case RuleKinds.OBJECT_FIELD:
        const objectField = state.name && objectFieldDefs ? objectFieldDefs[state.name] : null;
        inputType = objectField === null || objectField === void 0 ? void 0 : objectField.type;
        break;
      case RuleKinds.NAMED_TYPE:
        if (state.name) {
          type = schema.getType(state.name);
        }
        break;
    }
  });
  return {
    argDef,
    argDefs,
    directiveDef,
    enumValue,
    fieldDef,
    inputType,
    objectFieldDefs,
    parentType,
    type,
    interfaceDef,
    objectTypeDef
  };
}
__name(getTypeInfo, "getTypeInfo");
CodeMirror.registerHelper("hint", "graphql", (editor, options) => {
  const schema = options.schema;
  if (!schema) {
    return;
  }
  const cur = editor.getCursor();
  const token = editor.getTokenAt(cur);
  const tokenStart = token.type !== null && /"|\w/.test(token.string[0]) ? token.start : token.end;
  const position = new Position(cur.line, tokenStart);
  const rawResults = getAutocompleteSuggestions(schema, editor.getValue(), position, token, options.externalFragments);
  const results = {
    list: rawResults.map((item) => ({
      text: item.label,
      type: item.type,
      description: item.documentation,
      isDeprecated: item.isDeprecated,
      deprecationReason: item.deprecationReason
    })),
    from: { line: cur.line, ch: tokenStart },
    to: { line: cur.line, ch: token.end }
  };
  if ((results === null || results === void 0 ? void 0 : results.list) && results.list.length > 0) {
    results.from = CodeMirror.Pos(results.from.line, results.from.ch);
    results.to = CodeMirror.Pos(results.to.line, results.to.ch);
    CodeMirror.signal(editor, "hasCompletion", editor, results, token);
  }
  return results;
});
