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
An update that keeps what its body leaves out

A whole-document update validated without defaults carries only the keys the client sent. Before it is written, each
key it leaves out is taken from the stored document, so an omission keeps the stored value instead of resetting it.
``keep_omitted_keys`` is that completion, shared by every update route that works this way
"""
from typing import Any
from collections.abc import Collection, Iterable
# -------------------------------------------------------------------------------------------------------------------- #


def keep_omitted_keys(
        payload: dict[str, Any],
        stored: dict[str, Any],
        *,
        keys: Iterable[str] | None = None,
        excluded: Collection[str] = (),
        empty_values: tuple[Any, ...] = (),
    ) -> dict[str, Any]:
    """
    The payload completed from the stored document: each key it leaves out takes the stored value

    A key counts as left out when the payload does not carry it, or carries one of ``empty_values`` (an importer that
    spells "empty" as ``None`` / ``''``). A key the payload sends otherwise wins; a key the stored document does not
    hold stays out

    Args:
        payload (dict[str, Any]): The validated update body (never mutated)
        stored (dict[str, Any]): The stored document (never mutated)
        keys (Iterable[str] | None): The keys to complete; None completes every key of the stored document
        excluded (Collection[str]): Keys never taken from the stored document (a secret the read never answers)
        empty_values (tuple[Any, ...]): Values that count as left out. Defaults to none - only an absent key is

    Returns:
        dict[str, Any]: A new dict - the payload, every left-out key filled from the stored document
    """
    completed: dict[str, Any] = dict(payload)

    for key in (stored if keys is None else keys):
        if key in excluded or key not in stored:
            continue

        if key not in completed or completed[key] in empty_values:
            completed[key] = stored[key]

    return completed
