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
Validation schema for CmdbCiExplorerProfile

A CmdbCiExplorerProfile is a saved CI Explorer filter (collection ``framework.ciExplorerProfile``): the
two id filters, and the three toggles saying which optional edge sources the graph walks. Each toggle
defaults to TRUE - the frontend graph's own default (``DEFAULT_CI_EXPLORER_SCOPE``) and the default of
``GET /ci_explorer/items`` - and the default is applied whenever a write leaves the toggle out, the
update included.

This module is the single source of the document's Cerberus validation schema,
consumed as CmdbCiExplorerProfile.SCHEMA.
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_cmdb_ci_explorer_profile_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a CmdbCiExplorerProfile document

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as CmdbCiExplorerProfile.SCHEMA
    """
    # pylint: disable=import-outside-toplevel
    # Resolved at call time, not at module import time: the model imports this builder while its own
    # package __init__ is still running (see class_schema/__init__.py)
    from cmdb.models.ci_explorer_model.ci_explorer_profile_constants import (
        CiExplorerProfileKey,
        DEFAULT_PROFILE_SCOPE,
    )

    def id_filter() -> dict[str, Any]:
        """A list of positive integer ids, empty or null for "no restriction" - a new dict per filter."""
        return {'type': 'list', 'required': False, 'nullable': True, 'empty': True,
                'schema': {'type': 'integer', 'min': 1}}

    return {
        CiExplorerProfileKey.PUBLIC_ID.value: {  # public_id of the CmdbCiExplorerProfile
            'type': 'integer',
            'min': 1,
        },
        CiExplorerProfileKey.NAME.value: {  # Name of the saved CI Explorer filter (visible to users)
            'type': 'string',
            'required': True,
            'empty': False,
        },
        # public_ids of CmdbTypes the saved filter restricts neighbours to; empty = no restriction
        CiExplorerProfileKey.TYPES_FILTER.value: id_filter(),
        # public_ids of CmdbRelations the saved filter restricts edges to; empty = no restriction
        CiExplorerProfileKey.RELATIONS_FILTER.value: id_filter(),
        # The three edge-source toggles: whether the graph includes the location hierarchy, the IPAM
        # hierarchy and the CIs the object is cabled to
        **{
            key: {'type': 'boolean', 'required': False, 'nullable': True, 'empty': True, 'default': default}
            for key, default in DEFAULT_PROFILE_SCOPE.items()
        },
    }
