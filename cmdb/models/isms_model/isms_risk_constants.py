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
Document keys of an IsmsRisk

The keys of the ``isms.risk`` documents, named once. They were previously spelled out as bare literals
in four independent places - the model's ``from_data`` and ``to_json``, the Cerberus schema, and both
halves of the CSV importer (its header set and the candidate row it builds) - 46 occurrences for ten
keys, so a renamed or mistyped key showed up as a silently missing value rather than as an error.

The order of the members is the order ``CmdbDAO.to_json`` emits, since the shared implementation walks
this enum: ``public_id`` first, then the document's own fields.

Members are the raw MongoDB keys; use ``.value`` wherever a key is needed as a dict key, a Mongo
filter key or a projection key, so what reaches the database is a plain string
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'RiskKey',
    'RISK_IMPORT_KEYS',
]


class RiskKey(BaseStrEnum):
    """
    Field keys of an IsmsRisk document
    """
    PUBLIC_ID = 'public_id'
    NAME = 'name'
    RISK_TYPE = 'risk_type'
    PROTECTION_GOALS = 'protection_goals'
    THREATS = 'threats'
    VULNERABILITIES = 'vulnerabilities'
    CATEGORY_ID = 'category_id'
    IDENTIFIER = 'identifier'
    CONSEQUENCES = 'consequences'
    DESCRIPTION = 'description'


# The columns a risk CSV carries. Derived from the document keys minus the two the import does not
# accept: the server-owned public_id, and category_id, which the importer has never read - an imported
# risk gets its category in the UI afterwards
RISK_IMPORT_KEYS: tuple[str, ...] = tuple(
    key.value for key in RiskKey if key not in (RiskKey.PUBLIC_ID, RiskKey.CATEGORY_ID)
)
