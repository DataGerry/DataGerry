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
Document keys of an IsmsThreat

The keys of the ``isms.threat`` documents, named once - they were spelled out as bare literals in
the model's ``from_data``, its ``to_json``, the Cerberus schema and the CSV importer's header set: 19
occurrences for five keys.

The key set is deliberately identical to ``VulnerabilityKey``: a threat and a vulnerability are the same
document shape with different meanings, they share one ``THREAT_VULNERABILITY`` extendable-option type
for their ``source``, and one importer helper reads both. That is also why the shared
``CmdbDAO.to_json`` type-checks its instance - without it one serialises cleanly as the other, and
``IsmsRisk`` keeps them in two separate reference lists where a swap would go unnoticed.

``THREAT_IMPORT_KEYS`` is the CSV column set, derived from the document keys minus the server-owned
public_id, so the importer's header contract cannot drift from the collection

Members are the raw MongoDB keys; use ``.value`` wherever a key is needed as a dict key, a Mongo filter
key or a projection key, so what reaches the database is a plain string
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'ThreatKey',
    'THREAT_IMPORT_KEYS',
]


class ThreatKey(BaseStrEnum):
    """
    Field keys of an IsmsThreat document
    """
    PUBLIC_ID = 'public_id'
    NAME = 'name'
    SOURCE = 'source'
    IDENTIFIER = 'identifier'
    DESCRIPTION = 'description'


# The columns a threat CSV carries: every document key except the server-owned public_id
THREAT_IMPORT_KEYS: tuple[str, ...] = tuple(
    key.value for key in ThreatKey if key is not ThreatKey.PUBLIC_ID
)
