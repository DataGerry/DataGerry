# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2026 becon GmbH
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
Reading an uploaded JSON text: decoding failures and nesting depth as two typed refusals

An upload is anyone's text. Decoding it can fail in more ways than `JSONDecodeError`: an extended-JSON hook raises its
own errors for a malformed `$oid`, `$uuid`, `$regex` or `$numberDecimal` (`JSON_UPLOAD_DECODE_ERRORS`). And a text
the decoder accepts can still be nested so deep that the code walking it afterwards - `copy.deepcopy`, a validator, a
staging insert - runs out of Python recursion and fails as a server error. `load_json_upload` answers both as typed
errors a route can refuse with 400, and bounds the depth right after decoding with `nesting_depth`, which walks with a
stack of its own - so measuring cannot run out of recursion itself - and stops as soon as one branch passes the limit.

`MAX_JSON_UPLOAD_DEPTH` is the default bound: MongoDB's documented nesting limit for a document. A transfer file is 9
levels deep, a type export a few less
"""
import json
import re
from typing import Any, Callable

from bson.errors import InvalidId

from cmdb.errors.utils import JsonUploadDecodeError, JsonUploadTooDeepError
# -------------------------------------------------------------------------------------------------------------------- #

# How deep an uploaded JSON value may be nested - MongoDB's documented nesting limit for a document
MAX_JSON_UPLOAD_DEPTH: int = 100

# What decoding an upload raises for a text that is not JSON or holds an unreadable extended-JSON value: ValueError
# (JSONDecodeError, UnicodeDecodeError, a bad $uuid / $date / base64), TypeError (a value of the wrong kind),
# ArithmeticError (a bad $numberDecimal), InvalidId (a bad $oid) and re.error (a $regex that does not compile)
JSON_UPLOAD_DECODE_ERRORS: tuple[type[Exception], ...] = (ValueError, TypeError, ArithmeticError, InvalidId, re.error)


def nesting_depth(value: Any, limit: int) -> int:
    """
    How deeply a decoded JSON value is nested, measured up to one past a limit

    A scalar is 0 deep, an empty or flat list / dict 1, each container inside it one more. Walked with a stack of its
    own, never recursively, and given up as soon as a container passes the limit

    Args:
        value (Any): The decoded value
        limit (int): The depth past which the walk stops

    Returns:
        int: The depth, or ``limit + 1`` when it is deeper than the limit
    """
    deepest: int = 0
    stack: list[tuple[Any, int]] = [(value, 1)]

    while stack:
        current, depth = stack.pop()

        if not isinstance(current, (dict, list)):
            continue

        if depth > limit:
            return limit + 1

        deepest = max(deepest, depth)
        children = current.values() if isinstance(current, dict) else current
        stack.extend((child, depth + 1) for child in children)

    return deepest


def load_json_upload(text: str | bytes,
                     object_hook: Callable[[dict[str, Any]], Any] | None = None,
                     max_depth: int = MAX_JSON_UPLOAD_DEPTH) -> Any:
    """
    Decodes an uploaded JSON text and bounds how deeply it is nested

    Args:
        text (str | bytes): The upload - bytes are decoded as UTF-8
        object_hook (Callable[[dict[str, Any]], Any] | None): The extended-JSON hook to decode with; None for none
        max_depth (int): The deepest nesting accepted. Defaults to MAX_JSON_UPLOAD_DEPTH

    Raises:
        JsonUploadDecodeError: When the text is not UTF-8 JSON or holds a value the hook cannot read - carrying the
            decoder's error
        JsonUploadTooDeepError: When it is nested deeper than ``max_depth``

    Returns:
        Any: The decoded value
    """
    try:
        decoded: Any = json.loads(text, object_hook=object_hook)
    except RecursionError as err:
        raise JsonUploadTooDeepError(err) from err
    except JSON_UPLOAD_DECODE_ERRORS as err:
        raise JsonUploadDecodeError(err) from err

    if nesting_depth(decoded, max_depth) > max_depth:
        raise JsonUploadTooDeepError(f"The upload is nested deeper than {max_depth} levels")

    return decoded
