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
Implementation of CmdbLocation in DataGerry

A CmdbLocation is **one node of the location tree, mirroring one CmdbObject's place in it**. The
document carries no location data of its own beyond the tree edge (`parent`) and a snapshot of the
underlying object's render metadata (`type_label`, `type_icon`, `type_selectable`), copied at write
time so the tree can be drawn without reading a type per node.

**The frontend does not write these documents.** The object write path mirrors them - see
`cmdb_locations/location_helper.py::sync_object_location` - and the `POST /locations/` route exists
for completeness; both go through raw dicts, so this model is a **read-side** class: it hydrates
documents for the two list routes and for the three callers that need one field off a location.

Three invariants of the collection shape it:

* `object_id` is **unique**: a CmdbObject owns at most one node, which is what lets
  `LocationsManager.get_location_for_object` be a single-document read. Existing databases were
  created with a non-unique index - `updater_20260804` de-duplicates and rebuilds it.
* the tree is rooted in a **synthetic root document** (`public_id` 1, the 0 sentinels for `parent`,
  `object_id` and `type_id` - see `RootLocationDefault`). It is seeded with the database, is backed
  by no object, and carries all eight keys like any other node.
* `type_selectable` and `type_icon` are a **snapshot, not a live reference**: they are copied from
  the CmdbType when the node is written, so flipping the type later reaches existing nodes only
  through `LocationsManager.update_locations_by_type`. The tree's drop targets are drawn from the
  copy.

`LocationKey` names every persisted key and drives the shared `CmdbDAO.from_data` / `to_json`, so
this model implements neither: the enum is the payload contract, and `REQUIRED_INIT_KEYS` is what
makes the five keys a node cannot do without actually required on the read path. The constructor is
the validating place for the two optional render keys and coerces them through `location_utils`,
which the document-level read shares - see that module for why a read is the more forgiving of the
two.
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.location_model.location_constants import CmdbLocationDefault, LocationKey
from cmdb.models.location_model.location_utils import coerce_type_icon, coerce_type_selectable

from cmdb.class_schema.location_model.cmdb_location_schema import get_cmdb_location_schema

from cmdb.errors.models.cmdb_location import (
    CmdbLocationInitError,
    CmdbLocationInitFromDataError,
    CmdbLocationToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 CmdbLocation - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbLocation(CmdbDAO):
    """
    Implementation of CmdbLocation, one node of the location tree

    Extends: CmdbDAO
    """
    COLLECTION = 'framework.locations'

    # The five keys a node cannot do without: without them it names no tree edge and nothing to
    # render. Enforced by the shared from_data, which refuses a document missing one instead of
    # building an instance holding None - the shape the list routes used to answer as 'name': null.
    # Every writer produces all of them (the object mirror, the POST route and the seeded root), and
    # the partial mirror update is a '$set', so no stored document loses one
    REQUIRED_INIT_KEYS: list[str] = [
        LocationKey.NAME.value,
        LocationKey.PARENT.value,
        LocationKey.OBJECT_ID.value,
        LocationKey.TYPE_ID.value,
        LocationKey.TYPE_LABEL.value,
    ]

    # 'object_id' is unique: a CmdbObject has at most one node in the location tree, which the code
    # relies on throughout (LocationsManager.get_location_for_object is a get_one_by, and the
    # object<->location mirror in location_helper assumes the single node it finds is the only one).
    # Existing databases were created with this index non-unique - updater_20260804 de-duplicates and
    # rebuilds it, because index reconciliation matches on name only and never on options
    INDEX_KEYS: list[dict[str, Any]] = [
        {
            'keys': [(LocationKey.OBJECT_ID.value, CmdbDAO.DAO_ASCENDING)],
            'name': LocationKey.OBJECT_ID.value,
            'unique': True,
        },
        {
            'keys': [(LocationKey.PARENT.value, CmdbDAO.DAO_ASCENDING)],
            'name': LocationKey.PARENT.value,
            'unique': False,
        },
        {
            'keys': [(LocationKey.TYPE_ID.value, CmdbDAO.DAO_ASCENDING)],
            'name': LocationKey.TYPE_ID.value,
            'unique': False,
        },
    ]

    SCHEMA: dict[str, Any] = get_cmdb_location_schema()

    # The document's keys drive the shared from_data / to_json on CmdbDAO, so this model has neither
    KEYS = LocationKey
    INIT_FROM_DATA_ERROR = CmdbLocationInitFromDataError
    TO_JSON_ERROR = CmdbLocationToJsonError


    def __init__(
            self,
            *,
            public_id: int,
            name: str,
            parent: int,
            object_id: int,
            type_id: int,
            type_label: str,
            type_icon: str | None = CmdbLocationDefault.TYPE_ICON,
            type_selectable: bool | None = CmdbLocationDefault.TYPE_SELECTABLE,
        ) -> None:
        """
        Initialises a CmdbLocation

        Keyword-only, because CmdbDAO.__new__ looks for public_id in **kwargs and runs before this:
        a positional call could never have worked

        Args:
            public_id (int): public_id of the CmdbLocation
            name (str): Name of the node as the location tree displays it
            parent (int): public_id of the parent CmdbLocation (the root's is the 0 sentinel)
            object_id (int): public_id of the CmdbObject this node mirrors (0 for the root)
            type_id (int): public_id of the CmdbType of that object (0 for the root)
            type_label (str): Label of that CmdbType, copied at write time
            type_icon (str | None): Icon of that CmdbType, copied at write time. None - an absent or
                                    null key - reads as CmdbLocationDefault.TYPE_ICON
            type_selectable (bool | None): Whether this node may be chosen as a parent for other
                                           locations, copied from the CmdbType at write time and not
                                           updated when the type changes. None reads as
                                           CmdbLocationDefault.TYPE_SELECTABLE

        Raises:
            CmdbLocationInitError: If the CmdbLocation could not be initialised
        """
        try:
            self.name: str = name
            self.parent: int = parent
            self.object_id: int = object_id
            self.type_id: int = type_id
            self.type_label: str = type_label
            self.type_icon: str = coerce_type_icon(type_icon)
            self.type_selectable: bool = coerce_type_selectable(type_selectable)

            super().__init__(public_id=public_id)
        except Exception as err:
            raise CmdbLocationInitError(err) from err
