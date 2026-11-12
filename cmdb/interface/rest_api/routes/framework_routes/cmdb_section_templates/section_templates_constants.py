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
Constants of the CmdbSectionTemplate REST routes
"""
# -------------------------------------------------------------------------------------------------------------------- #

# Refusal (HTTP 400) of a create whose name a stored template already holds - the name read's answer, and the
# unique index's when a concurrent create wins the race. Formatted with the name
TEMPLATE_NAME_TAKEN_MESSAGE: str = "A template with the name: {name} already exists!"

# Refusal (HTTP 400) of an update that would turn a global template into a non-global one. Consuming types claim a
# global template by name, and only a global one: the claims would be dropped on their next write and a delete would
# skip their clean-up. The other direction - a template made global - stays allowed
GLOBAL_TEMPLATE_DEMOTION_MESSAGE: str = (
    "A global Section Template can not be made non-global - consuming types reference it by name!"
)
