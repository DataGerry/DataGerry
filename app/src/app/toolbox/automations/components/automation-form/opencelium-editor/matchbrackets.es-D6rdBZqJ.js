import { a as codemirror$1 } from "./codemirror.es-dDlEaI2D.js";
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
var matchbrackets$2 = { exports: {} };
(function(module, exports$1) {
  (function(mod) {
    mod(codemirror$1.exports);
  })(function(CodeMirror) {
    var ie_lt8 = /MSIE \d/.test(navigator.userAgent) && (document.documentMode == null || document.documentMode < 8);
    var Pos = CodeMirror.Pos;
    var matching = { "(": ")>", ")": "(<", "[": "]>", "]": "[<", "{": "}>", "}": "{<", "<": ">>", ">": "<<" };
    function bracketRegex(config) {
      return config && config.bracketRegex || /[(){}[\]]/;
    }
    __name(bracketRegex, "bracketRegex");
    function findMatchingBracket(cm, where, config) {
      var line = cm.getLineHandle(where.line), pos = where.ch - 1;
      var afterCursor = config && config.afterCursor;
      if (afterCursor == null)
        afterCursor = /(^| )cm-fat-cursor($| )/.test(cm.getWrapperElement().className);
      var re = bracketRegex(config);
      var match = !afterCursor && pos >= 0 && re.test(line.text.charAt(pos)) && matching[line.text.charAt(pos)] || re.test(line.text.charAt(pos + 1)) && matching[line.text.charAt(++pos)];
      if (!match)
        return null;
      var dir = match.charAt(1) == ">" ? 1 : -1;
      if (config && config.strict && dir > 0 != (pos == where.ch))
        return null;
      var style = cm.getTokenTypeAt(Pos(where.line, pos + 1));
      var found = scanForBracket(cm, Pos(where.line, pos + (dir > 0 ? 1 : 0)), dir, style, config);
      if (found == null)
        return null;
      return {
        from: Pos(where.line, pos),
        to: found && found.pos,
        match: found && found.ch == match.charAt(0),
        forward: dir > 0
      };
    }
    __name(findMatchingBracket, "findMatchingBracket");
    function scanForBracket(cm, where, dir, style, config) {
      var maxScanLen = config && config.maxScanLineLength || 1e4;
      var maxScanLines = config && config.maxScanLines || 1e3;
      var stack = [];
      var re = bracketRegex(config);
      var lineEnd = dir > 0 ? Math.min(where.line + maxScanLines, cm.lastLine() + 1) : Math.max(cm.firstLine() - 1, where.line - maxScanLines);
      for (var lineNo = where.line; lineNo != lineEnd; lineNo += dir) {
        var line = cm.getLine(lineNo);
        if (!line)
          continue;
        var pos = dir > 0 ? 0 : line.length - 1, end = dir > 0 ? line.length : -1;
        if (line.length > maxScanLen)
          continue;
        if (lineNo == where.line)
          pos = where.ch - (dir < 0 ? 1 : 0);
        for (; pos != end; pos += dir) {
          var ch = line.charAt(pos);
          if (re.test(ch) && (style === void 0 || (cm.getTokenTypeAt(Pos(lineNo, pos + 1)) || "") == (style || ""))) {
            var match = matching[ch];
            if (match && match.charAt(1) == ">" == dir > 0)
              stack.push(ch);
            else if (!stack.length)
              return { pos: Pos(lineNo, pos), ch };
            else
              stack.pop();
          }
        }
      }
      return lineNo - dir == (dir > 0 ? cm.lastLine() : cm.firstLine()) ? false : null;
    }
    __name(scanForBracket, "scanForBracket");
    function matchBrackets(cm, autoclear, config) {
      var maxHighlightLen = cm.state.matchBrackets.maxHighlightLineLength || 1e3, highlightNonMatching = config && config.highlightNonMatching;
      var marks = [], ranges = cm.listSelections();
      for (var i = 0; i < ranges.length; i++) {
        var match = ranges[i].empty() && findMatchingBracket(cm, ranges[i].head, config);
        if (match && (match.match || highlightNonMatching !== false) && cm.getLine(match.from.line).length <= maxHighlightLen) {
          var style = match.match ? "CodeMirror-matchingbracket" : "CodeMirror-nonmatchingbracket";
          marks.push(cm.markText(match.from, Pos(match.from.line, match.from.ch + 1), { className: style }));
          if (match.to && cm.getLine(match.to.line).length <= maxHighlightLen)
            marks.push(cm.markText(match.to, Pos(match.to.line, match.to.ch + 1), { className: style }));
        }
      }
      if (marks.length) {
        if (ie_lt8 && cm.state.focused)
          cm.focus();
        var clear = /* @__PURE__ */ __name(function() {
          cm.operation(function() {
            for (var i2 = 0; i2 < marks.length; i2++)
              marks[i2].clear();
          });
        }, "clear");
        if (autoclear)
          setTimeout(clear, 800);
        else
          return clear;
      }
    }
    __name(matchBrackets, "matchBrackets");
    function doMatchBrackets(cm) {
      cm.operation(function() {
        if (cm.state.matchBrackets.currentlyHighlighted) {
          cm.state.matchBrackets.currentlyHighlighted();
          cm.state.matchBrackets.currentlyHighlighted = null;
        }
        cm.state.matchBrackets.currentlyHighlighted = matchBrackets(cm, false, cm.state.matchBrackets);
      });
    }
    __name(doMatchBrackets, "doMatchBrackets");
    function clearHighlighted(cm) {
      if (cm.state.matchBrackets && cm.state.matchBrackets.currentlyHighlighted) {
        cm.state.matchBrackets.currentlyHighlighted();
        cm.state.matchBrackets.currentlyHighlighted = null;
      }
    }
    __name(clearHighlighted, "clearHighlighted");
    CodeMirror.defineOption("matchBrackets", false, function(cm, val, old) {
      if (old && old != CodeMirror.Init) {
        cm.off("cursorActivity", doMatchBrackets);
        cm.off("focus", doMatchBrackets);
        cm.off("blur", clearHighlighted);
        clearHighlighted(cm);
      }
      if (val) {
        cm.state.matchBrackets = typeof val == "object" ? val : {};
        cm.on("cursorActivity", doMatchBrackets);
        cm.on("focus", doMatchBrackets);
        cm.on("blur", clearHighlighted);
      }
    });
    CodeMirror.defineExtension("matchBrackets", function() {
      matchBrackets(this, true);
    });
    CodeMirror.defineExtension("findMatchingBracket", function(pos, config, oldConfig) {
      if (oldConfig || typeof config == "boolean") {
        if (!oldConfig) {
          config = config ? { strict: true } : null;
        } else {
          oldConfig.strict = config;
          config = oldConfig;
        }
      }
      return findMatchingBracket(this, pos, config);
    });
    CodeMirror.defineExtension("scanForBracket", function(pos, dir, style, config) {
      return scanForBracket(this, pos, dir, style, config);
    });
  });
})();
var matchbrackets = matchbrackets$2.exports;
var matchbrackets$1 = /* @__PURE__ */ Object.freeze(/* @__PURE__ */ _mergeNamespaces$1({
  __proto__: null,
  [Symbol.toStringTag]: "Module",
  "default": matchbrackets
}, [matchbrackets$2.exports]));
export {
  matchbrackets$2 as a,
  matchbrackets$1 as m
};
