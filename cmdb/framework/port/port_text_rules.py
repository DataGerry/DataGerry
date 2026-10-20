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
The text cap of the port surface, for the values no request schema sees

``POST /ports/`` and ``PUT|PATCH /ports/<id>`` validate their body against the port write schema, which
caps ``name`` and ``description``. The bulk routes are built differently: the creation writes the names
the preview GENERATED, from a syntax, a prefix and a slot, and it and the bulk edit carry their
descriptions in body keys of their own. This module applies the same cap - ``TEXT_VALUE_MAX_LENGTH`` -
to all of them, so a port written by a batch can never hold what a port written alone could not.

Pure and free of Flask: the routes turn the reasons into a 400
"""
from typing import Any, Iterable, Mapping

from cmdb.models.type_model.type_constants import TEXT_VALUE_MAX_LENGTH
from cmdb.framework.port.port_text_constants import EXCERPT_ELLIPSIS, NAME_EXCERPT_LENGTH, PortTextError
# -------------------------------------------------------------------------------------------------------------------- #


def text_value_blockers(values: Mapping[str, Any], keys: Iterable[str]) -> list[str]:
    """
    Every reason the named text values of a request would be refused, reported at once

    A key the request leaves out, or sends as null, is not judged: every one of these values is
    optional, and whether a REQUIRED one (a syntax) is present is its own rule's business

    Args:
        values (Mapping[str, Any]): The request body, or the part of it carrying the values
        keys (Iterable[str]): The keys whose values must be text within the cap

    Returns:
        list[str]: The reasons, in the order of ``keys``; empty when every value is usable
    """
    blockers: list[str] = []

    for key in keys:
        value: Any = values.get(key)

        if value is None:
            continue

        if not isinstance(value, str):
            blockers.append(PortTextError.NOT_TEXT.format(field=key, value_type=type(value).__name__))
        elif len(value) > TEXT_VALUE_MAX_LENGTH:
            blockers.append(PortTextError.TOO_LONG.format(field=key, length=len(value), maximum=TEXT_VALUE_MAX_LENGTH))

    return blockers


def long_name_blockers(names: Iterable[str]) -> list[str]:
    """
    The reason generated port names would be refused for their length

    One reason for the whole batch, however many names are too long - a syntax that is too long is so
    for every name it generates, and a thousand identical sentences would bury the one that matters. It
    names how many are affected and quotes the first

    Args:
        names (Iterable[str]): The generated names

    Returns:
        list[str]: One reason when any name is longer than the cap; empty otherwise
    """
    too_long: list[str] = [name for name in names if len(name) > TEXT_VALUE_MAX_LENGTH]

    if not too_long:
        return []

    first: str = too_long[0]
    excerpt: str = first if len(first) <= NAME_EXCERPT_LENGTH else first[:NAME_EXCERPT_LENGTH] + EXCERPT_ELLIPSIS

    return [PortTextError.NAMES_TOO_LONG.format(
        count=len(too_long), maximum=TEXT_VALUE_MAX_LENGTH, excerpt=excerpt, length=len(first),
    )]
