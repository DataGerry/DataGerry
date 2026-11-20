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
Which CmdbObjects count as ConfigItems - what a cloud subscription's ConfigItem limit holds

Every stored CmdbObject counts, except an object the user sync links to user management (``system_ref``): a person
mirroring a CmdbUser and a person group mapped to a CmdbUserGroup exist because user management does, so they cost no
ConfigItem. An object the sync unlinks - a former user's person, a copy left by a target change, an unmapped group -
counts from then on.

**One criteria for every count that answers the limit question**: the object create's limit check, the object
import's and the per-type count reported to the service portal all read through ``config_item_criteria``, so no two
of them can disagree about the number. It lives beside the manager because the manager's own aggregation needs it
and the manager may not import the framework.
"""
from typing import Any

from cmdb.models.object_model import CmdbObjectKey
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'config_item_criteria',
]


def config_item_criteria() -> dict[str, Any]:
    """
    Builds the filter selecting the CmdbObjects that count as ConfigItems

    Matches every object without a ``system_ref`` - a fresh dict on every call, so a caller narrowing it never changes
    another's

    Returns:
        dict[str, Any]: The filter, usable as a count criteria or as a ``$match`` query
    """
    return {CmdbObjectKey.SYSTEM_REF.value: {'$exists': False}}
