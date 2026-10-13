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
Unit tests for cmdb.database.updater.versions.updater_20261013

The migration only reports the stored field patterns the pattern rule refuses, per type and section template; it
writes nothing and asks the live rule. This module owns the literals, the read, the report and the failure tail
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.database.updater.versions import updater_20261013 as module
from cmdb.database.updater.versions.updater_20261013 import Update20261013, stored_pattern_problems
from cmdb.errors.updater import UpdaterException
from cmdb.framework.field_pattern_rule import field_pattern_problem
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.field_key_enum import FieldKey
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20261013
DATABASE_NAME: str = 'cmdb-unit'
TYPE_ID: int = 31
FIELD: str = 'code'
REFUSED: str = r'\p{L}+'


def _build_stubbed_updater(collections: dict[str, list[dict[str, Any]]]) -> Any:
    """The updater with a stubbed database manager answering each collection's documents"""
    updater = Update20261013.__new__(Update20261013)
    updater.dbm = MagicMock()
    updater.dbm.find.side_effect = lambda collection, **_kwargs: iter(collections.get(collection, []))
    updater.db_name = DATABASE_NAME
    updater.increase_updater_version = MagicMock()

    return updater


@pytest.mark.parametrize('frozen, live', [
    (module.TYPE_COLLECTION, CmdbType.COLLECTION),
    (module.SECTION_TEMPLATE_COLLECTION, CmdbSectionTemplate.COLLECTION),
    (module.FIELD_NAME_KEY, FieldKey.NAME.value),
    (module.FIELD_REGEX_KEY, FieldKey.REGEX.value),
], ids=['types', 'templates', 'field-name', 'field-regex'])
def test_a_literal_names_what_the_code_names_today(frozen: Any, live: Any) -> None:
    """Right when it shipped"""
    assert frozen == live


def test_a_document_reports_each_refused_pattern() -> None:
    """In field order; portable and missing patterns pass; junk is skipped"""
    document = {'fields': [{'name': FIELD, 'regex': REFUSED}, {'name': 'ok', 'regex': '[a-z]+'}, {'name': 'none'},
                           'junk', {'name': 'num', 'regex': 5}]}

    assert stored_pattern_problems(document) == [field_pattern_problem(FIELD, REFUSED),
                                                 field_pattern_problem('num', 5)]


def test_a_document_without_fields_reports_nothing() -> None:
    """Never raises"""
    assert not stored_pattern_problems({'fields': None})


def test_both_collections_are_reported_and_nothing_written(caplog: pytest.LogCaptureFixture) -> None:
    """Read with the pattern filter, projected"""
    updater = _build_stubbed_updater({
        CmdbType.COLLECTION: [{'public_id': TYPE_ID, 'name': 'typ', 'fields': [{'name': FIELD, 'regex': REFUSED}]}],
        CmdbSectionTemplate.COLLECTION: [{'public_id': TYPE_ID, 'name': 'tpl',
                                          'fields': [{'name': FIELD, 'regex': '(?i)a'}]}],
    })

    updater.start_update()

    assert "'typ'" in caplog.text and "'tpl'" in caplog.text
    kwargs: dict[str, Any] = updater.dbm.find.call_args.kwargs
    assert kwargs['filter'] == {'fields.regex': {'$exists': True}}
    updater.dbm.update.assert_not_called()
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


def test_a_failed_read_is_wrapped_with_the_error_itself_and_leaves_the_version() -> None:
    """The next start reports again"""
    updater = _build_stubbed_updater({})
    error = RuntimeError('down')
    updater.dbm.find.side_effect = error

    with pytest.raises(UpdaterException) as exc_info:
        updater.start_update()

    assert exc_info.value.__cause__ is error and exc_info.value.args[0] is error
    updater.increase_updater_version.assert_not_called()


def test_the_description_says_it_writes_nothing() -> None:
    """The line the updater log prints"""
    assert 'writes nothing' in Update20261013.__new__(Update20261013).description()
