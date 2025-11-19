import { a as codemirror$1 } from "./codemirror.es-DeWroV-8.js";
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
var closebrackets$2 = { exports: {} };
(function(module, exports$1) {
  (function(mod) {
    mod(codemirror$1.exports);
  })(function(CodeMirror) {
    var defaults = {
      pairs: `()[]{}''""`,
      closeBefore: `)]}'":;>`,
      triples: "",
      explode: "[]{}"
    };
    var Pos = CodeMirror.Pos;
    CodeMirror.defineOption("autoCloseBrackets", false, function(cm, val, old) {
      if (old && old != CodeMirror.Init) {
        cm.removeKeyMap(keyMap);
        cm.state.closeBrackets = null;
      }
      if (val) {
        ensureBound(getOption(val, "pairs"));
        cm.state.closeBrackets = val;
        cm.addKeyMap(keyMap);
      }
    });
    function getOption(conf, name) {
      if (name == "pairs" && typeof conf == "string")
        return conf;
      if (typeof conf == "object" && conf[name] != null)
        return conf[name];
      return defaults[name];
    }
    __name(getOption, "getOption");
    var keyMap = { Backspace: handleBackspace, Enter: handleEnter };
    function ensureBound(chars) {
      for (var i = 0; i < chars.length; i++) {
        var ch = chars.charAt(i), key = "'" + ch + "'";
        if (!keyMap[key])
          keyMap[key] = handler(ch);
      }
    }
    __name(ensureBound, "ensureBound");
    ensureBound(defaults.pairs + "`");
    function handler(ch) {
      return function(cm) {
        return handleChar(cm, ch);
      };
    }
    __name(handler, "handler");
    function getConfig(cm) {
      var deflt = cm.state.closeBrackets;
      if (!deflt || deflt.override)
        return deflt;
      var mode = cm.getModeAt(cm.getCursor());
      return mode.closeBrackets || deflt;
    }
    __name(getConfig, "getConfig");
    function handleBackspace(cm) {
      var conf = getConfig(cm);
      if (!conf || cm.getOption("disableInput"))
        return CodeMirror.Pass;
      var pairs = getOption(conf, "pairs");
      var ranges = cm.listSelections();
      for (var i = 0; i < ranges.length; i++) {
        if (!ranges[i].empty())
          return CodeMirror.Pass;
        var around = charsAround(cm, ranges[i].head);
        if (!around || pairs.indexOf(around) % 2 != 0)
          return CodeMirror.Pass;
      }
      for (var i = ranges.length - 1; i >= 0; i--) {
        var cur = ranges[i].head;
        cm.replaceRange("", Pos(cur.line, cur.ch - 1), Pos(cur.line, cur.ch + 1), "+delete");
      }
    }
    __name(handleBackspace, "handleBackspace");
    function handleEnter(cm) {
      var conf = getConfig(cm);
      var explode = conf && getOption(conf, "explode");
      if (!explode || cm.getOption("disableInput"))
        return CodeMirror.Pass;
      var ranges = cm.listSelections();
      for (var i = 0; i < ranges.length; i++) {
        if (!ranges[i].empty())
          return CodeMirror.Pass;
        var around = charsAround(cm, ranges[i].head);
        if (!around || explode.indexOf(around) % 2 != 0)
          return CodeMirror.Pass;
      }
      cm.operation(function() {
        var linesep = cm.lineSeparator() || "\n";
        cm.replaceSelection(linesep + linesep, null);
        moveSel(cm, -1);
        ranges = cm.listSelections();
        for (var i2 = 0; i2 < ranges.length; i2++) {
          var line = ranges[i2].head.line;
          cm.indentLine(line, null, true);
          cm.indentLine(line + 1, null, true);
        }
      });
    }
    __name(handleEnter, "handleEnter");
    function moveSel(cm, dir) {
      var newRanges = [], ranges = cm.listSelections(), primary = 0;
      for (var i = 0; i < ranges.length; i++) {
        var range = ranges[i];
        if (range.head == cm.getCursor())
          primary = i;
        var pos = range.head.ch || dir > 0 ? { line: range.head.line, ch: range.head.ch + dir } : { line: range.head.line - 1 };
        newRanges.push({ anchor: pos, head: pos });
      }
      cm.setSelections(newRanges, primary);
    }
    __name(moveSel, "moveSel");
    function contractSelection(sel) {
      var inverted = CodeMirror.cmpPos(sel.anchor, sel.head) > 0;
      return {
        anchor: new Pos(sel.anchor.line, sel.anchor.ch + (inverted ? -1 : 1)),
        head: new Pos(sel.head.line, sel.head.ch + (inverted ? 1 : -1))
      };
    }
    __name(contractSelection, "contractSelection");
    function handleChar(cm, ch) {
      var conf = getConfig(cm);
      if (!conf || cm.getOption("disableInput"))
        return CodeMirror.Pass;
      var pairs = getOption(conf, "pairs");
      var pos = pairs.indexOf(ch);
      if (pos == -1)
        return CodeMirror.Pass;
      var closeBefore = getOption(conf, "closeBefore");
      var triples = getOption(conf, "triples");
      var identical = pairs.charAt(pos + 1) == ch;
      var ranges = cm.listSelections();
      var opening = pos % 2 == 0;
      var type;
      for (var i = 0; i < ranges.length; i++) {
        var range = ranges[i], cur = range.head, curType;
        var next = cm.getRange(cur, Pos(cur.line, cur.ch + 1));
        if (opening && !range.empty()) {
          curType = "surround";
        } else if ((identical || !opening) && next == ch) {
          if (identical && stringStartsAfter(cm, cur))
            curType = "both";
          else if (triples.indexOf(ch) >= 0 && cm.getRange(cur, Pos(cur.line, cur.ch + 3)) == ch + ch + ch)
            curType = "skipThree";
          else
            curType = "skip";
        } else if (identical && cur.ch > 1 && triples.indexOf(ch) >= 0 && cm.getRange(Pos(cur.line, cur.ch - 2), cur) == ch + ch) {
          if (cur.ch > 2 && /\bstring/.test(cm.getTokenTypeAt(Pos(cur.line, cur.ch - 2))))
            return CodeMirror.Pass;
          curType = "addFour";
        } else if (identical) {
          var prev = cur.ch == 0 ? " " : cm.getRange(Pos(cur.line, cur.ch - 1), cur);
          if (!CodeMirror.isWordChar(next) && prev != ch && !CodeMirror.isWordChar(prev))
            curType = "both";
          else
            return CodeMirror.Pass;
        } else if (opening && (next.length === 0 || /\s/.test(next) || closeBefore.indexOf(next) > -1)) {
          curType = "both";
        } else {
          return CodeMirror.Pass;
        }
        if (!type)
          type = curType;
        else if (type != curType)
          return CodeMirror.Pass;
      }
      var left = pos % 2 ? pairs.charAt(pos - 1) : ch;
      var right = pos % 2 ? ch : pairs.charAt(pos + 1);
      cm.operation(function() {
        if (type == "skip") {
          moveSel(cm, 1);
        } else if (type == "skipThree") {
          moveSel(cm, 3);
        } else if (type == "surround") {
          var sels = cm.getSelections();
          for (var i2 = 0; i2 < sels.length; i2++)
            sels[i2] = left + sels[i2] + right;
          cm.replaceSelections(sels, "around");
          sels = cm.listSelections().slice();
          for (var i2 = 0; i2 < sels.length; i2++)
            sels[i2] = contractSelection(sels[i2]);
          cm.setSelections(sels);
        } else if (type == "both") {
          cm.replaceSelection(left + right, null);
          cm.triggerElectric(left + right);
          moveSel(cm, -1);
        } else if (type == "addFour") {
          cm.replaceSelection(left + left + left + left, "before");
          moveSel(cm, 1);
        }
      });
    }
    __name(handleChar, "handleChar");
    function charsAround(cm, pos) {
      var str = cm.getRange(Pos(pos.line, pos.ch - 1), Pos(pos.line, pos.ch + 1));
      return str.length == 2 ? str : null;
    }
    __name(charsAround, "charsAround");
    function stringStartsAfter(cm, pos) {
      var token = cm.getTokenAt(Pos(pos.line, pos.ch + 1));
      return /\bstring/.test(token.type) && token.start == pos.ch && (pos.ch == 0 || !/\bstring/.test(cm.getTokenTypeAt(pos)));
    }
    __name(stringStartsAfter, "stringStartsAfter");
  });
})();
var closebrackets = closebrackets$2.exports;
var closebrackets$1 = /* @__PURE__ */ Object.freeze(/* @__PURE__ */ _mergeNamespaces$1({
  __proto__: null,
  [Symbol.toStringTag]: "Module",
  "default": closebrackets
}, [closebrackets$2.exports]));
export {
  closebrackets$1 as c
};
