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
The names a port delete gives its writes in a WriteLedger, so a residue report says what is left behind
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'CascadeLedgerDescription',
]


class CascadeLedgerDescription(BaseStrEnum):
    """
    What each delete of `delete_ports_with_dependents` removes, as the ledger's residue names it
    """
    CONNECTIONS = "the connections of Ports {port_ids} deleted"
    INTERFACE_LINKS = "the interface links of Ports {port_ids} deleted"
    PORTS = "Ports {port_ids} deleted"
