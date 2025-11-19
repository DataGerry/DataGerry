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
var foldgutter$2 = { exports: {} };
var foldcode = { exports: {} };
(function(module, exports$1) {
  (function(mod) {
    mod(codemirror$1.exports);
  })(function(CodeMirror) {
    function doFold(cm, pos, options, force) {
      if (options && options.call) {
        var finder = options;
        options = null;
      } else {
        var finder = getOption(cm, options, "rangeFinder");
      }
      if (typeof pos == "number")
        pos = CodeMirror.Pos(pos, 0);
      var minSize = getOption(cm, options, "minFoldSize");
      function getRange(allowFolded) {
        var range2 = finder(cm, pos);
        if (!range2 || range2.to.line - range2.from.line < minSize)
          return null;
        if (force === "fold")
          return range2;
        var marks = cm.findMarksAt(range2.from);
        for (var i = 0; i < marks.length; ++i) {
          if (marks[i].__isFold) {
            if (!allowFolded)
              return null;
            range2.cleared = true;
            marks[i].clear();
          }
        }
        return range2;
      }
      __name(getRange, "getRange");
      var range = getRange(true);
      if (getOption(cm, options, "scanUp"))
        while (!range && pos.line > cm.firstLine()) {
          pos = CodeMirror.Pos(pos.line - 1, 0);
          range = getRange(false);
        }
      if (!range || range.cleared || force === "unfold")
        return;
      var myWidget = makeWidget(cm, options, range);
      CodeMirror.on(myWidget, "mousedown", function(e) {
        myRange.clear();
        CodeMirror.e_preventDefault(e);
      });
      var myRange = cm.markText(range.from, range.to, {
        replacedWith: myWidget,
        clearOnEnter: getOption(cm, options, "clearOnEnter"),
        __isFold: true
      });
      myRange.on("clear", function(from, to) {
        CodeMirror.signal(cm, "unfold", cm, from, to);
      });
      CodeMirror.signal(cm, "fold", cm, range.from, range.to);
    }
    __name(doFold, "doFold");
    function makeWidget(cm, options, range) {
      var widget = getOption(cm, options, "widget");
      if (typeof widget == "function") {
        widget = widget(range.from, range.to);
      }
      if (typeof widget == "string") {
        var text = document.createTextNode(widget);
        widget = document.createElement("span");
        widget.appendChild(text);
        widget.className = "CodeMirror-foldmarker";
      } else if (widget) {
        widget = widget.cloneNode(true);
      }
      return widget;
    }
    __name(makeWidget, "makeWidget");
    CodeMirror.newFoldFunction = function(rangeFinder, widget) {
      return function(cm, pos) {
        doFold(cm, pos, { rangeFinder, widget });
      };
    };
    CodeMirror.defineExtension("foldCode", function(pos, options, force) {
      doFold(this, pos, options, force);
    });
    CodeMirror.defineExtension("isFolded", function(pos) {
      var marks = this.findMarksAt(pos);
      for (var i = 0; i < marks.length; ++i)
        if (marks[i].__isFold)
          return true;
    });
    CodeMirror.commands.toggleFold = function(cm) {
      cm.foldCode(cm.getCursor());
    };
    CodeMirror.commands.fold = function(cm) {
      cm.foldCode(cm.getCursor(), null, "fold");
    };
    CodeMirror.commands.unfold = function(cm) {
      cm.foldCode(cm.getCursor(), { scanUp: false }, "unfold");
    };
    CodeMirror.commands.foldAll = function(cm) {
      cm.operation(function() {
        for (var i = cm.firstLine(), e = cm.lastLine(); i <= e; i++)
          cm.foldCode(CodeMirror.Pos(i, 0), { scanUp: false }, "fold");
      });
    };
    CodeMirror.commands.unfoldAll = function(cm) {
      cm.operation(function() {
        for (var i = cm.firstLine(), e = cm.lastLine(); i <= e; i++)
          cm.foldCode(CodeMirror.Pos(i, 0), { scanUp: false }, "unfold");
      });
    };
    CodeMirror.registerHelper("fold", "combine", function() {
      var funcs = Array.prototype.slice.call(arguments, 0);
      return function(cm, start) {
        for (var i = 0; i < funcs.length; ++i) {
          var found = funcs[i](cm, start);
          if (found)
            return found;
        }
      };
    });
    CodeMirror.registerHelper("fold", "auto", function(cm, start) {
      var helpers = cm.getHelpers(start, "fold");
      for (var i = 0; i < helpers.length; i++) {
        var cur = helpers[i](cm, start);
        if (cur)
          return cur;
      }
    });
    var defaultOptions = {
      rangeFinder: CodeMirror.fold.auto,
      widget: "↔",
      minFoldSize: 0,
      scanUp: false,
      clearOnEnter: true
    };
    CodeMirror.defineOption("foldOptions", null);
    function getOption(cm, options, name) {
      if (options && options[name] !== void 0)
        return options[name];
      var editorOptions = cm.options.foldOptions;
      if (editorOptions && editorOptions[name] !== void 0)
        return editorOptions[name];
      return defaultOptions[name];
    }
    __name(getOption, "getOption");
    CodeMirror.defineExtension("foldOption", function(options, name) {
      return getOption(this, options, name);
    });
  });
})();
(function(module, exports$1) {
  (function(mod) {
    mod(codemirror$1.exports, foldcode.exports);
  })(function(CodeMirror) {
    CodeMirror.defineOption("foldGutter", false, function(cm, val, old) {
      if (old && old != CodeMirror.Init) {
        cm.clearGutter(cm.state.foldGutter.options.gutter);
        cm.state.foldGutter = null;
        cm.off("gutterClick", onGutterClick);
        cm.off("changes", onChange);
        cm.off("viewportChange", onViewportChange);
        cm.off("fold", onFold);
        cm.off("unfold", onFold);
        cm.off("swapDoc", onChange);
      }
      if (val) {
        cm.state.foldGutter = new State(parseOptions(val));
        updateInViewport(cm);
        cm.on("gutterClick", onGutterClick);
        cm.on("changes", onChange);
        cm.on("viewportChange", onViewportChange);
        cm.on("fold", onFold);
        cm.on("unfold", onFold);
        cm.on("swapDoc", onChange);
      }
    });
    var Pos = CodeMirror.Pos;
    function State(options) {
      this.options = options;
      this.from = this.to = 0;
    }
    __name(State, "State");
    function parseOptions(opts) {
      if (opts === true)
        opts = {};
      if (opts.gutter == null)
        opts.gutter = "CodeMirror-foldgutter";
      if (opts.indicatorOpen == null)
        opts.indicatorOpen = "CodeMirror-foldgutter-open";
      if (opts.indicatorFolded == null)
        opts.indicatorFolded = "CodeMirror-foldgutter-folded";
      return opts;
    }
    __name(parseOptions, "parseOptions");
    function isFolded(cm, line) {
      var marks = cm.findMarks(Pos(line, 0), Pos(line + 1, 0));
      for (var i = 0; i < marks.length; ++i) {
        if (marks[i].__isFold) {
          var fromPos = marks[i].find(-1);
          if (fromPos && fromPos.line === line)
            return marks[i];
        }
      }
    }
    __name(isFolded, "isFolded");
    function marker(spec) {
      if (typeof spec == "string") {
        var elt = document.createElement("div");
        elt.className = spec + " CodeMirror-guttermarker-subtle";
        return elt;
      } else {
        return spec.cloneNode(true);
      }
    }
    __name(marker, "marker");
    function updateFoldInfo(cm, from, to) {
      var opts = cm.state.foldGutter.options, cur = from - 1;
      var minSize = cm.foldOption(opts, "minFoldSize");
      var func = cm.foldOption(opts, "rangeFinder");
      var clsFolded = typeof opts.indicatorFolded == "string" && classTest(opts.indicatorFolded);
      var clsOpen = typeof opts.indicatorOpen == "string" && classTest(opts.indicatorOpen);
      cm.eachLine(from, to, function(line) {
        ++cur;
        var mark = null;
        var old = line.gutterMarkers;
        if (old)
          old = old[opts.gutter];
        if (isFolded(cm, cur)) {
          if (clsFolded && old && clsFolded.test(old.className))
            return;
          mark = marker(opts.indicatorFolded);
        } else {
          var pos = Pos(cur, 0);
          var range = func && func(cm, pos);
          if (range && range.to.line - range.from.line >= minSize) {
            if (clsOpen && old && clsOpen.test(old.className))
              return;
            mark = marker(opts.indicatorOpen);
          }
        }
        if (!mark && !old)
          return;
        cm.setGutterMarker(line, opts.gutter, mark);
      });
    }
    __name(updateFoldInfo, "updateFoldInfo");
    function classTest(cls) {
      return new RegExp("(^|\\s)" + cls + "(?:$|\\s)\\s*");
    }
    __name(classTest, "classTest");
    function updateInViewport(cm) {
      var vp = cm.getViewport(), state = cm.state.foldGutter;
      if (!state)
        return;
      cm.operation(function() {
        updateFoldInfo(cm, vp.from, vp.to);
      });
      state.from = vp.from;
      state.to = vp.to;
    }
    __name(updateInViewport, "updateInViewport");
    function onGutterClick(cm, line, gutter) {
      var state = cm.state.foldGutter;
      if (!state)
        return;
      var opts = state.options;
      if (gutter != opts.gutter)
        return;
      var folded = isFolded(cm, line);
      if (folded)
        folded.clear();
      else
        cm.foldCode(Pos(line, 0), opts);
    }
    __name(onGutterClick, "onGutterClick");
    function onChange(cm) {
      var state = cm.state.foldGutter;
      if (!state)
        return;
      var opts = state.options;
      state.from = state.to = 0;
      clearTimeout(state.changeUpdate);
      state.changeUpdate = setTimeout(function() {
        updateInViewport(cm);
      }, opts.foldOnChangeTimeSpan || 600);
    }
    __name(onChange, "onChange");
    function onViewportChange(cm) {
      var state = cm.state.foldGutter;
      if (!state)
        return;
      var opts = state.options;
      clearTimeout(state.changeUpdate);
      state.changeUpdate = setTimeout(function() {
        var vp = cm.getViewport();
        if (state.from == state.to || vp.from - state.to > 20 || state.from - vp.to > 20) {
          updateInViewport(cm);
        } else {
          cm.operation(function() {
            if (vp.from < state.from) {
              updateFoldInfo(cm, vp.from, state.from);
              state.from = vp.from;
            }
            if (vp.to > state.to) {
              updateFoldInfo(cm, state.to, vp.to);
              state.to = vp.to;
            }
          });
        }
      }, opts.updateViewportTimeSpan || 400);
    }
    __name(onViewportChange, "onViewportChange");
    function onFold(cm, from) {
      var state = cm.state.foldGutter;
      if (!state)
        return;
      var line = from.line;
      if (line >= state.from && line < state.to)
        updateFoldInfo(cm, line, line + 1);
    }
    __name(onFold, "onFold");
  });
})();
var foldgutter = foldgutter$2.exports;
var foldgutter$1 = /* @__PURE__ */ Object.freeze(/* @__PURE__ */ _mergeNamespaces$1({
  __proto__: null,
  [Symbol.toStringTag]: "Module",
  "default": foldgutter
}, [foldgutter$2.exports]));
export {
  foldgutter$1 as f
};
