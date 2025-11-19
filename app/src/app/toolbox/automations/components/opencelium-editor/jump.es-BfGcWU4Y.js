import { C as CodeMirror } from "./codemirror.es-DeWroV-8.js";
import { g as getTypeInfo, a as getFieldReference, b as getDirectiveReference, c as getArgumentReference, d as getEnumValueReference, e as getTypeReference } from "./SchemaReference.es-BgWTY9qZ.js";
import "./index-BL2fvCQ5.js";
import "react";
import "react-dom";
import "./introspection.es-B-0en2tI.js";
import "./forEachState.es-Bu9VKDOE.js";
var __defProp = Object.defineProperty;
var __name = (target, value) => __defProp(target, "name", { value, configurable: true });
CodeMirror.defineOption("jump", false, (cm, options, old) => {
  if (old && old !== CodeMirror.Init) {
    const oldOnMouseOver = cm.state.jump.onMouseOver;
    CodeMirror.off(cm.getWrapperElement(), "mouseover", oldOnMouseOver);
    const oldOnMouseOut = cm.state.jump.onMouseOut;
    CodeMirror.off(cm.getWrapperElement(), "mouseout", oldOnMouseOut);
    CodeMirror.off(document, "keydown", cm.state.jump.onKeyDown);
    delete cm.state.jump;
  }
  if (options) {
    const state = cm.state.jump = {
      options,
      onMouseOver: onMouseOver.bind(null, cm),
      onMouseOut: onMouseOut.bind(null, cm),
      onKeyDown: onKeyDown.bind(null, cm)
    };
    CodeMirror.on(cm.getWrapperElement(), "mouseover", state.onMouseOver);
    CodeMirror.on(cm.getWrapperElement(), "mouseout", state.onMouseOut);
    CodeMirror.on(document, "keydown", state.onKeyDown);
  }
});
function onMouseOver(cm, event) {
  const target = event.target || event.srcElement;
  if (!(target instanceof HTMLElement)) {
    return;
  }
  if ((target === null || target === void 0 ? void 0 : target.nodeName) !== "SPAN") {
    return;
  }
  const box = target.getBoundingClientRect();
  const cursor = {
    left: (box.left + box.right) / 2,
    top: (box.top + box.bottom) / 2
  };
  cm.state.jump.cursor = cursor;
  if (cm.state.jump.isHoldingModifier) {
    enableJumpMode(cm);
  }
}
__name(onMouseOver, "onMouseOver");
function onMouseOut(cm) {
  if (!cm.state.jump.isHoldingModifier && cm.state.jump.cursor) {
    cm.state.jump.cursor = null;
    return;
  }
  if (cm.state.jump.isHoldingModifier && cm.state.jump.marker) {
    disableJumpMode(cm);
  }
}
__name(onMouseOut, "onMouseOut");
function onKeyDown(cm, event) {
  if (cm.state.jump.isHoldingModifier || !isJumpModifier(event.key)) {
    return;
  }
  cm.state.jump.isHoldingModifier = true;
  if (cm.state.jump.cursor) {
    enableJumpMode(cm);
  }
  const onKeyUp = /* @__PURE__ */ __name((upEvent) => {
    if (upEvent.code !== event.code) {
      return;
    }
    cm.state.jump.isHoldingModifier = false;
    if (cm.state.jump.marker) {
      disableJumpMode(cm);
    }
    CodeMirror.off(document, "keyup", onKeyUp);
    CodeMirror.off(document, "click", onClick);
    cm.off("mousedown", onMouseDown);
  }, "onKeyUp");
  const onClick = /* @__PURE__ */ __name((clickEvent) => {
    const destination = cm.state.jump.destination;
    if (destination) {
      cm.state.jump.options.onClick(destination, clickEvent);
    }
  }, "onClick");
  const onMouseDown = /* @__PURE__ */ __name((_, downEvent) => {
    if (cm.state.jump.destination) {
      downEvent.codemirrorIgnore = true;
    }
  }, "onMouseDown");
  CodeMirror.on(document, "keyup", onKeyUp);
  CodeMirror.on(document, "click", onClick);
  cm.on("mousedown", onMouseDown);
}
__name(onKeyDown, "onKeyDown");
const isMac = typeof navigator !== "undefined" && navigator && navigator.appVersion.indexOf("Mac") !== -1;
function isJumpModifier(key) {
  return key === (isMac ? "Meta" : "Control");
}
__name(isJumpModifier, "isJumpModifier");
function enableJumpMode(cm) {
  if (cm.state.jump.marker) {
    return;
  }
  const cursor = cm.state.jump.cursor;
  const pos = cm.coordsChar(cursor);
  const token = cm.getTokenAt(pos, true);
  const options = cm.state.jump.options;
  const getDestination = options.getDestination || cm.getHelper(pos, "jump");
  if (getDestination) {
    const destination = getDestination(token, options, cm);
    if (destination) {
      const marker = cm.markText({ line: pos.line, ch: token.start }, { line: pos.line, ch: token.end }, { className: "CodeMirror-jump-token" });
      cm.state.jump.marker = marker;
      cm.state.jump.destination = destination;
    }
  }
}
__name(enableJumpMode, "enableJumpMode");
function disableJumpMode(cm) {
  const marker = cm.state.jump.marker;
  cm.state.jump.marker = null;
  cm.state.jump.destination = null;
  marker.clear();
}
__name(disableJumpMode, "disableJumpMode");
CodeMirror.registerHelper("jump", "graphql", (token, options) => {
  if (!options.schema || !options.onClick || !token.state) {
    return;
  }
  const state = token.state;
  const kind = state.kind;
  const step = state.step;
  const typeInfo = getTypeInfo(options.schema, state);
  if (kind === "Field" && step === 0 && typeInfo.fieldDef || kind === "AliasedField" && step === 2 && typeInfo.fieldDef) {
    return getFieldReference(typeInfo);
  } else if (kind === "Directive" && step === 1 && typeInfo.directiveDef) {
    return getDirectiveReference(typeInfo);
  } else if (kind === "Argument" && step === 0 && typeInfo.argDef) {
    return getArgumentReference(typeInfo);
  } else if (kind === "EnumValue" && typeInfo.enumValue) {
    return getEnumValueReference(typeInfo);
  } else if (kind === "NamedType" && typeInfo.type) {
    return getTypeReference(typeInfo);
  }
});
