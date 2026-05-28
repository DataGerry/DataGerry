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
Validation schema for CmdbSectionTemplate

A CmdbSectionTemplate is a reusable section definition that CmdbTypes can include
(collection ``framework.sectionTemplates``).

This module is the single source of the document's Cerberus validation schema,
consumed as CmdbSectionTemplate.SCHEMA.
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_cmdb_section_template_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a CmdbSectionTemplate document

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as CmdbSectionTemplate.SCHEMA
    """
    return {
        'public_id': {  # public_id of the CmdbSectionTemplate
            'type': 'integer',
        },
        'is_global': {  # True if the template is shared/reusable across CmdbTypes
            'type': 'boolean',
            'default': False,
        },
        'predefined': {  # True if provided by DataGerry rather than user-created
            'type': 'boolean',
            'default': False,
        },
        'name': {  # Unique name of the section template
            'type': 'string',
            'required': True,
        },
        'label': {  # Displayed label of the section template
            'type': 'string',
            'required': True,
        },
        'type': {  # Section kind (a SectionType value)
            'type': 'string',
            'default': 'section',
        },
        'fields': {  # Field definitions contained in the template
            'type': 'list',
            'required': True,
            'default': [],
        },
    }
