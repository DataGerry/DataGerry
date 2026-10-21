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
Constants owned by the `BaseManager`

They live here rather than in the manager module so the manager file stays behaviour only, per the project's
`<domain>_constants.py` convention
"""
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = ['EMPTY_DELETE_FILTER_MSG']

# Why `BaseManager.delete_many` refuses an empty filter: `{}` matches every document, so a filter that came out
# empty would delete the whole collection
EMPTY_DELETE_FILTER_MSG: str = (
    "Refusing to delete from collection '{collection}' with an empty filter: it would delete every document"
)
