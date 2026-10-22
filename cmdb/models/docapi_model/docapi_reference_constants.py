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
Constants of a DocAPI document's reference resolution
"""
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'DEFAULT_REFERENCE_DEPTH',
    'LOCATION_NAME_KEY',
]

#: How many reference hops a document follows from each object it renders (the root, an `object(id)`, a relation
#: partner): a reference field resolves to the referenced object's data, whose own references resolve one hop less
DEFAULT_REFERENCE_DEPTH: int = 3

#: The key of a CmdbLocation's display name - what a location field resolves to in a document
LOCATION_NAME_KEY: str = 'name'
