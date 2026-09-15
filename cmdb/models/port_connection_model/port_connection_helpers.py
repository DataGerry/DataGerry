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
The endpoint arithmetic of a port connection - the single source of truth for its canonical form

A connection is UNDIRECTED: 'port A is connected to port B' is the same fact as 'port B is connected
to port A', and the concept is explicit that both ends must be treated symmetrically. That symmetry is
made structural by storing the two ids SORTED ASCENDING, so the two spellings of one link are one
document - which in turn is what lets a single index refuse a duplicate pair, and what keeps any
reader from mistaking the first id for a source.

Every consumer canonicalises through here: the model's own constructor and the connection validator
the write path runs. Keeping one implementation is what stops a document from ever being stored
unsorted while everything downstream assumes it is not.

Lives in the model layer rather than under cmdb/framework/port/ so the CmdbPortConnection model can
use it without a framework import
"""
from typing import Any

from cmdb.utils import coerce_whole_number

from cmdb.models.port_connection_model.port_connection_constants import ENDPOINT_COUNT
# -------------------------------------------------------------------------------------------------------------------- #

def coerce_endpoints(endpoints: Any) -> list[int] | None:
    """
    Reads a raw endpoints value into exactly two port ids, or reports that it is unusable

    Deliberately strict about the COUNT and lenient about the notation: a JSON client may send 42.0
    and a CSV one '42', both of which name port 42, but a list of one or three ids does not name a
    connection at all and no default could repair it. A self-connection is NOT judged here - it is a
    business rule with its own message, and this function is also what the model uses on read, where
    a historical row must still be readable

    Args:
        endpoints (Any): The raw endpoints value from a request or a stored document

    Returns:
        list[int] | None: The two port ids, or None when the value does not name two ports
    """
    if not isinstance(endpoints, (list, tuple)):
        return None

    if len(endpoints) != ENDPOINT_COUNT:
        return None

    coerced: list[int | None] = [coerce_whole_number(endpoint) for endpoint in endpoints]

    if any(endpoint is None for endpoint in coerced):
        return None

    return [endpoint for endpoint in coerced if endpoint is not None]


def sort_endpoints(endpoints: Any) -> list[int] | None:
    """
    Returns the canonical, ascending form of a connection's two endpoints

    The one place the sort happens. Sorting on write is what makes 1 to 10 and 10 to 1 the same
    document, so 'no duplicate pair' needs no rule of its own and the two partial unique indexes can
    do their work

    Args:
        endpoints (Any): The raw endpoints value from a request or a stored document

    Returns:
        list[int] | None: The two port ids in ascending order, or None when the value is unusable
    """
    coerced: list[int] | None = coerce_endpoints(endpoints)

    if coerced is None:
        return None

    return sorted(coerced)


def is_self_connection(endpoints: Any) -> bool:
    """
    Reports whether both endpoints name the same port

    This is the one cardinality rule the database cannot hold: [5, 5] dedupes to a single key within
    one document, so a unique multikey index sees nothing wrong with it. It stays a validator rule for
    exactly that reason

    Args:
        endpoints (Any): The raw endpoints value from a request or a stored document

    Returns:
        bool: True when the two endpoints are the same port; False when they differ or are unusable
    """
    coerced: list[int] | None = coerce_endpoints(endpoints)

    if coerced is None:
        return False

    return coerced[0] == coerced[1]
