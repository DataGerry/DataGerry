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
Response keys and refusal messages of the bulk port creation
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

class BulkCreateKey(BaseStrEnum):
    """
    Keys of a successful bulk-creation response

    CONNECTIONS is present for a patch panel only, and holds the INTERNAL connections that pair the two
    faces - those ARE the pairing, so they are returned rather than left for the caller to look up
    """
    PORTS = 'ports'
    CONNECTIONS = 'connections'
    TOTAL_PORTS = 'total_ports'
    TOTAL_CONNECTIONS = 'total_connections'


class BulkResidueKey(BaseStrEnum):
    """
    Keys of the residue report, present only when a rollback could not finish

    Named ids rather than a count, because the point of the report is that somebody has to go and
    remove them by hand - a number would tell them how much damage there is without telling them where
    """
    PORT_IDS = 'port_ids'
    CONNECTION_IDS = 'connection_ids'


class BulkCreateError(BaseStrEnum):
    """
    Messages reported when a bulk creation is refused or fails part-way

    Members with a `{...}` placeholder are filled via `format()`
    """
    # Refused before anything is written: the preview already found names that can not all be created
    COLLISIONS_FOUND = (
        'The generated names can not all be created - see the preview for the collisions on each face!'
    )
    # A write failed part-way and the compensating rollback removed everything that had been created.
    # The batch is off, but the database is exactly as it was
    ROLLED_BACK = (
        'Creating the ports failed after {created} of them had been written: {reason}. '
        'Everything that had been created was removed again.'
    )
    # The failure the honest message exists for: the rollback itself could not finish, so rows survive
    # that nobody asked for. §37's "never 24 front / 18 rear / 18 internal" is exactly this state, and
    # it must not be reported as either a success or a clean failure
    ROLLBACK_INCOMPLETE = (
        'Creating the ports failed ({reason}), and the automatic cleanup could not remove everything. '
        'These Ports and Port connections were left behind and have to be removed by hand: {residue}'
    )
