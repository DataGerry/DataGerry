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
Reading a CmdbReport's stored query back into a MongoDB query

A report's ``report_query.data`` is the ``repr`` of the query dict its conditions compile to -
``datetime.datetime(...)`` calls and all - and every reader of a report (the report run, the DocAPI
report table) turns it back into a dict HERE, so there is one reading of the stored shape.

**The string is evaluated with ``eval``**, in a namespace that exposes only ``datetime`` and has an
empty ``__builtins__``. That keeps builtin NAMES out of reach, but it is **not a sandbox**: an
expression can still walk from a literal's attributes to the interpreter's internals. It is safe only
because every writer builds the string on the server from the report's conditions - the write routes
refuse a client-supplied ``report_query`` - so no request can place an expression of its own there.
Anything that writes a report document another way inherits that risk, and that is why the evaluation
lives in exactly one function
"""
from datetime import datetime
from typing import Any

from cmdb.models.reports_model.report_constants import ReportQueryKey
# -------------------------------------------------------------------------------------------------------------------- #

__all__ = [
    'STORED_DATETIME_CALL',
    'eval_stored_report_query',
    'read_stored_report_query',
]

#: How a datetime value is spelled in the stored repr; rewritten to the bare name the namespace binds
STORED_DATETIME_CALL: str = 'datetime.datetime'

# Only 'datetime' is in scope and builtins are removed - see the module docstring for what that does
# and does not protect against
_EVAL_GLOBALS: dict[str, Any] = {'datetime': datetime, '__builtins__': {}}

# The CmdbReport key the stored query lives under
_REPORT_QUERY_KEY: str = 'report_query'


def eval_stored_report_query(query_str: str) -> dict[str, Any]:
    """
    Evaluates a stored report query string back into the Mongo query dict it was built from

    Args:
        query_str (str): The stored ``report_query.data`` string

    Raises:
        Exception: Whatever the evaluation raises for a string that is not a stored query - the
            callers decide what a corrupted report answers

    Returns:
        dict[str, Any]: The reconstructed Mongo query
    """
    # pylint: disable=eval-used
    return eval(query_str.replace(STORED_DATETIME_CALL, 'datetime'), _EVAL_GLOBALS)


def read_stored_report_query(report: dict[str, Any]) -> dict[str, Any]:
    """
    Answers a stored report's executable Mongo query, or an empty one when it stores none

    A report written through the routes always carries a query; a document imported or inserted
    directly may not, and that reads as a report without conditions rather than as an error

    Args:
        report (dict[str, Any]): The stored CmdbReport document

    Raises:
        Exception: When a query IS stored but cannot be evaluated - a corrupted document

    Returns:
        dict[str, Any]: The reconstructed Mongo query, empty when the report stores none
    """
    stored_query: Any = report.get(_REPORT_QUERY_KEY)
    query_str: Any = stored_query.get(ReportQueryKey.DATA) if isinstance(stored_query, dict) else None

    if not isinstance(query_str, str) or not query_str.strip():
        return {}

    return eval_stored_report_query(query_str)
