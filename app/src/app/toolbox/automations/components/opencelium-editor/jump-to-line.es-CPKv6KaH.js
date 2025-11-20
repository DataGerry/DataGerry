import { a as codemirror$1 } from "./codemirror.es-BPA5EyRh.js";
import { a as dialog$2 } from "./dialog.es-Tt14TTcK.js";
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
var jumpToLine$2 = { exports: {} };
(function(module, exports$1) {
  (function(mod) {
    mod(codemirror$1.exports, dialog$2.exports);
  })(function(CodeMirror) {
    CodeMirror.defineOption("search", { bottom: false });
    function dialog2(cm, text, shortText, deflt, f) {
      if (cm.openDialog)
        cm.openDialog(text, f, { value: deflt, selectValueOnOpen: true, bottom: cm.options.search.bottom });
      else
        f(prompt(shortText, deflt));
    }
    __name(dialog2, "dialog");
    function getJumpDialog(cm) {
      return cm.phrase("Jump to line:") + ' <input type="text" style="width: 10em" class="CodeMirror-search-field"/> <span style="color: #888" class="CodeMirror-search-hint">' + cm.phrase("(Use line:column or scroll% syntax)") + "</span>";
    }
    __name(getJumpDialog, "getJumpDialog");
    function interpretLine(cm, string) {
      var num = Number(string);
      if (/^[-+]/.test(string))
        return cm.getCursor().line + num;
      else
        return num - 1;
    }
    __name(interpretLine, "interpretLine");
    CodeMirror.commands.jumpToLine = function(cm) {
      var cur = cm.getCursor();
      dialog2(cm, getJumpDialog(cm), cm.phrase("Jump to line:"), cur.line + 1 + ":" + cur.ch, function(posStr) {
        if (!posStr)
          return;
        var match;
        if (match = /^\s*([\+\-]?\d+)\s*\:\s*(\d+)\s*$/.exec(posStr)) {
          cm.setCursor(interpretLine(cm, match[1]), Number(match[2]));
        } else if (match = /^\s*([\+\-]?\d+(\.\d+)?)\%\s*/.exec(posStr)) {
          var line = Math.round(cm.lineCount() * Number(match[1]) / 100);
          if (/^[-+]/.test(match[1]))
            line = cur.line + line + 1;
          cm.setCursor(line - 1, cur.ch);
        } else if (match = /^\s*\:?\s*([\+\-]?\d+)\s*/.exec(posStr)) {
          cm.setCursor(interpretLine(cm, match[1]), cur.ch);
        }
      });
    };
    CodeMirror.keyMap["default"]["Alt-G"] = "jumpToLine";
  });
})();
var jumpToLine = jumpToLine$2.exports;
var jumpToLine$1 = /* @__PURE__ */ Object.freeze(/* @__PURE__ */ _mergeNamespaces$1({
  __proto__: null,
  [Symbol.toStringTag]: "Module",
  "default": jumpToLine
}, [jumpToLine$2.exports]));
export {
  jumpToLine$1 as j
};
