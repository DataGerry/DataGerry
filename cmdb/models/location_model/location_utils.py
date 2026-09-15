# DATAGERRY - OpenSource Enterprise CMDB
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
This module contains helper methods for CmdbLocations

``validate_root_location`` answers whether a document is the synthetic root; ``to_location_document``
normalises a raw location document to the canonical key set (the same keys CmdbLocation.to_json
emits, optional render keys defaulted) and ``sort_locations_by_name`` puts one tree level into the
order the tree renders it in.

The two coercions for the optional render keys live here because the model and this read share them,
but they are applied with **different strictness on purpose**: ``CmdbLocation.__init__`` refuses a
value it cannot store, while a read of a whole tree level falls back to the default and reports it.
Dropping or failing a location is not an option there - a node carries the ``parent`` its children
point at, so losing one row orphans a whole subtree, which is why this module never skips a document
the way the extendable-option list read does
"""
from logging import Logger, getLogger
from typing import Any, Callable

from cmdb.models.location_model.location_constants import CmdbLocationDefault, LocationKey
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

def validate_root_location(tested_location: dict) -> bool:
    """
    Checks if a given location holds valid root location data

    Args:
        tested_location (dict): location data which should be tested

    Returns:
        (bool): Returns boolean if the given dict has valid root location data
    """
    # pylint: disable=import-outside-toplevel
    # Resolved at call time, not at module import time: this is the model layer reaching UP into the
    # database layer, and the predefined root document is built from this package's own constants, so a
    # module-level import closes the cycle cmdb.models.location_model (package __init__) ->
    # predefined_data.cmdb_data -> back into location_constants while this package is still
    # half-initialised - which is what made collection_validator, database_updater, route_utils,
    # init_rest_api and gunicorn unimportable as the first cmdb module of a process
    from cmdb.database.predefined_data.cmdb_data import get_root_location_data

    root_location = get_root_location_data()

    for root_key, root_value in root_location.items():
        if root_key not in tested_location.keys():
            return False

        # check if value is valid
        if root_value != tested_location[root_key]:
            return False

    return True


def coerce_type_icon(type_icon: Any) -> str:
    """
    Resolves the icon a location renders with

    An absent key and a stored ``null`` are the same statement - "no icon of its own" - and both
    answer the default, so the payload never contradicts CmdbLocationDefault. Anything that is not
    text is refused rather than passed on: it reaches the frontend as a CSS class name

    Args:
        type_icon (Any): The value stored under 'type_icon', if any

    Raises:
        ValueError: If a value is present but is not a string

    Returns:
        str: The icon class, or the default when none is stored
    """
    if type_icon is None:
        return CmdbLocationDefault.TYPE_ICON

    if not isinstance(type_icon, str):
        raise ValueError(f"Not a usable type_icon: {type_icon!r}!")

    return type_icon


def coerce_type_selectable(type_selectable: Any) -> bool:
    """
    Resolves whether the location may be picked as a parent for other locations

    Two-state, like every other flag in the product: an absent key or a stored ``null`` means the
    node is selectable (the default), not a third state. A non-boolean is refused instead of being
    read for truthiness - the frontend decides drop targets with ``type_selectable !== false``, so a
    stored ``"false"`` would silently make a node a valid drop target

    Args:
        type_selectable (Any): The value stored under 'type_selectable', if any

    Raises:
        ValueError: If a value is present but is not a boolean

    Returns:
        bool: Whether the node may be chosen as a parent
    """
    if type_selectable is None:
        return CmdbLocationDefault.TYPE_SELECTABLE

    if not isinstance(type_selectable, bool):
        raise ValueError(f"Not a usable type_selectable: {type_selectable!r}!")

    return type_selectable


# The keys a location document may omit, and how each one is resolved. Every other LocationKey is
# answered exactly as stored - see the module docstring for why a read never refuses a document
OPTIONAL_KEY_COERCIONS: dict[str, tuple[Callable[[Any], Any], Any]] = {
    LocationKey.TYPE_ICON.value: (coerce_type_icon, CmdbLocationDefault.TYPE_ICON),
    LocationKey.TYPE_SELECTABLE.value: (coerce_type_selectable, CmdbLocationDefault.TYPE_SELECTABLE),
}


def _read_optional_key(document: dict[str, Any], key: str) -> Any:
    """
    Resolves one optional render key of a stored document, without ever failing

    The model refuses a value it cannot store; a tree level cannot afford that (see the module
    docstring), so an unusable value is reported and answered as the default

    Args:
        document (dict[str, Any]): The stored CmdbLocation document
        key (str): The optional key to resolve

    Returns:
        Any: The stored value, or the key's default when none is stored or it is unusable
    """
    coerce, default = OPTIONAL_KEY_COERCIONS[key]

    try:
        return coerce(document.get(key))
    except ValueError as err:
        LOGGER.warning(
            "[to_location_document] Location ID:%s carries an unusable '%s', answering the default: %s",
            document.get(LocationKey.PUBLIC_ID.value), key, err,
        )

        return default


def to_location_document(document: dict[str, Any]) -> dict[str, Any]:
    """
    Normalises a raw CmdbLocation document to the canonical, JSON-compatible key set

    Answers with exactly the keys ``CmdbLocation.to_json`` emits - and with the same two fallbacks
    for the optional render keys (see CmdbLocationDefault) - so a caller that reads location
    documents straight from the database gets the identical payload a
    ``from_data`` -> ``to_json`` round trip would produce, without building the model. Keys the
    database adds (``_id``) or that a legacy document carries on top of the schema are dropped.

    Built from ``LocationKey`` rather than from a hand-written key list: the enum is the payload
    contract, and this read and the model's shared ``to_json`` must not be able to drift apart when
    a key is added to it

    Args:
        document (dict[str, Any]): A raw CmdbLocation document as stored in the database

    Returns:
        dict[str, Any]: The canonical CmdbLocation payload
    """
    return {
        key.value: _read_optional_key(document, key.value) if key.value in OPTIONAL_KEY_COERCIONS
        else document.get(key.value)
        for key in LocationKey
    }


def sort_locations_by_name(locations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Orders CmdbLocation documents by name, case-insensitively, with the public_id as tie-breaker

    The database reads behind the location tree are unordered as far as the tree is concerned
    (``BaseManager.get_many`` defaults to public_id descending), which surfaced as an
    insertion-order tree. Sorting happens here rather than in the query because MongoDB's default
    binary collation would order 'Zoo' before 'alpha', and a location level is small enough that the
    in-process sort costs nothing. A missing or non-string name sorts as an empty name, a missing
    public_id as 0, so a malformed document can never raise here

    Args:
        locations (list[dict[str, Any]]): CmdbLocation documents of a single tree level

    Returns:
        list[dict[str, Any]]: The same documents, name-ascending with a public_id tie-break
    """
    def sort_key(location: dict[str, Any]) -> tuple[str, int]:
        name: Any = location.get(LocationKey.NAME.value)
        public_id: Any = location.get(LocationKey.PUBLIC_ID.value)

        return (
            name.casefold() if isinstance(name, str) else '',
            public_id if isinstance(public_id, int) else 0,
        )

    return sorted(locations, key=sort_key)
