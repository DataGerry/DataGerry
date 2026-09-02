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
``RootLocationDefault`` moved to ``cmdb.models.location_model.location_constants`` on 2026-08-27,
and ``ExtendableOptionKey`` to ``cmdb.models.extendable_option_model.extendable_option_constants``
on 2026-09-02, for the same reason: the manager, route and helper layers all consume them, and
importing a document-key enum upward from the database layer is the wrong direction.
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


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
