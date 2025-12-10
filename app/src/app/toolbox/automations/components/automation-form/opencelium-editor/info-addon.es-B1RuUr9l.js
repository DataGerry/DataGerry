import { C as CodeMirror } from "./codemirror.es-dDlEaI2D.js";
import "./index-BamfOqR5.js";
import "react";
import "react-dom";
var __defProp = Object.defineProperty;
var __name = (target, value) => __defProp(target, "name", { value, configurable: true });
CodeMirror.defineOption("info", false, (cm, options, old) => {
  if (old && old !== CodeMirror.Init) {
    const oldOnMouseOver = cm.state.info.onMouseOver;
    CodeMirror.off(cm.getWrapperElement(), "mouseover", oldOnMouseOver);
    clearTimeout(cm.state.info.hoverTimeout);
    delete cm.state.info;
  }
  if (options) {
    const state = cm.state.info = createState(options);
    state.onMouseOver = onMouseOver.bind(null, cm);
    CodeMirror.on(cm.getWrapperElement(), "mouseover", state.onMouseOver);
  }
});
function createState(options) {
  return {
    options: options instanceof Function ? { render: options } : options === true ? {} : options
  };
}
__name(createState, "createState");
function getHoverTime(cm) {
  const options = cm.state.info.options;
  return (options === null || options === void 0 ? void 0 : options.hoverTime) || 500;
}
__name(getHoverTime, "getHoverTime");
function onMouseOver(cm, e) {
  const state = cm.state.info;
  const target = e.target || e.srcElement;
  if (!(target instanceof HTMLElement)) {
    return;
  }
  if (target.nodeName !== "SPAN" || state.hoverTimeout !== void 0) {
    return;
  }
  const box = target.getBoundingClientRect();
  const onMouseMove = /* @__PURE__ */ __name(function() {
    clearTimeout(state.hoverTimeout);
    state.hoverTimeout = setTimeout(onHover, hoverTime);
  }, "onMouseMove");
  const onMouseOut = /* @__PURE__ */ __name(function() {
    CodeMirror.off(document, "mousemove", onMouseMove);
    CodeMirror.off(cm.getWrapperElement(), "mouseout", onMouseOut);
    clearTimeout(state.hoverTimeout);
    state.hoverTimeout = void 0;
  }, "onMouseOut");
  const onHover = /* @__PURE__ */ __name(function() {
    CodeMirror.off(document, "mousemove", onMouseMove);
    CodeMirror.off(cm.getWrapperElement(), "mouseout", onMouseOut);
    state.hoverTimeout = void 0;
    onMouseHover(cm, box);
  }, "onHover");
  const hoverTime = getHoverTime(cm);
  state.hoverTimeout = setTimeout(onHover, hoverTime);
  CodeMirror.on(document, "mousemove", onMouseMove);
  CodeMirror.on(cm.getWrapperElement(), "mouseout", onMouseOut);
}
__name(onMouseOver, "onMouseOver");
function onMouseHover(cm, box) {
  const pos = cm.coordsChar({
    left: (box.left + box.right) / 2,
    top: (box.top + box.bottom) / 2
  });
  const state = cm.state.info;
  const options = state.options;
  const render = options.render || cm.getHelper(pos, "info");
  if (render) {
    const token = cm.getTokenAt(pos, true);
    if (token) {
      const info = render(token, options, cm, pos);
      if (info) {
        showPopup(cm, box, info);
      }
    }
  }
}
__name(onMouseHover, "onMouseHover");
function showPopup(cm, box, info) {
  const popup = document.createElement("div");
  popup.className = "CodeMirror-info";
  popup.appendChild(info);
  document.body.appendChild(popup);
  const popupBox = popup.getBoundingClientRect();
  const popupStyle = window.getComputedStyle(popup);
  const popupWidth = popupBox.right - popupBox.left + parseFloat(popupStyle.marginLeft) + parseFloat(popupStyle.marginRight);
  const popupHeight = popupBox.bottom - popupBox.top + parseFloat(popupStyle.marginTop) + parseFloat(popupStyle.marginBottom);
  let topPos = box.bottom;
  if (popupHeight > window.innerHeight - box.bottom - 15 && box.top > window.innerHeight - box.bottom) {
    topPos = box.top - popupHeight;
  }
  if (topPos < 0) {
    topPos = box.bottom;
  }
  let leftPos = Math.max(0, window.innerWidth - popupWidth - 15);
  if (leftPos > box.left) {
    leftPos = box.left;
  }
  popup.style.opacity = "1";
  popup.style.top = topPos + "px";
  popup.style.left = leftPos + "px";
  let popupTimeout;
  const onMouseOverPopup = /* @__PURE__ */ __name(function() {
    clearTimeout(popupTimeout);
  }, "onMouseOverPopup");
  const onMouseOut = /* @__PURE__ */ __name(function() {
    clearTimeout(popupTimeout);
    popupTimeout = setTimeout(hidePopup, 200);
  }, "onMouseOut");
  const hidePopup = /* @__PURE__ */ __name(function() {
    CodeMirror.off(popup, "mouseover", onMouseOverPopup);
    CodeMirror.off(popup, "mouseout", onMouseOut);
    CodeMirror.off(cm.getWrapperElement(), "mouseout", onMouseOut);
    if (popup.style.opacity) {
      popup.style.opacity = "0";
      setTimeout(() => {
        if (popup.parentNode) {
          popup.parentNode.removeChild(popup);
        }
      }, 600);
    } else if (popup.parentNode) {
      popup.parentNode.removeChild(popup);
    }
  }, "hidePopup");
  CodeMirror.on(popup, "mouseover", onMouseOverPopup);
  CodeMirror.on(popup, "mouseout", onMouseOut);
  CodeMirror.on(cm.getWrapperElement(), "mouseout", onMouseOut);
}
__name(showPopup, "showPopup");
