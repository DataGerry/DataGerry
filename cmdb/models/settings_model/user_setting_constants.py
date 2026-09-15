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
The vocabulary of a CmdbUserSetting document

The four keys were bare literals in the model, in four of the manager's criteria dicts and in the
routes until 2026-09-09; naming them here is what keeps the three layers spelling one document the
same way. `PUBLIC_ID` is in the list because the collection **does** carry one - the manager stamps it
on insert - even though it is not part of the model and not part of what the list route answers
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

class UserSettingKey(BaseStrEnum):
    """
    Keys of a stored CmdbUserSetting document

    RESOURCE + USER_ID are its identity (a unique compound index, see `CmdbUserSetting.INDEX_KEYS`);
    PAYLOADS holds whatever the client stores under that resource; SETTING_TYPE is the stored value of
    a `UserSettingType`. PUBLIC_ID is stamped by the manager on insert and answered by the
    single-resource read only - which read answers which shape is discussion-backlog #218
    """
    PUBLIC_ID = 'public_id'
    RESOURCE = 'resource'
    USER_ID = 'user_id'
    PAYLOADS = 'payloads'
    SETTING_TYPE = 'setting_type'
