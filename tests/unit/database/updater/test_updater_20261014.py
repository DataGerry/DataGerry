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
Unit tests for cmdb.database.updater.versions.updater_20261014

The migration renames every relation whose name an older relation holds, then builds the unique name index. Its run
against a real collection is its own integration test; this module owns the frozen literals, the rename plan, the
index branches, the order and the failure tail
"""
from typing import Any
from unittest.mock import MagicMock, call

import pytest

from cmdb.database.updater.versions import updater_20261014 as module
from cmdb.database.updater.versions.updater_20261014 import Update20261014, duplicate_renames
from cmdb.errors.database import DocumentGetError
from cmdb.errors.updater import UpdaterException
from cmdb.models.relation_model import CmdbRelation
from cmdb.models.relation_model.relation_constants import RelationKey
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20261014
DATABASE_NAME: str = 'cmdb-unit'


def _relation(public_id: Any, name: Any) -> dict[str, Any]:
    """A stored relation as the migration reads it."""
    return {RelationKey.PUBLIC_ID.value: public_id, RelationKey.RELATION_NAME.value: name}


def _updater(relations: list[dict[str, Any]] | None = None,
             index_info: dict[str, Any] | None = None) -> tuple[Update20261014, MagicMock]:
    """The migration over a mocked database manager."""
    dbm = MagicMock()
    dbm.find.return_value = iter(relations or [])
    dbm.get_index_info.return_value = index_info or {}

    return Update20261014(dbm, DATABASE_NAME), dbm


class TestFrozenLiterals:
    """The literals still name what the live model declares"""

    def test_the_collection_and_field(self) -> None:
        """The relation collection and its name key"""
        assert (module.RELATION_COLLECTION, module.RELATION_NAME_FIELD, module.PUBLIC_ID_FIELD) == (
            CmdbRelation.COLLECTION, RelationKey.RELATION_NAME.value, RelationKey.PUBLIC_ID.value)

    def test_the_index_is_the_one_the_model_declares(self) -> None:
        """Same name, same key, unique"""
        declared = next(index for index in CmdbRelation.INDEX_KEYS if index['name'] == module.RELATION_NAME_INDEX)

        assert declared['keys'] == [(module.RELATION_NAME_FIELD, CmdbRelation.DAO_ASCENDING)]
        assert declared['unique'] is True

    def test_creation_date(self) -> None:
        """The version this migration bumps to"""
        assert _updater()[0].creation_date() == CREATION_DATE

    def test_description_names_the_relation_name(self) -> None:
        """What the update log shows"""
        assert 'relation' in _updater()[0].description()


class TestDuplicateRenames:
    """duplicate_renames"""

    def test_the_lowest_public_id_keeps_the_name(self) -> None:
        """In any stored order"""
        relations = [_relation(9, 'runs-on'), _relation(3, 'runs-on'), _relation(5, 'runs-on'), _relation(4, 'x')]

        assert duplicate_renames(relations) == [(5, 'runs-on', 'runs-on-5'), (9, 'runs-on', 'runs-on-9')]

    def test_a_taken_new_name_gets_the_id_again(self) -> None:
        """Until it is free"""
        relations = [_relation(1, 'a'), _relation(2, 'a'), _relation(3, 'a-2'), _relation(4, 'a-2-2')]

        assert duplicate_renames(relations) == [(2, 'a', 'a-2-2-2')]

    def test_case_and_spacing_are_different_names(self) -> None:
        """Compared exactly, as the index compares"""
        assert not duplicate_renames([_relation(1, 'Rack'), _relation(2, 'rack'), _relation(3, 'rack ')])

    def test_an_unreadable_document_is_skipped(self) -> None:
        """No string name or no int id"""
        relations = [_relation(1, 'a'), _relation(2, None), _relation('3', 'a'), _relation(4, 5)]

        assert not duplicate_renames(relations)


class TestRenameDuplicates:
    """Update20261014.rename_duplicates"""

    def test_each_rename_is_conditioned_on_the_name_read(self) -> None:
        """One update per duplicate"""
        updater, dbm = _updater([_relation(1, 'a'), _relation(2, 'a')])

        assert updater.rename_duplicates() == [(2, 'a', 'a-2')]
        dbm.update.assert_called_once_with(
            module.RELATION_COLLECTION, DATABASE_NAME,
            {module.PUBLIC_ID_FIELD: 2, module.RELATION_NAME_FIELD: 'a'}, {module.RELATION_NAME_FIELD: 'a-2'})


class TestBuildUniqueNameIndex:
    """Update20261014.build_unique_name_index"""

    def test_a_missing_index_is_built(self) -> None:
        """Unique, on the name"""
        updater, dbm = _updater()

        assert updater.build_unique_name_index() is True
        (index,) = dbm.create_indexes.call_args.args[2]
        assert index.document == {'key': {module.RELATION_NAME_FIELD: 1}, 'name': module.RELATION_NAME_INDEX,
                                  'unique': True}
        dbm.drop_index.assert_not_called()

    def test_a_unique_index_is_left_alone(self) -> None:
        """Re-run safe"""
        updater, dbm = _updater(index_info={module.RELATION_NAME_INDEX: {module.INDEX_UNIQUE_KEY: True}})

        assert updater.build_unique_name_index() is False
        dbm.create_indexes.assert_not_called()

    def test_a_non_unique_index_of_that_name_is_rebuilt(self) -> None:
        """Dropped first"""
        updater, dbm = _updater(index_info={module.RELATION_NAME_INDEX: {}})

        assert updater.build_unique_name_index() is True
        dbm.drop_index.assert_called_once_with(module.RELATION_COLLECTION, DATABASE_NAME, module.RELATION_NAME_INDEX)


class TestStartUpdate:
    """Update20261014.start_update"""

    def test_renames_then_builds_then_bumps(self) -> None:
        """The index cannot be built over a duplicate"""
        updater, dbm = _updater([_relation(1, 'a'), _relation(2, 'a')])
        updater.increase_updater_version = MagicMock()
        order = MagicMock()
        order.attach_mock(dbm.update, 'update')
        order.attach_mock(dbm.create_indexes, 'create_indexes')
        order.attach_mock(updater.increase_updater_version, 'bump')

        updater.start_update()

        assert [entry[0] for entry in order.mock_calls] == ['update', 'create_indexes', 'bump']
        assert order.mock_calls[-1] == call.bump(CREATION_DATE)

    def test_a_failure_is_wrapped_with_the_exception(self) -> None:
        """The exception itself, not its text; the version is not bumped"""
        updater, dbm = _updater()
        failure = DocumentGetError('read failed')
        dbm.find.side_effect = failure
        updater.increase_updater_version = MagicMock()

        with pytest.raises(UpdaterException) as caught:
            updater.start_update()

        assert caught.value.args[0] is failure and caught.value.__cause__ is failure
        updater.increase_updater_version.assert_not_called()
