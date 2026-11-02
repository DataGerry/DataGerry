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
Constants of the ObjectsManager's aggregation pipelines

The document keys of a CmdbObject live in ``cmdb.models.object_model`` (``CmdbObjectKey``); what is named here
belongs to the manager's queries instead: the keys of the per-type count groups
"""
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'TYPE_GROUP_ID_KEY',
    'TYPE_GROUP_COUNT_KEY',
]

# A per-type count group: MongoDB's own grouping key (the type_id) and the number of objects in the group
TYPE_GROUP_ID_KEY: str = '_id'
TYPE_GROUP_COUNT_KEY: str = 'count'
