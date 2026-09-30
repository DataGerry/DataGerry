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
Unit tests for the rights route helpers

Pure: no Mongo, no Flask. The rights themselves are a static in-code tree; the only database-backed
part is WHO holds them, and that is resolved in one aggregation. What is pinned here is the shape of
that aggregation - it is what keeps a page of rights from costing one query per right - and that the
literal membership rule is the one applied
"""
from typing import Any
from unittest.mock import MagicMock

from cmdb.models.group_model.group_constants import GroupKey
from cmdb.interface.rest_api.routes.user_management_routes.rights_constants import RightHolderKey
from cmdb.interface.rest_api.routes.user_management_routes.rights_helper import (
    resolve_right_holders,
    with_right_holders,
)
# -------------------------------------------------------------------------------------------------------------------- #

RIGHT_A: str = 'base.framework.type.view'
RIGHT_B: str = 'base.framework.object.view'
UNHELD_RIGHT: str = 'base.docapi.template.add'

ADMIN_GROUP: dict[str, Any] = {'public_id': 1, 'name': 'admin', 'label': 'Administrator'}
USER_GROUP: dict[str, Any] = {'public_id': 2, 'name': 'user', 'label': 'User'}


def _manager(aggregation_result: list[dict[str, Any]]) -> MagicMock:
    """A GroupsManager stand-in whose aggregate() answers the given documents."""
    manager = MagicMock()
    manager.aggregate.return_value = aggregation_result

    return manager


# -------------------------------------------------------------------------------------------------------------------- #
#                                             resolve_right_holders                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_the_holders_are_keyed_by_right_name() -> None:
    """The aggregation groups by the unwound right, so its _id is the right's name"""
    manager = _manager([{'_id': RIGHT_A, RightHolderKey.GROUPS.value: [USER_GROUP]}])

    assert resolve_right_holders(manager, [RIGHT_A]) == {RIGHT_A: [USER_GROUP]}


def test_one_aggregation_serves_the_whole_page() -> None:
    """The point of the helper: a page of N rights costs ONE query, not N"""
    manager = _manager([
        {'_id': RIGHT_A, RightHolderKey.GROUPS.value: [USER_GROUP]},
        {'_id': RIGHT_B, RightHolderKey.GROUPS.value: [USER_GROUP, ADMIN_GROUP]},
    ])

    resolve_right_holders(manager, [RIGHT_A, RIGHT_B, UNHELD_RIGHT])

    manager.aggregate.assert_called_once()


def test_the_pipeline_asks_only_for_the_pages_rights() -> None:
    """Both matches are scoped to the page, so the unwind never walks the whole collection"""
    manager = _manager([])
    page = [RIGHT_A, RIGHT_B]

    resolve_right_holders(manager, page)

    pipeline = manager.aggregate.call_args.args[0]
    matches = [stage['$match'][GroupKey.RIGHTS.value]['$in'] for stage in pipeline if '$match' in stage]

    assert matches == [page, page]
    assert any('$unwind' in stage for stage in pipeline)


def test_no_right_names_means_no_query_at_all() -> None:
    """An empty page must not send an aggregation matching everything"""
    manager = _manager([])

    assert resolve_right_holders(manager, []) == {}
    manager.aggregate.assert_not_called()


def test_a_right_no_group_holds_is_absent_from_the_mapping() -> None:
    """The aggregation only answers what it found; the caller fills the rest in"""
    manager = _manager([{'_id': RIGHT_A, RightHolderKey.GROUPS.value: [USER_GROUP]}])

    assert UNHELD_RIGHT not in resolve_right_holders(manager, [RIGHT_A, UNHELD_RIGHT])


# -------------------------------------------------------------------------------------------------------------------- #
#                                              with_right_holders                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_every_right_gains_both_keys() -> None:
    """Including the ones nobody holds - a client never distinguishes none from not answered"""
    rights = [{'name': RIGHT_A}, {'name': UNHELD_RIGHT}]

    enriched = with_right_holders(rights, {RIGHT_A: [USER_GROUP]})

    assert enriched[0][RightHolderKey.GROUPS_COUNT.value] == 1
    assert enriched[0][RightHolderKey.GROUPS.value] == [USER_GROUP]
    assert enriched[1][RightHolderKey.GROUPS_COUNT.value] == 0
    assert enriched[1][RightHolderKey.GROUPS.value] == []


def test_the_count_is_the_length_of_the_list() -> None:
    """The number beside the list and the list cannot disagree - one is derived from the other"""
    enriched = with_right_holders([{'name': RIGHT_B}], {RIGHT_B: [USER_GROUP, ADMIN_GROUP]})

    assert enriched[0][RightHolderKey.GROUPS_COUNT.value] == len(enriched[0][RightHolderKey.GROUPS.value])


def test_the_original_right_keys_survive() -> None:
    """The entry is the serialised right PLUS the two keys, not a replacement for it"""
    enriched = with_right_holders([{'name': RIGHT_A, 'label': 'View type', 'level': 10}], {})

    assert enriched[0]['label'] == 'View type'
    assert enriched[0]['level'] == 10
