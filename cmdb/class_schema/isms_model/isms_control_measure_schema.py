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
Validation schema for IsmsControlMeasure

An IsmsControlMeasure is a control, requirement or measure in the ISMS
(collection ``isms.controlMeasure``).

This module is the single source of the document's Cerberus validation schema,
consumed as IsmsControlMeasure.SCHEMA.
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_isms_control_measure_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a IsmsControlMeasure document

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as IsmsControlMeasure.SCHEMA
    """
    # pylint: disable=import-outside-toplevel
    # Resolved at call time, not at module import time: the model imports this builder while its own
    # package __init__ is still running, so a module-level import back into cmdb.models would close that
    # cycle and leave every class_schema module unimportable on its own (see class_schema/__init__.py)
    from cmdb.models.isms_model.control_measure_type_enum import ControlMeasureType
    from cmdb.models.isms_model.isms_control_measure_constants import ControlMeasureKey

    return {
        ControlMeasureKey.PUBLIC_ID.value: {  # public_id of the IsmsControlMeasure
            'type': 'integer',
            'min': 1,
        },
        ControlMeasureKey.TITLE.value: {  # Title of the control measure
            'type': 'string',
            'required': True,
            'empty': False,
        },
        ControlMeasureKey.CONTROL_MEASURE_TYPE.value: {  # CONTROL / REQUIREMENT / MEASURE (a ControlMeasureType value)
            'type': 'string',
            'required': True,
            'empty': False,
            'allowed': [measure_type.value for measure_type in ControlMeasureType],
        },
        # public_id of the source the control originates from (e.g. a framework / standard)
        ControlMeasureKey.SOURCE.value: {
            'type': 'integer',
            'required': True,
            'nullable': True,
        },
        ControlMeasureKey.IMPLEMENTATION_STATE.value: {  # public_id of CmdbExtendableOption 'IMPLEMENTATION_STATE'
            'type': 'integer',
            'required': True,
            'nullable': True,
        },
        ControlMeasureKey.IDENTIFIER.value: {  # External identifier / catalogue number of the control
            'type': 'string',
            'required': True,
            'nullable': True,
        },
        ControlMeasureKey.CHAPTER.value: {  # Chapter / section reference within the source framework
            'type': 'string',
            'required': True,
            'nullable': True,
        },
        ControlMeasureKey.DESCRIPTION.value: {  # Description of the control measure
            'type': 'string',
            'required': True,
            'nullable': True,
        },
        ControlMeasureKey.IS_APPLICABLE.value: {  # Whether the control is applicable (Statement of Applicability)
            'type': 'boolean',
            'required': True,
            'nullable': True,
        },
        ControlMeasureKey.REASON.value: {  # Justification for applicability or exclusion
            'type': 'string',
            'required': True,
            'nullable': True,
        },
    }
