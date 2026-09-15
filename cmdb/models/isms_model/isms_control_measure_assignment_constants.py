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
Document keys of an IsmsControlMeasureAssignment

The keys of the ``isms.controlMeasureAssignment`` documents, named once. They were spelled out as bare
literals in the model, its Cerberus schema, the two person cascades and the ObjectGroup cascade -
``responsible_for_implementation_id`` alone appeared in five places, always paired with its
``_ref_type`` sibling, which is exactly the pair a typo would break silently.

Members are the raw MongoDB keys; use ``.value`` wherever a key is needed as a dict key, a Mongo filter
key or a projection key, so what reaches the database is a plain string
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'ControlMeasureAssignmentKey',
]


class ControlMeasureAssignmentKey(BaseStrEnum):
    """
    Field keys of an IsmsControlMeasureAssignment document
    """
    PUBLIC_ID = 'public_id'
    CONTROL_MEASURE_ID = 'control_measure_id'
    RISK_ASSESSMENT_ID = 'risk_assessment_id'
    PLANNED_IMPLEMENTATION_DATE = 'planned_implementation_date'
    IMPLEMENTATION_STATUS = 'implementation_status'
    FINISHED_IMPLEMENTATION_DATE = 'finished_implementation_date'
    PRIORITY = 'priority'
    RESPONSIBLE_FOR_IMPLEMENTATION_ID_REF_TYPE = 'responsible_for_implementation_id_ref_type'
    RESPONSIBLE_FOR_IMPLEMENTATION_ID = 'responsible_for_implementation_id'
