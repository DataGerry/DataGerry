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
Unit tests for cmdb.database.updater.versions.updater_20260824

Covers the orphan lookup's query shape, the two cleanup passes (the claimed one delegating to the
shared global-template removal, the orphan one adding the report cleanup the per-type removal does not
do), the template-document deletion's already-gone branch and the orchestration in start_update. The
end-to-end behaviour against a real MongoDB is covered by
tests/integration/database/test_integration_updater_20260824.py, and the metadata contract by the
shared parametrized test in test_version_updaters
"""
from unittest.mock import MagicMock, patch

import pytest

from cmdb.errors.updater import UpdaterException
from cmdb.database.updater.versions.updater_20260824 import (
    RACK_MOUNTING_FIELDS,
    RACK_MOUNTING_TEMPLATE,
    TYPE_SECTION_NAME_PATH,
    Update20260824,
    cleanup_claimed_types,
    cleanup_orphaned_types,
    delete_template_document,
    find_types_with_inlined_section,
)
# -------------------------------------------------------------------------------------------------------------------- #

MODULE_PATH: str = 'cmdb.database.updater.versions.updater_20260824'

DB_NAME: str = 'testdb'
ORPHAN_TYPE_ID: int = 77
SECOND_ORPHAN_TYPE_ID: int = 78


def _manager_with_orphans(*type_ids: int) -> MagicMock:
    """A SectionTemplatesManager stand-in whose type lookup returns the given orphan types"""
    manager = MagicMock()
    manager.types_manager.find_types.return_value = [MagicMock(public_id=type_id) for type_id in type_ids]

    return manager

# -------------------------------------------------------------------------------------------------------------------- #
#                                              constants / lookup shape                                                #
# -------------------------------------------------------------------------------------------------------------------- #

def test_section_path_addresses_the_render_meta_section_name() -> None:
    """The orphan lookup matches on the section name inside render_meta, not on the template claim"""
    assert TYPE_SECTION_NAME_PATH == 'render_meta.sections.name'


def test_the_frozen_field_set_is_the_three_template_fields() -> None:
    """The migration carries the retired template's field names, which no longer exist in the code"""
    assert set(RACK_MOUNTING_FIELDS) == {
        'dg-rackmounting-ru',
        'dg-rackmounting-position',
        'dg-rackmounting-orientation',
    }


def test_find_types_with_inlined_section_queries_by_section_name() -> None:
    """The lookup is by section name so a type that lost its claim is still found"""
    manager = _manager_with_orphans(ORPHAN_TYPE_ID)

    result = find_types_with_inlined_section(manager)

    manager.types_manager.find_types.assert_called_once_with(
        {TYPE_SECTION_NAME_PATH: RACK_MOUNTING_TEMPLATE},
    )
    assert len(result) == 1

# -------------------------------------------------------------------------------------------------------------------- #
#                                                     pass 1                                                           #
# -------------------------------------------------------------------------------------------------------------------- #

def test_cleanup_claimed_types_delegates_to_the_shared_removal() -> None:
    """The claiming types go through the same removal an admin triggers by deleting the template"""
    manager = MagicMock()

    cleanup_claimed_types(manager)

    manager.cleanup_global_section_templates.assert_called_once_with(RACK_MOUNTING_TEMPLATE)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                     pass 2                                                           #
# -------------------------------------------------------------------------------------------------------------------- #

def test_cleanup_orphaned_types_cleans_each_type_and_its_reports() -> None:
    """Each orphan is cleaned per-type and then has its reports stripped against the re-read type"""
    manager = _manager_with_orphans(ORPHAN_TYPE_ID)
    cleaned_type = MagicMock()
    manager.types_manager.get_type_instance.return_value = cleaned_type

    assert cleanup_orphaned_types(manager) == 1

    manager.cleanup_global_section_from_type.assert_called_once_with(ORPHAN_TYPE_ID, RACK_MOUNTING_TEMPLATE)
    manager.cleanup_global_section_reports.assert_called_once_with(cleaned_type, set(RACK_MOUNTING_FIELDS))


def test_cleanup_orphaned_types_handles_every_orphan() -> None:
    """All orphans are processed, not just the first"""
    manager = _manager_with_orphans(ORPHAN_TYPE_ID, SECOND_ORPHAN_TYPE_ID)

    assert cleanup_orphaned_types(manager) == 2
    assert manager.cleanup_global_section_from_type.call_count == 2


