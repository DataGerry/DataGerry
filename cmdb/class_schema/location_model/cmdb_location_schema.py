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
Validation schema for CmdbLocation

A CmdbLocation is a node in the location tree that wraps a CmdbObject
(collection ``framework.locations``).

This module is the written-down contract of the **stored document**, exposed as CmdbLocation.SCHEMA. It is not a
request validator, and no write runs it: ``POST /locations/`` takes two ids, an optional type id and an optional
name and builds the rest from the object's own type (so its body is not this document), and every other write is
the object mirror (``location_helper.sync_object_location``). What the schema says is held to the model by tests - the keys it requires
are ``CmdbLocation.REQUIRED_INIT_KEYS``, the five the read path refuses a document without, and its defaults are
``CmdbLocationDefault``'s - so the two descriptions of one document cannot drift apart.
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_cmdb_location_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a stored CmdbLocation document

    The five keys a node cannot do without are required. ``parent`` and ``object_id`` may be null but not absent: no
    writer stores a null (the seeded root uses the 0 sentinels of ``RootLocationDefault``), but the tree code reads a
    null as "no usable parent" rather than failing, so the contract allows it. ``type_icon`` and ``type_selectable``
    are optional, defaulting as the model does

    Returns:
        dict: Field name to Cerberus rule mapping, exposed as CmdbLocation.SCHEMA
    """
    # pylint: disable=import-outside-toplevel
    # Resolved at call time, not at module import time: the model imports this builder while its own package
    # __init__ is still running, so a module-level import back into cmdb.models would close that cycle and leave
    # this module unimportable on its own (see class_schema/__init__.py)
    from cmdb.models.location_model.location_constants import CmdbLocationDefault, LocationKey

    return {
        LocationKey.PUBLIC_ID.value: {  # public_id of the CmdbLocation
            'type': 'integer',
        },
        LocationKey.NAME.value: {  # Display name of the location
            'type': 'string',
            'required': True,
        },
        LocationKey.PARENT.value: {  # public_id of the parent CmdbLocation; 0 for the root
            'type': 'integer',
            'required': True,
            'nullable': True,
        },
        LocationKey.OBJECT_ID.value: {  # public_id of the CmdbObject this location represents; 0 for the root
            'type': 'integer',
            'required': True,
            'nullable': True,
        },
        LocationKey.TYPE_ID.value: {  # public_id of the CmdbType of the underlying object
            'type': 'integer',
            'required': True,
        },
        LocationKey.TYPE_LABEL.value: {  # Label of the underlying object's CmdbType
            'type': 'string',
            'required': True,
        },
        LocationKey.TYPE_ICON.value: {  # Icon of the underlying object's CmdbType
            'type': 'string',
            'default': CmdbLocationDefault.TYPE_ICON,
        },
        LocationKey.TYPE_SELECTABLE.value: {  # Whether this location may be chosen as a parent for others
            'type': 'boolean',
            'default': CmdbLocationDefault.TYPE_SELECTABLE,
        },
    }
