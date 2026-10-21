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
Unit tests for cmdb.database.updater.versions.updater_20261008

The migration grants the fixed ``user`` group the two relation view rights and copies each object's live type onto
every stored CmdbObjectRelation. Its run against real collections is its own integration test; this module owns
the frozen literals (they must still name what the live code names), the shape of the grant and of the re-stamp
pipeline, and the failure tail: the wrapper carries the error itself and a failed run leaves the version alone
"""
# pylint: disable=no-member  # the database manager is a MagicMock, so update_many_raw / aggregate carry call_args
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.database.database_services.database_updater import DatabaseUpdater
from cmdb.database.updater.versions import updater_20261008 as module
from cmdb.database.updater.versions.updater_20261008 import Update20261008, build_type_restamp_pipeline
from cmdb.errors.updater import UpdaterException
from cmdb.interface.rest_api.routes.relation_routes.relation_constants import ObjectRelationRight, RelationRight
from cmdb.models.group_model import CmdbUserGroup, GroupKey
from cmdb.models.group_model.group_constants import USER_GROUP_ID
from cmdb.models.object_model import CmdbObject
from cmdb.models.object_relation_model import CmdbObjectRelation, ObjectRelationKey
from cmdb.models.right_model.all_rights import ALL_RIGHTS, flat_rights_tree
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20261008
DATABASE_NAME: str = 'cmdb-unit'


def _build_stubbed_updater() -> Any:
    """The updater with a stubbed database manager, bypassing the base class's wiring"""
    updater = Update20261008.__new__(Update20261008)
    updater.dbm = MagicMock()
    updater.dbm.aggregate.return_value = iter([])
    updater.db_name = DATABASE_NAME
    updater.increase_updater_version = MagicMock()

    return updater

# ------------------------------------------------- frozen literals -------------------------------------------------- #

@pytest.mark.parametrize('frozen, live', [
    (module.GROUP_COLLECTION, CmdbUserGroup.COLLECTION),
    (module.OBJECT_COLLECTION, CmdbObject.COLLECTION),
    (module.OBJECT_RELATION_COLLECTION, CmdbObjectRelation.COLLECTION),
    (module.RIGHTS_FIELD, GroupKey.RIGHTS.value),
    (module.USER_GROUP_ID, USER_GROUP_ID),
    (module.PARENT_ID_FIELD, ObjectRelationKey.RELATION_PARENT_ID.value),
    (module.CHILD_ID_FIELD, ObjectRelationKey.RELATION_CHILD_ID.value),
    (module.PARENT_TYPE_FIELD, ObjectRelationKey.RELATION_PARENT_TYPE_ID.value),
    (module.CHILD_TYPE_FIELD, ObjectRelationKey.RELATION_CHILD_TYPE_ID.value),
], ids=['groups', 'objects', 'relations', 'rights', 'user-group', 'parent', 'child', 'parent-type', 'child-type'])
def test_a_frozen_literal_names_what_the_code_names_today(frozen: Any, live: Any) -> None:
    """Frozen on purpose - and right when it shipped"""
    assert frozen == live


def test_the_granted_rights_are_the_two_view_rights_of_the_tree() -> None:
    """A misspelt right would grant nothing"""
    assert module.GRANTED_RIGHTS == [RelationRight.VIEW.value, ObjectRelationRight.VIEW.value]
    assert set(module.GRANTED_RIGHTS) <= {right.name for right in flat_rights_tree(ALL_RIGHTS)}

# ----------------------------------------------------- the run ------------------------------------------------------ #

def test_grants_both_rights_to_the_fixed_group_only() -> None:
    """$addToSet, so a right already held is not added twice; a rights value that is no list is not touched"""
    updater = _build_stubbed_updater()

    updater.start_update()

    kwargs: dict[str, Any] = updater.dbm.update_many_raw.call_args.kwargs
    assert kwargs['collection'] == CmdbUserGroup.COLLECTION
    assert kwargs['filter_query'] == {'public_id': USER_GROUP_ID, GroupKey.RIGHTS.value: {'$type': 'array'}}
    assert kwargs['update'] == {'$addToSet': {GroupKey.RIGHTS.value: {'$each': module.GRANTED_RIGHTS}}}


