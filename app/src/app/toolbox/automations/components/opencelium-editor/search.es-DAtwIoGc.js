import { a as codemirror$1 } from "./codemirror.es-fs4QEe8g.js";
import { a as searchcursor$2 } from "./searchcursor.es-DJrpcW8N.js";
import { a as dialog$2 } from "./dialog.es-CaQPqZek.js";
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
var search$2 = { exports: {} };
(function(module, exports$1) {
  (function(mod) {
    mod(codemirror$1.exports, searchcursor$2.exports, dialog$2.exports);
  })(function(CodeMirror) {
    CodeMirror.defineOption("search", { bottom: false });
    function searchOverlay(query, caseInsensitive) {
      if (typeof query == "string")
        query = new RegExp(query.replace(/[\-\[\]\/\{\}\(\)\*\+\?\.\\\^\$\|]/g, "\\$&"), caseInsensitive ? "gi" : "g");
      else if (!query.global)
        query = new RegExp(query.source, query.ignoreCase ? "gi" : "g");
      return { token: function(stream) {
        query.lastIndex = stream.pos;
        var match = query.exec(stream.string);
        if (match && match.index == stream.pos) {
          stream.pos += match[0].length || 1;
          return "searching";
        } else if (match) {
          stream.pos = match.index;
        } else {
          stream.skipToEnd();
        }
      } };
    }
    __name(searchOverlay, "searchOverlay");
    function SearchState() {
      this.posFrom = this.posTo = this.lastQuery = this.query = null;
      this.overlay = null;
    }
    __name(SearchState, "SearchState");
    function getSearchState(cm) {
      return cm.state.search || (cm.state.search = new SearchState());
    }
    __name(getSearchState, "getSearchState");
    function queryCaseInsensitive(query) {
      return typeof query == "string" && query == query.toLowerCase();
    }
    __name(queryCaseInsensitive, "queryCaseInsensitive");
    function getSearchCursor(cm, query, pos) {
      return cm.getSearchCursor(query, pos, { caseFold: queryCaseInsensitive(query), multiline: true });
    }
    __name(getSearchCursor, "getSearchCursor");
    function persistentDialog(cm, text, deflt, onEnter, onKeyDown) {
      cm.openDialog(text, onEnter, {
        value: deflt,
        selectValueOnOpen: true,
        closeOnEnter: false,
        onClose: function() {
          clearSearch(cm);
        },
        onKeyDown,
        bottom: cm.options.search.bottom
      });
    }
    __name(persistentDialog, "persistentDialog");
    function dialog2(cm, text, shortText, deflt, f) {
      if (cm.openDialog)
        cm.openDialog(text, f, { value: deflt, selectValueOnOpen: true, bottom: cm.options.search.bottom });
      else
        f(prompt(shortText, deflt));
    }
    __name(dialog2, "dialog");
    function confirmDialog(cm, text, shortText, fs) {
      if (cm.openConfirm)
        cm.openConfirm(text, fs);
      else if (confirm(shortText))
        fs[0]();
    }
    __name(confirmDialog, "confirmDialog");
    function parseString(string) {
      return string.replace(/\\([nrt\\])/g, function(match, ch) {
        if (ch == "n")
          return "\n";
        if (ch == "r")
          return "\r";
        if (ch == "t")
          return "	";
        if (ch == "\\")
          return "\\";
        return match;
      });
    }
    __name(parseString, "parseString");
    function parseQuery(query) {
      var isRE = query.match(/^\/(.*)\/([a-z]*)$/);
      if (isRE) {
        try {
          query = new RegExp(isRE[1], isRE[2].indexOf("i") == -1 ? "" : "i");
        } catch (e) {
        }
      } else {
        query = parseString(query);
      }
      if (typeof query == "string" ? query == "" : query.test(""))
        query = /x^/;
      return query;
    }
    __name(parseQuery, "parseQuery");
    function startSearch(cm, state, query) {
      state.queryText = query;
      state.query = parseQuery(query);
      cm.removeOverlay(state.overlay, queryCaseInsensitive(state.query));
      state.overlay = searchOverlay(state.query, queryCaseInsensitive(state.query));
      cm.addOverlay(state.overlay);
      if (cm.showMatchesOnScrollbar) {
        if (state.annotate) {
          state.annotate.clear();
          state.annotate = null;
        }
        state.annotate = cm.showMatchesOnScrollbar(state.query, queryCaseInsensitive(state.query));
      }
    }
    __name(startSearch, "startSearch");
    function doSearch(cm, rev, persistent, immediate) {
      var state = getSearchState(cm);
      if (state.query)
        return findNext(cm, rev);
      var q = cm.getSelection() || state.lastQuery;
      if (q instanceof RegExp && q.source == "x^")
        q = null;
      if (persistent && cm.openDialog) {
        var hiding = null;
        var searchNext = /* @__PURE__ */ __name(function(query, event) {
          CodeMirror.e_stop(event);
          if (!query)
            return;
          if (query != state.queryText) {
            startSearch(cm, state, query);
            state.posFrom = state.posTo = cm.getCursor();
          }
          if (hiding)
            hiding.style.opacity = 1;
          findNext(cm, event.shiftKey, function(_, to) {
            var dialog3;
            if (to.line < 3 && document.querySelector && (dialog3 = cm.display.wrapper.querySelector(".CodeMirror-dialog")) && dialog3.getBoundingClientRect().bottom - 4 > cm.cursorCoords(to, "window").top)
              (hiding = dialog3).style.opacity = 0.4;
          });
        }, "searchNext");
        persistentDialog(cm, getQueryDialog(cm), q, searchNext, function(event, query) {
          var keyName = CodeMirror.keyName(event);
          var extra = cm.getOption("extraKeys"), cmd = extra && extra[keyName] || CodeMirror.keyMap[cm.getOption("keyMap")][keyName];
          if (cmd == "findNext" || cmd == "findPrev" || cmd == "findPersistentNext" || cmd == "findPersistentPrev") {
            CodeMirror.e_stop(event);
            startSearch(cm, getSearchState(cm), query);
            cm.execCommand(cmd);
          } else if (cmd == "find" || cmd == "findPersistent") {
            CodeMirror.e_stop(event);
            searchNext(query, event);
          }
        });
        if (immediate && q) {
          startSearch(cm, state, q);
          findNext(cm, rev);
        }
      } else {
        dialog2(cm, getQueryDialog(cm), "Search for:", q, function(query) {
          if (query && !state.query)
            cm.operation(function() {
              startSearch(cm, state, query);
              state.posFrom = state.posTo = cm.getCursor();
              findNext(cm, rev);
            });
        });
      }
    }
    __name(doSearch, "doSearch");
    function findNext(cm, rev, callback) {
      cm.operation(function() {
        var state = getSearchState(cm);
        var cursor = getSearchCursor(cm, state.query, rev ? state.posFrom : state.posTo);
        if (!cursor.find(rev)) {
          cursor = getSearchCursor(cm, state.query, rev ? CodeMirror.Pos(cm.lastLine()) : CodeMirror.Pos(cm.firstLine(), 0));
          if (!cursor.find(rev))
            return;
        }
        cm.setSelection(cursor.from(), cursor.to());
        cm.scrollIntoView({ from: cursor.from(), to: cursor.to() }, 20);
        state.posFrom = cursor.from();
        state.posTo = cursor.to();
        if (callback)
          callback(cursor.from(), cursor.to());
      });
    }
    __name(findNext, "findNext");
    function clearSearch(cm) {
      cm.operation(function() {
        var state = getSearchState(cm);
        state.lastQuery = state.query;
        if (!state.query)
          return;
        state.query = state.queryText = null;
        cm.removeOverlay(state.overlay);
        if (state.annotate) {
          state.annotate.clear();
          state.annotate = null;
        }
      });
    }
    __name(clearSearch, "clearSearch");
    function el(tag, attrs) {
      var element = tag ? document.createElement(tag) : document.createDocumentFragment();
      for (var key in attrs) {
        element[key] = attrs[key];
      }
      for (var i = 2; i < arguments.length; i++) {
        var child = arguments[i];
        element.appendChild(typeof child == "string" ? document.createTextNode(child) : child);
      }
      return element;
    }
    __name(el, "el");
    function getQueryDialog(cm) {
      return el("", null, el("span", { className: "CodeMirror-search-label" }, cm.phrase("Search:")), " ", el("input", { type: "text", "style": "width: 10em", className: "CodeMirror-search-field" }), " ", el("span", { style: "color: #888", className: "CodeMirror-search-hint" }, cm.phrase("(Use /re/ syntax for regexp search)")));
    }
    __name(getQueryDialog, "getQueryDialog");
    function getReplaceQueryDialog(cm) {
      return el("", null, " ", el("input", { type: "text", "style": "width: 10em", className: "CodeMirror-search-field" }), " ", el("span", { style: "color: #888", className: "CodeMirror-search-hint" }, cm.phrase("(Use /re/ syntax for regexp search)")));
    }
    __name(getReplaceQueryDialog, "getReplaceQueryDialog");
    function getReplacementQueryDialog(cm) {
      return el("", null, el("span", { className: "CodeMirror-search-label" }, cm.phrase("With:")), " ", el("input", { type: "text", "style": "width: 10em", className: "CodeMirror-search-field" }));
    }
    __name(getReplacementQueryDialog, "getReplacementQueryDialog");
    function getDoReplaceConfirm(cm) {
      return el("", null, el("span", { className: "CodeMirror-search-label" }, cm.phrase("Replace?")), " ", el("button", {}, cm.phrase("Yes")), " ", el("button", {}, cm.phrase("No")), " ", el("button", {}, cm.phrase("All")), " ", el("button", {}, cm.phrase("Stop")));
    }
    __name(getDoReplaceConfirm, "getDoReplaceConfirm");
    function replaceAll(cm, query, text) {
      cm.operation(function() {
        for (var cursor = getSearchCursor(cm, query); cursor.findNext(); ) {
          if (typeof query != "string") {
            var match = cm.getRange(cursor.from(), cursor.to()).match(query);
            cursor.replace(text.replace(/\$(\d)/g, function(_, i) {
              return match[i];
            }));
          } else
            cursor.replace(text);
        }
      });
    }
    __name(replaceAll, "replaceAll");
    function replace(cm, all) {
      if (cm.getOption("readOnly"))
        return;
      var query = cm.getSelection() || getSearchState(cm).lastQuery;
      var dialogText = all ? cm.phrase("Replace all:") : cm.phrase("Replace:");
      var fragment = el("", null, el("span", { className: "CodeMirror-search-label" }, dialogText), getReplaceQueryDialog(cm));
      dialog2(cm, fragment, dialogText, query, function(query2) {
        if (!query2)
          return;
        query2 = parseQuery(query2);
        dialog2(cm, getReplacementQueryDialog(cm), cm.phrase("Replace with:"), "", function(text) {
          text = parseString(text);
          if (all) {
            replaceAll(cm, query2, text);
          } else {
            clearSearch(cm);
            var cursor = getSearchCursor(cm, query2, cm.getCursor("from"));
            var advance = /* @__PURE__ */ __name(function() {
              var start = cursor.from(), match;
              if (!(match = cursor.findNext())) {
                cursor = getSearchCursor(cm, query2);
                if (!(match = cursor.findNext()) || start && cursor.from().line == start.line && cursor.from().ch == start.ch)
                  return;
              }
              cm.setSelection(cursor.from(), cursor.to());
              cm.scrollIntoView({ from: cursor.from(), to: cursor.to() });
              confirmDialog(cm, getDoReplaceConfirm(cm), cm.phrase("Replace?"), [
                function() {
                  doReplace(match);
                },
                advance,
                function() {
                  replaceAll(cm, query2, text);
                }
              ]);
            }, "advance");
            var doReplace = /* @__PURE__ */ __name(function(match) {
              cursor.replace(typeof query2 == "string" ? text : text.replace(/\$(\d)/g, function(_, i) {
                return match[i];
              }));
              advance();
            }, "doReplace");
            advance();
          }
        });
      });
    }
    __name(replace, "replace");
    CodeMirror.commands.find = function(cm) {
      clearSearch(cm);
      doSearch(cm);
    };
    CodeMirror.commands.findPersistent = function(cm) {
      clearSearch(cm);
      doSearch(cm, false, true);
    };
    CodeMirror.commands.findPersistentNext = function(cm) {
      doSearch(cm, false, true, true);
    };
    CodeMirror.commands.findPersistentPrev = function(cm) {
      doSearch(cm, true, true, true);
    };
    CodeMirror.commands.findNext = doSearch;
    CodeMirror.commands.findPrev = function(cm) {
      doSearch(cm, true);
    };
    CodeMirror.commands.clearSearch = clearSearch;
    CodeMirror.commands.replace = replace;
    CodeMirror.commands.replaceAll = function(cm) {
      replace(cm, true);
    };
  });
})();
var search = search$2.exports;
var search$1 = /* @__PURE__ */ Object.freeze(/* @__PURE__ */ _mergeNamespaces$1({
  __proto__: null,
  [Symbol.toStringTag]: "Module",
  "default": search
}, [search$2.exports]));
export {
  search$1 as s
};
