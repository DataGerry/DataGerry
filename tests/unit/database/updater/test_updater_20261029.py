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
Unit tests for cmdb.database.updater.versions.updater_20261029

The migration renames every section template whose name its keeper holds - a predefined template of the name, else
the lowest public_id - logs the types claiming the name, then builds the unique name index. Its run against a real
collection is its own integration test; this module owns the frozen literals, the rename plan, the log, the index
branches, the order and the failure tail
"""
import logging
from typing import Any
from unittest.mock import MagicMock, call

import pytest

from cmdb.database.updater.versions import updater_20261029 as module
from cmdb.database.updater.versions.updater_20261029 import Update20261029, duplicate_renames
from cmdb.errors.database import DocumentGetError
from cmdb.errors.updater import UpdaterException
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.section_template_model.section_template_constants import SectionTemplateKey
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20261029
DATABASE_NAME: str = 'cmdb-unit'
CLAIMING_TYPE_IDS: list[int] = [7, 3]


def _template(public_id: Any, name: Any, predefined: Any = False) -> dict[str, Any]:
    """A stored template as the migration reads it."""
    return {SectionTemplateKey.PUBLIC_ID.value: public_id, SectionTemplateKey.NAME.value: name,
            SectionTemplateKey.PREDEFINED.value: predefined}


def _updater(templates: list[dict[str, Any]] | None = None, index_info: dict[str, Any] | None = None,
             claiming: list[int] | None = None) -> tuple[Update20261029, MagicMock]:
    """The migration over a mocked database manager; types claiming any name are ``claiming``"""
    dbm = MagicMock()

    def _find(collection: str, *_args: Any, **_kwargs: Any) -> Any:
        if collection == module.TYPE_COLLECTION:
            return iter([{module.PUBLIC_ID_FIELD: type_id} for type_id in claiming or []])
        return iter(templates or [])

    dbm.find.side_effect = _find
    dbm.get_index_info.return_value = index_info or {}

    return Update20261029(dbm, DATABASE_NAME), dbm


class TestFrozenLiterals:
    """The literals still name what the live models declare"""

    def test_the_collections_and_fields(self) -> None:
        """The template collection, its keys, and the type collection with its claim key"""
        assert (module.SECTION_TEMPLATE_COLLECTION, module.NAME_FIELD, module.PREDEFINED_FIELD,
                module.PUBLIC_ID_FIELD) == (
            CmdbSectionTemplate.COLLECTION, SectionTemplateKey.NAME.value, SectionTemplateKey.PREDEFINED.value,
            SectionTemplateKey.PUBLIC_ID.value)
        assert (module.TYPE_COLLECTION, module.GLOBAL_TEMPLATE_IDS_FIELD) == (
            CmdbType.COLLECTION, TypeSchemaKey.GLOBAL_TEMPLATE_IDS.value)

    def test_the_index_is_the_one_the_model_declares(self) -> None:
        """Same name, same key, unique"""
        declared = next(index for index in CmdbSectionTemplate.INDEX_KEYS if index['name'] == module.NAME_INDEX)

        assert declared['keys'] == [(module.NAME_FIELD, CmdbSectionTemplate.DAO_ASCENDING)]
        assert declared['unique'] is True

    def test_creation_date(self) -> None:
        """The version this migration bumps to"""
        assert _updater()[0].creation_date() == CREATION_DATE

    def test_description_names_the_section_template(self) -> None:
        """What the update log shows"""
        assert 'section template' in _updater()[0].description()


class TestDuplicateRenames:
    """duplicate_renames"""

    def test_the_lowest_public_id_keeps_the_name(self) -> None:
        """In any stored order"""
        templates = [_template(9, 'net'), _template(3, 'net'), _template(5, 'net'), _template(4, 'x')]

        assert duplicate_renames(templates) == [(5, 'net', 'net-5'), (9, 'net', 'net-9')]

    def test_a_predefined_template_keeps_the_name_over_a_lower_id(self) -> None:
        """The seeding and the predefined guards find it by the name"""
        templates = [_template(2, 'dg-net'), _template(8, 'dg-net', predefined=True)]

        assert duplicate_renames(templates) == [(2, 'dg-net', 'dg-net-2')]

    def test_only_a_true_predefined_flag_counts(self) -> None:
        """A truthy non-boolean is not predefined"""
        templates = [_template(2, 'n'), _template(8, 'n', predefined='yes')]

        assert duplicate_renames(templates) == [(8, 'n', 'n-8')]

    def test_a_taken_new_name_gets_the_id_again(self) -> None:
        """Until it is free"""
        templates = [_template(1, 'a'), _template(2, 'a'), _template(3, 'a-2'), _template(4, 'a-2-2')]

        assert duplicate_renames(templates) == [(2, 'a', 'a-2-2-2')]

    def test_case_and_spacing_are_different_names(self) -> None:
        """Compared exactly, as the index compares"""
        assert not duplicate_renames([_template(1, 'Net'), _template(2, 'net'), _template(3, 'net ')])

    def test_an_unreadable_document_is_skipped(self) -> None:
        """No string name or no int id"""
        templates = [_template(1, 'a'), _template(2, None), _template('3', 'a'), _template(4, 5)]

        assert not duplicate_renames(templates)

    def test_no_duplicates_no_renames(self) -> None:
        """What a re-run plans"""
        assert not duplicate_renames([_template(1, 'a'), _template(2, 'a-2')])


class TestRenameDuplicates:
    """Update20261029.rename_duplicates"""

    def test_each_rename_is_conditioned_on_the_name_read(self) -> None:
        """One update per duplicate"""
        updater, dbm = _updater([_template(1, 'a'), _template(2, 'a')])

        assert updater.rename_duplicates() == [(2, 'a', 'a-2')]
        dbm.update.assert_called_once_with(
            module.SECTION_TEMPLATE_COLLECTION, DATABASE_NAME,
            {module.PUBLIC_ID_FIELD: 2, module.NAME_FIELD: 'a'}, {module.NAME_FIELD: 'a-2'})

    def test_the_rename_is_logged_with_the_claiming_types(self, caplog: pytest.LogCaptureFixture) -> None:
        """For an administrator to check their section"""
        updater, _dbm = _updater([_template(1, 'a'), _template(2, 'a')], claiming=CLAIMING_TYPE_IDS)

        with caplog.at_level(logging.WARNING, logger=module.LOGGER.name):
            updater.rename_duplicates()

        (record,) = caplog.records
        assert "'a-2'" in record.getMessage() and str(sorted(CLAIMING_TYPE_IDS)) in record.getMessage()

    def test_nothing_is_written_without_a_duplicate(self) -> None:
        """Neither templates nor types"""
        updater, dbm = _updater([_template(1, 'a')])

        assert not updater.rename_duplicates()
        dbm.update.assert_not_called()


class TestClaimingTypeIds:
    """Update20261029.claiming_type_ids"""

    def test_the_ids_sorted_from_a_projected_query_on_the_claim(self) -> None:
        """Only the ids are read"""
        updater, dbm = _updater(claiming=CLAIMING_TYPE_IDS)

        assert updater.claiming_type_ids('a') == sorted(CLAIMING_TYPE_IDS)
        dbm.find.assert_called_once_with(
            module.TYPE_COLLECTION, DATABASE_NAME, filter={module.GLOBAL_TEMPLATE_IDS_FIELD: 'a'},
            projection={module.PUBLIC_ID_FIELD: 1, module.MONGO_ID_FIELD: 0})


class TestBuildUniqueNameIndex:
    """Update20261029.build_unique_name_index"""

    def test_a_missing_index_is_built(self) -> None:
        """Unique, on the name"""
        updater, dbm = _updater()

        assert updater.build_unique_name_index() is True
        (index,) = dbm.create_indexes.call_args.args[2]
        assert index.document == {'key': {module.NAME_FIELD: 1}, 'name': module.NAME_INDEX, 'unique': True}
        dbm.drop_index.assert_not_called()

    def test_a_unique_index_is_left_alone(self) -> None:
        """Re-run safe"""
        updater, dbm = _updater(index_info={module.NAME_INDEX: {module.INDEX_UNIQUE_KEY: True}})

        assert updater.build_unique_name_index() is False
        dbm.create_indexes.assert_not_called()

    def test_a_non_unique_index_of_that_name_is_rebuilt(self) -> None:
        """Dropped first"""
        updater, dbm = _updater(index_info={module.NAME_INDEX: {}})

        assert updater.build_unique_name_index() is True
        dbm.drop_index.assert_called_once_with(module.SECTION_TEMPLATE_COLLECTION, DATABASE_NAME, module.NAME_INDEX)


class TestStartUpdate:
    """Update20261029.start_update"""

    def test_renames_then_builds_then_bumps(self) -> None:
        """The index cannot be built over a duplicate"""
        updater, dbm = _updater([_template(1, 'a'), _template(2, 'a')])
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
