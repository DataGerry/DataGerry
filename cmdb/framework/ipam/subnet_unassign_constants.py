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
Messages and bounds of the subnet 'unassign IPs' write (``subnet_unassign``)

The named placeholders are filled by the caller. Every message here is a 400 or 404 the orchestrator answers before
or while writing the interface owners
"""
# -------------------------------------------------------------------------------------------------------------------- #

# How often one owner's write is planned again after a concurrent edit changed it between the read and the write. A
# miss re-reads that owner and re-plans the unassign from what is stored now; past this many attempts the request
# stops with OWNER_KEPT_CHANGING_MSG
MAX_OWNER_WRITE_ATTEMPTS: int = 3

IPS_NOT_A_LIST_MSG: str = "'{ips_key}' must be a non-empty list of IP strings!"
IPS_TOO_MANY_MSG: str = "At most {max_ips} IPs can be unassigned at once, but {count} were sent!"
IPS_NON_STRING_ENTRY_MSG: str = "'{ips_key}' contains a non-string entry: {entry!r}"
IPS_INVALID_ENTRY_MSG: str = "'{ips_key}' contains an invalid IP address: {entry!r}"
IP_OUTSIDE_SUBNET_MSG: str = "IP {entry!r} is outside subnet {network}!"
IPS_NOT_ASSIGNED_MSG: str = "Cannot unassign IPs {missing} - they are not currently assigned to subnet {subnet_id}!"
NO_SUBNET_TYPE_MSG: str = "No SUBNET CmdbType is defined; cannot unassign interface rows!"
SUBNET_NOT_FOUND_MSG: str = "Subnet with public_id {subnet_id} was not found!"
NOT_A_SUBNET_MSG: str = "Object with public_id {subnet_id} is not a SUBNET!"
SUBNET_RANGE_MISSING_MSG: str = "Subnet has no network range defined; cannot unassign interface rows!"
SUBNET_RANGE_NOT_CANONICAL_MSG: str = "Subnet network range {raw_cidr!r} is not a canonical CIDR; cannot unassign!"
UNASSIGN_MODE_INVALID_MSG: str = "'{raw_mode}' is not a valid unassign mode (expected '{reference}' or '{row}')!"
OWNER_KEPT_CHANGING_MSG: str = (
    "The object with public_id {owner_id} was changed by another edit {attempts} times while its IPs were being "
    "unassigned; the owners before it were unassigned - please try again!"
)
