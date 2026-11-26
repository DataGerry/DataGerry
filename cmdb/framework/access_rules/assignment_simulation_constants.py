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
The constants of the assignment simulation (phase 11): the answer's keys, the warnings, the caps
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'SAMPLE_LIMIT',
    'MAX_SIMULATED_MEMBERS',
    'MAX_LISTED_MEMBERS',
    'SimulationKey',
    'SimulationFacet',
    'SimulationWarning',
    'SIMULATION_WARNING_MESSAGES',
    'TEXT_KINDS',
]

# Sample objects per list (D4: also per gained / lost)
SAMPLE_LIMIT: int = 10
# The members a scope with user tokens is counted for one by one (D3)
MAX_SIMULATED_MEMBERS: int = 20
# The members named, for a caller who may view users (D5)
MAX_LISTED_MEMBERS: int = 10
# The field kinds a 'contains' searches as a substring - no index serves it
TEXT_KINDS: frozenset[str] = frozenset({'text', 'textarea'})


class SimulationKey(BaseStrEnum):
    """The keys of a simulation answer"""
    ROLE_ID = 'role_id'
    GROUP_ID = 'group_id'
    SCOPE = 'scope'
    WITHIN_CALLERS_VIEW = 'within_callers_view'
    TOTAL = 'total'
    BY_TYPE = 'by_type'
    TYPE_ID = 'type_id'
    COUNT = 'count'
    SAMPLES = 'samples'
    PUBLIC_ID = 'public_id'
    SUMMARY = 'summary'
    GAINED = 'gained'
    LOST = 'lost'
    MEMBERS = 'members'
    MEMBER_COUNT = 'member_count'
    SIMULATED_MEMBERS = 'simulated_members'
    USER_ID = 'user_id'
    USER_NAME = 'user_name'
    NEWLY_RESTRICTED_TYPES = 'newly_restricted_types'
    WARNINGS = 'warnings'
    CODE = 'code'
    MESSAGE = 'message'


class SimulationFacet(BaseStrEnum):
    """The facets of the one simulation aggregation"""
    BY_TYPE = 'by_type'
    SAMPLES = 'samples'
    ROLE_TOTAL = 'role_total'
    GAINED = 'gained'
    GAINED_SAMPLES = 'gained_samples'
    LOST = 'lost'
    LOST_SAMPLES = 'lost_samples'
    MEMBER_PREFIX = 'member_'


class SimulationWarning(BaseStrEnum):
    """What a simulation warns about (D6) - the frontend asks for confirmation on any (D7)"""
    UNINDEXED_CONTAINS = 'unindexed_contains'
    POORLY_INDEXED = 'poorly_indexed'
    EMPTY = 'empty'
    EVERY_OBJECT = 'every_object'
    UNRESOLVED_TOKEN = 'unresolved_token'
    NEWLY_RESTRICTED = 'newly_restricted'


SIMULATION_WARNING_MESSAGES: dict[SimulationWarning, str] = {
    SimulationWarning.UNINDEXED_CONTAINS: (
        "'contains' on the text field(s) {fields} searches every object - no index serves it"),
    SimulationWarning.POORLY_INDEXED: (
        "'not_equals' / 'not_in' / 'is_empty' on the field(s) {fields} use an index poorly"),
    SimulationWarning.EMPTY: "The scope matches no object",
    SimulationWarning.EVERY_OBJECT: "The scope matches every object of the role's Types - '*' would say the same",
    SimulationWarning.UNRESOLVED_TOKEN: (
        "The user token resolves to nothing for the member(s) {user_ids} - no linked person or person group"),
    SimulationWarning.NEWLY_RESTRICTED: (
        "The Type(s) {type_ids} become restricted - every other user group loses them unless assigned"),
}
