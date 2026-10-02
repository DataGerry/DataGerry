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
Validation schema for CmdbPort

A CmdbPort is one physical port of one CmdbObject (collection ``framework.ports``). The port owns its
own document and its own public_id; the CmdbObject stores nothing about its ports.

This module is the single source of the document's Cerberus validation schema, consumed as
CmdbPort.SCHEMA. It describes the document's SHAPE only: that a port name is unique within
(object_id, side) is enforced by the collection's unique index, and that a select value is one the
matching CmdbExtendableOption list actually offers is a cross-collection rule neither a schema nor an
index can express. The two free-text fields are capped at TEXT_VALUE_MAX_LENGTH, the cap every
CmdbType text field and every cable text field has.

Which writes run what:

  - ``POST /ports/`` and ``PUT|PATCH /ports/<id>`` validate their body against
    ``get_cmdb_port_write_schema`` - derived from this one, so a field's type and cap are declared once
  - the bulk creation writes ports the name preview generated, and the preview judges what they are
    built from (the syntaxes, the prefix and slot, the descriptions, every generated name) by the same
    cap - ``cmdb.framework.port.port_text_rules``; the bulk edit judges its description the same way
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_cmdb_port_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a CmdbPort document

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as CmdbPort.SCHEMA
    """
    # pylint: disable=import-outside-toplevel
    # Resolved at call time, not at module import time: the model imports this builder while its own
    # package __init__ is still running, so a module-level import back into cmdb.models would close that
    # cycle and leave every class_schema module unimportable on its own (see class_schema/__init__.py)
    from cmdb.models.port_model.port_constants import PortKey, PortSide
    from cmdb.models.type_model.type_constants import TEXT_VALUE_MAX_LENGTH

    return {
        PortKey.PUBLIC_ID.value: {  # public_id of the CmdbPort - the id every other collection uses
            'type': 'integer',
        },
        PortKey.OBJECT_ID.value: {  # public_id of the CmdbObject owning the port
            'type': 'integer',
            'required': True,
        },
        PortKey.SIDE.value: {  # Which face of the object the port sits on; panel-ness derives from it
            'type': 'string',
            'required': False,
            'allowed': [side.value for side in PortSide],
            'default': PortSide.SINGLE.value,
        },
        PortKey.NAME.value: {  # The port's label, unique within (object_id, side)
            'type': 'string',
            'required': True,
            'empty': False,
            'maxlength': TEXT_VALUE_MAX_LENGTH,
        },
        PortKey.PORT_NUMBER.value: {  # Optional number used for ordering (concept §4)
            'type': 'integer',
            'nullable': True,
            'required': False,
        },
        PortKey.STATUS.value: {  # public_id of a PORT_STATUS CmdbExtendableOption
            'type': 'integer',
            'nullable': True,
            'required': False,
        },
        PortKey.PORT_TYPE.value: {  # public_id of a PORT_TYPE CmdbExtendableOption
            'type': 'integer',
            'nullable': True,
            'required': False,
        },
        PortKey.SPEED.value: {  # public_id of a PORT_SPEED CmdbExtendableOption
            'type': 'integer',
            'nullable': True,
            'required': False,
        },
        PortKey.DESCRIPTION.value: {  # Free text
            'type': 'string',
            'nullable': True,
            'required': False,
            'maxlength': TEXT_VALUE_MAX_LENGTH,
        },
        PortKey.AUTHOR_ID.value: {  # public_id of the CmdbUser who created the port
            'type': 'integer',
            'nullable': True,
            'required': False,
        },
        PortKey.CREATION_TIME.value: {  # When the port was created
            'type': 'dict',
            'nullable': True,
            'required': False,
        },
        PortKey.LAST_EDIT_TIME.value: {  # When the port was last changed
            'type': 'dict',
            'nullable': True,
            'required': False,
        },
    }


def get_cmdb_port_write_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a CmdbPort REQUEST body (create and update)

    Derived from the document schema, so a field's type and its text cap are declared once, with three
    deliberate differences:

      - the SERVER-OWNED keys are absent (public_id and the three audit fields). The validator runs with
        ``purge_unknown=True``, so a payload carrying an author_id or a creation_time never reaches the
        route at all
      - ``object_id`` and ``side`` are accepted UNTYPED. The routes judge both with messages of their own
        (the owner is read through its ACL, a side is named against the allowed ones), and a type rule
        refusing them first would replace those messages with the decorator's generic one
      - nothing is required, and ``name`` may be empty or null: the routes answer a missing or blank
        name with their own message - the schema adds only that a given name is a string within the cap

    Returns:
        dict: Field name to Cerberus rule mapping for a create or update body
    """
    # pylint: disable=import-outside-toplevel
    # Same cycle as get_cmdb_port_schema: resolved at call time, not at module import time
    from cmdb.models.port_model.port_constants import PortKey
    from cmdb.class_schema.write_schema_helper import build_write_schema

    write_schema: dict[str, Any] = build_write_schema(get_cmdb_port_schema(), server_owned=(
        PortKey.PUBLIC_ID.value,
        PortKey.AUTHOR_ID.value,
        PortKey.CREATION_TIME.value,
        PortKey.LAST_EDIT_TIME.value,
    ))
    untyped: set[str] = {PortKey.OBJECT_ID.value, PortKey.SIDE.value}

    schema: dict[str, Any] = {
        key: ({'required': False} if key in untyped else {**rules, 'required': False})
        for key, rules in write_schema.items()
    }
    schema[PortKey.NAME.value] = {**schema[PortKey.NAME.value], 'empty': True, 'nullable': True}

    return schema
