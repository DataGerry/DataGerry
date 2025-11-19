import { a as codemirror$1 } from "./codemirror.es-DowDixU7.js";
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
var braceFold$2 = { exports: {} };
(function(module, exports$1) {
  (function(mod) {
    mod(codemirror$1.exports);
  })(function(CodeMirror) {
    function bracketFolding(pairs) {
      return function(cm, start) {
        var line = start.line, lineText = cm.getLine(line);
        function findOpening(pair) {
          var tokenType;
          for (var at = start.ch, pass = 0; ; ) {
            var found2 = at <= 0 ? -1 : lineText.lastIndexOf(pair[0], at - 1);
            if (found2 == -1) {
              if (pass == 1)
                break;
              pass = 1;
              at = lineText.length;
              continue;
            }
            if (pass == 1 && found2 < start.ch)
              break;
            tokenType = cm.getTokenTypeAt(CodeMirror.Pos(line, found2 + 1));
            if (!/^(comment|string)/.test(tokenType))
              return { ch: found2 + 1, tokenType, pair };
            at = found2 - 1;
          }
        }
        __name(findOpening, "findOpening");
        function findRange(found2) {
          var count = 1, lastLine = cm.lastLine(), end, startCh = found2.ch, endCh;
          outer:
            for (var i2 = line; i2 <= lastLine; ++i2) {
              var text = cm.getLine(i2), pos = i2 == line ? startCh : 0;
              for (; ; ) {
                var nextOpen = text.indexOf(found2.pair[0], pos), nextClose = text.indexOf(found2.pair[1], pos);
                if (nextOpen < 0)
                  nextOpen = text.length;
                if (nextClose < 0)
                  nextClose = text.length;
                pos = Math.min(nextOpen, nextClose);
                if (pos == text.length)
                  break;
                if (cm.getTokenTypeAt(CodeMirror.Pos(i2, pos + 1)) == found2.tokenType) {
                  if (pos == nextOpen)
                    ++count;
                  else if (!--count) {
                    end = i2;
                    endCh = pos;
                    break outer;
                  }
                }
                ++pos;
              }
            }
          if (end == null || line == end)
            return null;
          return {
            from: CodeMirror.Pos(line, startCh),
            to: CodeMirror.Pos(end, endCh)
          };
        }
        __name(findRange, "findRange");
        var found = [];
        for (var i = 0; i < pairs.length; i++) {
          var open = findOpening(pairs[i]);
          if (open)
            found.push(open);
        }
        found.sort(function(a, b) {
          return a.ch - b.ch;
        });
        for (var i = 0; i < found.length; i++) {
          var range = findRange(found[i]);
          if (range)
            return range;
        }
        return null;
      };
    }
    __name(bracketFolding, "bracketFolding");
    CodeMirror.registerHelper("fold", "brace", bracketFolding([["{", "}"], ["[", "]"]]));
    CodeMirror.registerHelper("fold", "brace-paren", bracketFolding([["{", "}"], ["[", "]"], ["(", ")"]]));
    CodeMirror.registerHelper("fold", "import", function(cm, start) {
      function hasImport(line) {
        if (line < cm.firstLine() || line > cm.lastLine())
          return null;
        var start2 = cm.getTokenAt(CodeMirror.Pos(line, 1));
        if (!/\S/.test(start2.string))
          start2 = cm.getTokenAt(CodeMirror.Pos(line, start2.end + 1));
        if (start2.type != "keyword" || start2.string != "import")
          return null;
        for (var i = line, e = Math.min(cm.lastLine(), line + 10); i <= e; ++i) {
          var text = cm.getLine(i), semi = text.indexOf(";");
          if (semi != -1)
            return { startCh: start2.end, end: CodeMirror.Pos(i, semi) };
        }
      }
      __name(hasImport, "hasImport");
      var startLine = start.line, has = hasImport(startLine), prev;
      if (!has || hasImport(startLine - 1) || (prev = hasImport(startLine - 2)) && prev.end.line == startLine - 1)
        return null;
      for (var end = has.end; ; ) {
        var next = hasImport(end.line + 1);
        if (next == null)
          break;
        end = next.end;
      }
      return { from: cm.clipPos(CodeMirror.Pos(startLine, has.startCh + 1)), to: end };
    });
    CodeMirror.registerHelper("fold", "include", function(cm, start) {
      function hasInclude(line) {
        if (line < cm.firstLine() || line > cm.lastLine())
          return null;
        var start2 = cm.getTokenAt(CodeMirror.Pos(line, 1));
        if (!/\S/.test(start2.string))
          start2 = cm.getTokenAt(CodeMirror.Pos(line, start2.end + 1));
        if (start2.type == "meta" && start2.string.slice(0, 8) == "#include")
          return start2.start + 8;
      }
      __name(hasInclude, "hasInclude");
      var startLine = start.line, has = hasInclude(startLine);
      if (has == null || hasInclude(startLine - 1) != null)
        return null;
      for (var end = startLine; ; ) {
        var next = hasInclude(end + 1);
        if (next == null)
          break;
        ++end;
      }
      return {
        from: CodeMirror.Pos(startLine, has + 1),
        to: cm.clipPos(CodeMirror.Pos(end))
      };
    });
  });
})();
var braceFold = braceFold$2.exports;
var braceFold$1 = /* @__PURE__ */ Object.freeze(/* @__PURE__ */ _mergeNamespaces$1({
  __proto__: null,
  [Symbol.toStringTag]: "Module",
  "default": braceFold
}, [braceFold$2.exports]));
export {
  braceFold$1 as b
};
