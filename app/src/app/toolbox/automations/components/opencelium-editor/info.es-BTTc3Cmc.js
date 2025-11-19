import { C as CodeMirror } from "./codemirror.es-BKAcH5QB.js";
import { g as getTypeInfo, a as getFieldReference, b as getDirectiveReference, c as getArgumentReference, d as getEnumValueReference, e as getTypeReference } from "./SchemaReference.es-CnDCsrFK.js";
import "./info-addon.es-pg50AfnV.js";
import { a4 as GraphQLNonNull, q as GraphQLList } from "./index-C3ZYzSYT.js";
import "react";
import "react-dom";
import "./introspection.es-B-0en2tI.js";
import "./forEachState.es-Bu9VKDOE.js";
var __defProp = Object.defineProperty;
var __name = (target, value) => __defProp(target, "name", { value, configurable: true });
CodeMirror.registerHelper("info", "graphql", (token, options) => {
  if (!options.schema || !token.state) {
    return;
  }
  const state = token.state;
  const kind = state.kind;
  const step = state.step;
  const typeInfo = getTypeInfo(options.schema, token.state);
  if (kind === "Field" && step === 0 && typeInfo.fieldDef || kind === "AliasedField" && step === 2 && typeInfo.fieldDef) {
    const into = document.createElement("div");
    renderField(into, typeInfo, options);
    renderDescription(into, options, typeInfo.fieldDef);
    return into;
  } else if (kind === "Directive" && step === 1 && typeInfo.directiveDef) {
    const into = document.createElement("div");
    renderDirective(into, typeInfo, options);
    renderDescription(into, options, typeInfo.directiveDef);
    return into;
  } else if (kind === "Argument" && step === 0 && typeInfo.argDef) {
    const into = document.createElement("div");
    renderArg(into, typeInfo, options);
    renderDescription(into, options, typeInfo.argDef);
    return into;
  } else if (kind === "EnumValue" && typeInfo.enumValue && typeInfo.enumValue.description) {
    const into = document.createElement("div");
    renderEnumValue(into, typeInfo, options);
    renderDescription(into, options, typeInfo.enumValue);
    return into;
  } else if (kind === "NamedType" && typeInfo.type && typeInfo.type.description) {
    const into = document.createElement("div");
    renderType(into, typeInfo, options, typeInfo.type);
    renderDescription(into, options, typeInfo.type);
    return into;
  }
});
function renderField(into, typeInfo, options) {
  renderQualifiedField(into, typeInfo, options);
  renderTypeAnnotation(into, typeInfo, options, typeInfo.type);
}
__name(renderField, "renderField");
function renderQualifiedField(into, typeInfo, options) {
  var _a;
  const fieldName = ((_a = typeInfo.fieldDef) === null || _a === void 0 ? void 0 : _a.name) || "";
  if (fieldName.slice(0, 2) !== "__") {
    renderType(into, typeInfo, options, typeInfo.parentType);
    text(into, ".");
  }
  text(into, fieldName, "field-name", options, getFieldReference(typeInfo));
}
__name(renderQualifiedField, "renderQualifiedField");
function renderDirective(into, typeInfo, options) {
  var _a;
  const name = "@" + (((_a = typeInfo.directiveDef) === null || _a === void 0 ? void 0 : _a.name) || "");
  text(into, name, "directive-name", options, getDirectiveReference(typeInfo));
}
__name(renderDirective, "renderDirective");
function renderArg(into, typeInfo, options) {
  var _a;
  if (typeInfo.directiveDef) {
    renderDirective(into, typeInfo, options);
  } else if (typeInfo.fieldDef) {
    renderQualifiedField(into, typeInfo, options);
  }
  const name = ((_a = typeInfo.argDef) === null || _a === void 0 ? void 0 : _a.name) || "";
  text(into, "(");
  text(into, name, "arg-name", options, getArgumentReference(typeInfo));
  renderTypeAnnotation(into, typeInfo, options, typeInfo.inputType);
  text(into, ")");
}
__name(renderArg, "renderArg");
function renderTypeAnnotation(into, typeInfo, options, t) {
  text(into, ": ");
  renderType(into, typeInfo, options, t);
}
__name(renderTypeAnnotation, "renderTypeAnnotation");
function renderEnumValue(into, typeInfo, options) {
  var _a;
  const name = ((_a = typeInfo.enumValue) === null || _a === void 0 ? void 0 : _a.name) || "";
  renderType(into, typeInfo, options, typeInfo.inputType);
  text(into, ".");
  text(into, name, "enum-value", options, getEnumValueReference(typeInfo));
}
__name(renderEnumValue, "renderEnumValue");
function renderType(into, typeInfo, options, t) {
  if (t instanceof GraphQLNonNull) {
    renderType(into, typeInfo, options, t.ofType);
    text(into, "!");
  } else if (t instanceof GraphQLList) {
    text(into, "[");
    renderType(into, typeInfo, options, t.ofType);
    text(into, "]");
  } else {
    text(into, (t === null || t === void 0 ? void 0 : t.name) || "", "type-name", options, getTypeReference(typeInfo, t));
  }
}
__name(renderType, "renderType");
function renderDescription(into, options, def) {
  const description = def.description;
  if (description) {
    const descriptionDiv = document.createElement("div");
    descriptionDiv.className = "info-description";
    if (options.renderDescription) {
      descriptionDiv.innerHTML = options.renderDescription(description);
    } else {
      descriptionDiv.appendChild(document.createTextNode(description));
    }
    into.appendChild(descriptionDiv);
  }
  renderDeprecation(into, options, def);
}
__name(renderDescription, "renderDescription");
function renderDeprecation(into, options, def) {
  const reason = def.deprecationReason;
  if (reason) {
    const deprecationDiv = document.createElement("div");
    deprecationDiv.className = "info-deprecation";
    if (options.renderDescription) {
      deprecationDiv.innerHTML = options.renderDescription(reason);
    } else {
      deprecationDiv.appendChild(document.createTextNode(reason));
    }
    const label = document.createElement("span");
    label.className = "info-deprecation-label";
    label.appendChild(document.createTextNode("Deprecated: "));
    deprecationDiv.insertBefore(label, deprecationDiv.firstChild);
    into.appendChild(deprecationDiv);
  }
}
__name(renderDeprecation, "renderDeprecation");
function text(into, content, className = "", options = { onClick: null }, ref = null) {
  if (className) {
    const onClick = options.onClick;
    let node;
    if (onClick) {
      node = document.createElement("a");
      node.href = "javascript:void 0";
      node.addEventListener("click", (e) => {
        onClick(ref, e);
      });
    } else {
      node = document.createElement("span");
    }
    node.className = className;
    node.appendChild(document.createTextNode(content));
    into.appendChild(node);
  } else {
    into.appendChild(document.createTextNode(content));
  }
}
__name(text, "text");
