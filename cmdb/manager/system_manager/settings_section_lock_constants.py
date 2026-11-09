# DATAGERRY - OpenSource Enterprise CMDB
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
The values a settings-section lock holds (`settings_section_lock`)
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class SectionLockKey(BaseStrEnum):
    """
    The values a lock's settings section holds

    Members:
        HOLDER: The token of the request holding the lock; only that request releases it
        ACQUIRED_AT: When the lock was taken (UTC); after the lock's TTL it may be taken over
        USER_ID: public_id of the user whose request holds it, for the log
    """
    HOLDER = 'holder'
    ACQUIRED_AT = 'acquired_at'
    USER_ID = 'user_id'