def test_runs_the_restamp_over_the_object_relations_and_bumps_the_version() -> None:
    """The $merge pipeline is consumed before the version moves"""
    updater = _build_stubbed_updater()

    updater.start_update()

    assert updater.dbm.aggregate.call_args.args == (
        CmdbObjectRelation.COLLECTION, DATABASE_NAME, build_type_restamp_pipeline(),
    )
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


@pytest.mark.parametrize('failing', ['update_many_raw', 'aggregate'])
def test_a_failed_step_is_wrapped_with_the_error_itself_and_leaves_the_version(failing: str) -> None:
    """The next start runs the whole migration again"""
    updater = _build_stubbed_updater()
    error = RuntimeError('down')
    getattr(updater.dbm, failing).side_effect = error

    with pytest.raises(UpdaterException) as exc_info:
        updater.start_update()

    assert exc_info.value.__cause__ is error
    updater.increase_updater_version.assert_not_called()

# --------------------------------------------------- the pipeline --------------------------------------------------- #

class TestTheRestampPipeline:
    """Join both objects, keep a gone object's stored type, write back only what differs"""

    def test_stage_order(self) -> None:
        """Two joins, the live types, the difference, the write-back"""
        assert [next(iter(stage)) for stage in build_type_restamp_pipeline()] == [
            '$lookup', '$lookup', '$addFields', '$match', '$project', '$merge',
        ]

    @pytest.mark.parametrize('index, local_field', [
        (0, ObjectRelationKey.RELATION_PARENT_ID.value), (1, ObjectRelationKey.RELATION_CHILD_ID.value),
    ], ids=['parent', 'child'])
    def test_each_end_joins_its_object_by_public_id(self, index: int, local_field: str) -> None:
        """At most one object, and only its type"""
        lookup: dict[str, Any] = build_type_restamp_pipeline()[index]['$lookup']

        assert (lookup['from'], lookup['localField'], lookup['foreignField']) == (
            CmdbObject.COLLECTION, local_field, 'public_id',
        )
        assert lookup['pipeline'] == [{'$limit': 1}, {'$project': {'_id': 0, 'type_id': 1}}]

    def test_a_gone_object_keeps_the_stored_type(self) -> None:
        """$ifNull falls back to what the relation holds"""
        live_types: dict[str, Any] = build_type_restamp_pipeline()[2]['$addFields']

        assert live_types[module.LIVE_PARENT_TYPE_FIELD]['$ifNull'][1] == f'${module.PARENT_TYPE_FIELD}'
        assert live_types[module.LIVE_CHILD_TYPE_FIELD]['$ifNull'][1] == f'${module.CHILD_TYPE_FIELD}'

    def test_writes_back_only_the_two_types_onto_existing_relations(self) -> None:
        """Nothing else of a relation changes, and no relation is created"""
        pipeline = build_type_restamp_pipeline()

        assert set(pipeline[4]['$project']) == {'_id', module.PARENT_TYPE_FIELD, module.CHILD_TYPE_FIELD}
        assert pipeline[5]['$merge'] == {
            'into': CmdbObjectRelation.COLLECTION, 'on': '_id', 'whenMatched': 'merge', 'whenNotMatched': 'discard',
        }


def test_creation_date_is_registered() -> None:
    """The updater only runs what the registry lists"""
    assert Update20261008.__new__(Update20261008).creation_date() == CREATION_DATE
    assert CREATION_DATE in DatabaseUpdater.__UPDATE_VERSIONS__


def test_description_names_both_halves() -> None:
    """The rights and the re-stamp"""
    description: str = Update20261008.__new__(Update20261008).description()

    assert 'rights' in description and 're-stamps' in description
