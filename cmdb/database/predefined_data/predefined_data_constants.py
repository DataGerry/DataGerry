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
Key constants for the predefined (seed) data documents

The factory functions in this package build the documents inserted at setup. The document keys are
model-field identifiers, so they are named here (one BaseStrEnum per document type) instead of
repeated as string literals. All string enums extend BaseStrEnum, so members compare equal to their
string value for dict construction, lookup and JSON/BSON serialization.

Only keys whose consumers are inside ``cmdb/database`` belong here. ``LocationKey`` and
``RootLocationDefault`` moved to ``cmdb.models.location_model.location_constants`` on 2026-08-27
because the manager, route, helper and Rack layers all consume them, and importing a document-key
enum upward from the database layer is the wrong direction. ``ExtendableOptionKey`` below has the same
problem (the CmdbExtendableOption routes and helper import it) and has NOT been moved - it belongs
with that feature's own audit rather than with this one.
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class ExtendableOptionKey(BaseStrEnum):
    """Document keys of a CmdbExtendableOption"""
    VALUE = 'value'
    OPTION_TYPE = 'option_type'
    PREDEFINED = 'predefined'


class ProtectionGoalKey(BaseStrEnum):
    """Document keys of an IsmsProtectionGoal"""
    PUBLIC_ID = 'public_id'
    NAME = 'name'
    PREDEFINED = 'predefined'


class RiskMatrixKey(BaseStrEnum):
    """Document keys of an IsmsRiskMatrix"""
    PUBLIC_ID = 'public_id'
    RISK_MATRIX = 'risk_matrix'
    MATRIX_UNIT = 'matrix_unit'
