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
Helpers of the rights routes

The rights themselves are a static in-code tree; the only thing about them that lives in the
database is **who holds them** - a CmdbUserGroup stores the right NAMES it grants in its ``rights``
list. Resolving that per right is what this module does, in one aggregation rather than one query
per right
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.manager import GroupsManager
from cmdb.manager.query_builder.builder import Builder

from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.group_model.group_constants import GroupKey

from cmdb.interface.rest_api.routes.user_management_routes.rights_constants import RightHolderKey
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The aggregation groups by the unwound right name, so the grouping key carries it
AGGREGATION_ID_KEY: str = '_id'


def resolve_right_holders(
        groups_manager: GroupsManager,
        right_names: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
    """
    Resolves which CmdbUserGroups hold each of the given rights, in ONE aggregation

    Membership is **literal**: a group holds a right when its stored ``rights`` list contains that
    exact name. A wildcard above it (``base.user-management.group.*``, ``base.*``) grants the right
    at request time through ``CmdbUserGroup.has_extended_right`` but is NOT counted here, which is
    what keeps this answer identical to the one a ``?filter={"rights": "<name>"}`` listing gives -
    the two are shown side by side, as a count and the list behind it

    The alternative to this aggregation is one count query per right, which is what the page it
    serves used to do over HTTP: ~200 requests for a catalogue of ~200 rights

    Args:
        groups_manager (GroupsManager): db interface for CmdbUserGroups
        right_names (list[str]): The right names to resolve holders for

    Returns:
        dict[str, list[dict[str, Any]]]: Right name -> the groups holding it, each carrying its
            public_id, name and label. A right no group holds is absent from the mapping
    """
    if not right_names:
        return {}

    pipeline: list[dict[str, Any]] = [
        # Only groups that hold at least one of the page's rights reach the unwind
        Builder.match_({GroupKey.RIGHTS.value: {'$in': right_names}}),
        Builder.unwind_(f'${GroupKey.RIGHTS.value}'),
        # The unwind produces one document per (group, right) pair, so the second match drops the
        # pairs for rights this page does not show
        Builder.match_({GroupKey.RIGHTS.value: {'$in': right_names}}),
        Builder.group_(
            f'${GroupKey.RIGHTS.value}',
            {
                RightHolderKey.GROUPS.value: {
                    '$push': {
                        CmdbUserGroup.PUBLIC_ID_KEY: f'${CmdbUserGroup.PUBLIC_ID_KEY}',
                        GroupKey.NAME.value: f'${GroupKey.NAME.value}',
                        GroupKey.LABEL.value: f'${GroupKey.LABEL.value}',
                    },
                },
            },
        ),
    ]

    return {
        entry[AGGREGATION_ID_KEY]: entry.get(RightHolderKey.GROUPS.value, [])
        for entry in groups_manager.aggregate(pipeline)
    }


def with_right_holders(
        rights: list[dict[str, Any]],
        holders: dict[str, list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
    """
    Attaches the holding groups and their count to each right of a page

    Every right carries both keys, including the ones no group holds - a client reading
    ``groups_count`` never has to distinguish "none" from "not answered"

    Args:
        rights (list[dict[str, Any]]): The serialised rights of one page
        holders (dict[str, list[dict[str, Any]]]): Right name -> holding groups

    Returns:
        list[dict[str, Any]]: The same rights, each with `groups` and `groups_count` added
    """
    enriched: list[dict[str, Any]] = []

    for right in rights:
        groups: list[dict[str, Any]] = holders.get(right[RightHolderKey.NAME.value], [])
        enriched.append({
            **right,
            RightHolderKey.GROUPS.value: groups,
            RightHolderKey.GROUPS_COUNT.value: len(groups),
        })

    return enriched
