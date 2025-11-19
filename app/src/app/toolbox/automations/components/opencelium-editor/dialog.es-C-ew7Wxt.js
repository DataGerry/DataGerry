import { a as codemirror$1 } from "./codemirror.es-BKAcH5QB.js";
var __defProp = Object.defineProperty;
var __name = (target, value) => __defProp(target, "name", { value, configurable: true });
function _mergeNamespaces$1(n, m) {
  m.forEach(function(e) {
    e && typeof e !== "string" && !Array.isArray(e) && Object.keys(e).forEach(function(k) {
      if (k !== "default" && !(k in n)) {
        var d = Object.getOwnPropertyDescriptor(e, k);
        Object.defineProperty(n, k, d.get ? d : {
          enumerable: true,
          get: function() {
            return e[k];
          }
        });
      }
    });
  });
  return Object.freeze(n);
}
__name(_mergeNamespaces$1, "_mergeNamespaces");
var dialog$2 = { exports: {} };
(function(module, exports$1) {
  (function(mod) {
    mod(codemirror$1.exports);
  })(function(CodeMirror) {
    function dialogDiv(cm, template, bottom) {
      var wrap = cm.getWrapperElement();
      var dialog2;
      dialog2 = wrap.appendChild(document.createElement("div"));
      if (bottom)
        dialog2.className = "CodeMirror-dialog CodeMirror-dialog-bottom";
      else
        dialog2.className = "CodeMirror-dialog CodeMirror-dialog-top";
      if (typeof template == "string") {
        dialog2.innerHTML = template;
      } else {
        dialog2.appendChild(template);
      }
      CodeMirror.addClass(wrap, "dialog-opened");
      return dialog2;
    }
    __name(dialogDiv, "dialogDiv");
    function closeNotification(cm, newVal) {
      if (cm.state.currentNotificationClose)
        cm.state.currentNotificationClose();
      cm.state.currentNotificationClose = newVal;
    }
    __name(closeNotification, "closeNotification");
    CodeMirror.defineExtension("openDialog", function(template, callback, options) {
      if (!options)
        options = {};
      closeNotification(this, null);
      var dialog2 = dialogDiv(this, template, options.bottom);
      var closed = false, me = this;
      function close(newVal) {
        if (typeof newVal == "string") {
          inp.value = newVal;
        } else {
          if (closed)
            return;
          closed = true;
          CodeMirror.rmClass(dialog2.parentNode, "dialog-opened");
          dialog2.parentNode.removeChild(dialog2);
          me.focus();
          if (options.onClose)
            options.onClose(dialog2);
        }
      }
      __name(close, "close");
      var inp = dialog2.getElementsByTagName("input")[0], button;
      if (inp) {
        inp.focus();
        if (options.value) {
          inp.value = options.value;
          if (options.selectValueOnOpen !== false) {
            inp.select();
          }
        }
        if (options.onInput)
          CodeMirror.on(inp, "input", function(e) {
            options.onInput(e, inp.value, close);
          });
        if (options.onKeyUp)
          CodeMirror.on(inp, "keyup", function(e) {
            options.onKeyUp(e, inp.value, close);
          });
        CodeMirror.on(inp, "keydown", function(e) {
          if (options && options.onKeyDown && options.onKeyDown(e, inp.value, close)) {
            return;
          }
          if (e.keyCode == 27 || options.closeOnEnter !== false && e.keyCode == 13) {
            inp.blur();
            CodeMirror.e_stop(e);
            close();
          }
          if (e.keyCode == 13)
            callback(inp.value, e);
        });
        if (options.closeOnBlur !== false)
          CodeMirror.on(dialog2, "focusout", function(evt) {
            if (evt.relatedTarget !== null)
              close();
          });
      } else if (button = dialog2.getElementsByTagName("button")[0]) {
        CodeMirror.on(button, "click", function() {
          close();
          me.focus();
        });
        if (options.closeOnBlur !== false)
          CodeMirror.on(button, "blur", close);
        button.focus();
      }
      return close;
    });
    CodeMirror.defineExtension("openConfirm", function(template, callbacks, options) {
      closeNotification(this, null);
      var dialog2 = dialogDiv(this, template, options && options.bottom);
      var buttons = dialog2.getElementsByTagName("button");
      var closed = false, me = this, blurring = 1;
      function close() {
        if (closed)
          return;
        closed = true;
        CodeMirror.rmClass(dialog2.parentNode, "dialog-opened");
        dialog2.parentNode.removeChild(dialog2);
        me.focus();
      }
      __name(close, "close");
      buttons[0].focus();
      for (var i = 0; i < buttons.length; ++i) {
        var b = buttons[i];
        (function(callback) {
          CodeMirror.on(b, "click", function(e) {
            CodeMirror.e_preventDefault(e);
            close();
            if (callback)
              callback(me);
          });
        })(callbacks[i]);
        CodeMirror.on(b, "blur", function() {
          --blurring;
          setTimeout(function() {
            if (blurring <= 0)
              close();
          }, 200);
        });
        CodeMirror.on(b, "focus", function() {
          ++blurring;
        });
      }
    });
    CodeMirror.defineExtension("openNotification", function(template, options) {
      closeNotification(this, close);
      var dialog2 = dialogDiv(this, template, options && options.bottom);
      var closed = false, doneTimer;
      var duration = options && typeof options.duration !== "undefined" ? options.duration : 5e3;
      function close() {
        if (closed)
          return;
        closed = true;
        clearTimeout(doneTimer);
        CodeMirror.rmClass(dialog2.parentNode, "dialog-opened");
        dialog2.parentNode.removeChild(dialog2);
      }
      __name(close, "close");
      CodeMirror.on(dialog2, "click", function(e) {
        CodeMirror.e_preventDefault(e);
        close();
      });
      if (duration)
        doneTimer = setTimeout(close, duration);
      return close;
    });
  });
})();
var dialog = dialog$2.exports;
var dialog$1 = /* @__PURE__ */ Object.freeze(/* @__PURE__ */ _mergeNamespaces$1({
  __proto__: null,
  [Symbol.toStringTag]: "Module",
  "default": dialog
}, [dialog$2.exports]));
export {
  dialog$2 as a,
  dialog$1 as d
};
