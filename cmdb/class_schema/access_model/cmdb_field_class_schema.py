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
Validation schema for CmdbFieldClass

A CmdbFieldClass is a named protection class of the permission data model (collection ``access.fieldClasses``): a
field carrying it may only be written by a scope role granting it. Its name is the identifier fields and scope roles
reference - a slug, unique and immutable, never the built-in ``system`` class.

This module is the single source of the document's Cerberus validation schema,
consumed as CmdbFieldClass.SCHEMA.
"""
from typing import Any

from cmdb.class_schema.access_model.access_schema_helper import (
    check_not_blank,
    get_description_rule,
    get_field_class_name_rule,
)
# -------------------------------------------------------------------------------------------------------------------- #

def get_cmdb_field_class_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a CmdbFieldClass document

    Returns:
        dict[str, Any]: Field name to Cerberus rule mapping, consumed as CmdbFieldClass.SCHEMA
    """
    # pylint: disable=import-outside-toplevel
    # Resolved at call time, not at module import time: the model imports this builder while its own
    # package __init__ is still running (see class_schema/__init__.py)
    from cmdb.models.access_model.access_constants import FieldClassKey, LABEL_MAX_LENGTH

    return {
        FieldClassKey.PUBLIC_ID.value: {  # public_id of the CmdbFieldClass
            'type': 'integer',
            'min': 1,
        },
        FieldClassKey.NAME.value: {  # The identifier fields and scope roles reference: a slug, unique, immutable
            **get_field_class_name_rule(),
            'required': True,
        },
        FieldClassKey.LABEL.value: {  # The name the class is shown under, freely editable
            'type': 'string',
            'required': True,
            'empty': False,
            'maxlength': LABEL_MAX_LENGTH,
            'check_with': check_not_blank,
        },
        FieldClassKey.DESCRIPTION.value: get_description_rule(),  # What the class protects
    }