def test_cleanup_orphaned_types_is_a_noop_without_orphans() -> None:
    """A database whose types all held the claim needs no second pass"""
    manager = _manager_with_orphans()

    assert cleanup_orphaned_types(manager) == 0
    manager.cleanup_global_section_from_type.assert_not_called()
    manager.cleanup_global_section_reports.assert_not_called()


def test_cleanup_orphaned_types_skips_the_report_pass_for_a_vanished_type() -> None:
    """A type that disappeared between the lookup and the re-read is skipped, not crashed on"""
    manager = _manager_with_orphans(ORPHAN_TYPE_ID)
    manager.types_manager.get_type_instance.return_value = None

    assert cleanup_orphaned_types(manager) == 1
    manager.cleanup_global_section_reports.assert_not_called()

# -------------------------------------------------------------------------------------------------------------------- #
#                                              template-document deletion                                              #
# -------------------------------------------------------------------------------------------------------------------- #

def test_delete_template_document_deletes_an_existing_template() -> None:
    """The document is removed and the deletion reported"""
    dbm = MagicMock()
    dbm.find_one_by.return_value = {'public_id': 1, 'name': RACK_MOUNTING_TEMPLATE}

    assert delete_template_document(dbm, DB_NAME) is True
    dbm.delete.assert_called_once()


def test_delete_template_document_is_a_noop_when_already_gone() -> None:
    """A re-run finds no document and writes nothing - what makes the step idempotent"""
    dbm = MagicMock()
    dbm.find_one_by.return_value = None

    assert delete_template_document(dbm, DB_NAME) is False
    dbm.delete.assert_not_called()

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   start_update                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

def _prepared_updater() -> Update20260824:
    """An updater with its collaborators mocked, bypassing the real __init__"""
    updater = Update20260824.__new__(Update20260824)
    updater.dbm = MagicMock()
    updater.db_name = DB_NAME
    updater.increase_updater_version = MagicMock()

    return updater


def test_start_update_runs_both_passes_then_deletes_and_bumps() -> None:
    """The whole migration: claimed types, orphans, the template document, then the version"""
    updater = _prepared_updater()

    with patch(f'{MODULE_PATH}.SectionTemplatesManager') as manager_cls, \
         patch(f'{MODULE_PATH}.cleanup_claimed_types') as claimed, \
         patch(f'{MODULE_PATH}.cleanup_orphaned_types', return_value=2) as orphaned, \
         patch(f'{MODULE_PATH}.delete_template_document', return_value=True) as delete_doc:
        updater.start_update()

    manager_cls.assert_called_once_with(updater.dbm, DB_NAME)
    claimed.assert_called_once()
    orphaned.assert_called_once()
    delete_doc.assert_called_once_with(updater.dbm, DB_NAME)
    updater.increase_updater_version.assert_called_once_with(20260824)


def test_start_update_bumps_the_version_last() -> None:
    """The version must not be recorded before the work completes, or a crash skips the migration"""
    updater = _prepared_updater()
    order: list[str] = []

    with patch(f'{MODULE_PATH}.SectionTemplatesManager'), \
         patch(f'{MODULE_PATH}.cleanup_claimed_types', side_effect=lambda *_: order.append('claimed')), \
         patch(f'{MODULE_PATH}.cleanup_orphaned_types', side_effect=lambda *_: order.append('orphaned') or 0), \
         patch(f'{MODULE_PATH}.delete_template_document', side_effect=lambda *_: order.append('deleted')):
        updater.increase_updater_version = MagicMock(side_effect=lambda *_: order.append('version'))
        updater.start_update()

    assert order == ['claimed', 'orphaned', 'deleted', 'version']


@pytest.mark.parametrize('failing_step', [
    'cleanup_claimed_types',
    'cleanup_orphaned_types',
    'delete_template_document',
])
def test_start_update_wraps_any_failure(failing_step: str) -> None:
    """A failure in any step surfaces as UpdaterException and leaves the version unbumped"""
    updater = _prepared_updater()

    with patch(f'{MODULE_PATH}.SectionTemplatesManager'), \
         patch(f'{MODULE_PATH}.cleanup_claimed_types'), \
         patch(f'{MODULE_PATH}.cleanup_orphaned_types', return_value=0), \
         patch(f'{MODULE_PATH}.delete_template_document', return_value=False), \
         patch(f'{MODULE_PATH}.{failing_step}', side_effect=RuntimeError('boom')):
        with pytest.raises(UpdaterException):
            updater.start_update()

    updater.increase_updater_version.assert_not_called()
