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
Unit tests for cmdb.framework.object_edit

DB-free: the ObjectsManager is a MagicMock whose ``find_objects`` answers the read-back. Covers the
version bump (``compute_object_version``), the plan built before a write (``plan_object_edit``), the
edit stamp, the read-back that pairs each written object with its plan (``load_object_writes``) and
the best-effort hand-over to a callback (``hand_over_object_writes``) - including that a failed
read-back is logged under the lost-entry marker and never raised
"""
import logging
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.models.log_model.object_log_constants import OBJECT_LOG_LOST_MARKER
from cmdb.models.object_model import CmdbObjectKey, CmdbObjectFieldKey
from cmdb.models.object_model.cmdb_object import CmdbObject
from cmdb.framework.object_edit import (
    ObjectWrite,
    PlannedEdit,
    build_edit_stamp,
    compute_object_version,
    hand_over_object_writes,
    load_object_writes,
    plan_object_edit,
)
# -------------------------------------------------------------------------------------------------------------------- #

OBJECT_ID: int = 10
OTHER_OBJECT_ID: int = 11
AUTHOR_ID: int = 1
EDITOR_ID: int = 5
START_VERSION: str = '1.0.0'
PATCHED_VERSION: str = '1.0.1'
EDIT_TIME: datetime = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def _field(name: str, value: Any) -> dict[str, Any]:
    """One flat field entry."""
    return {CmdbObjectFieldKey.NAME.value: name, CmdbObjectFieldKey.VALUE.value: value}


def _doc(public_id: int = OBJECT_ID, value: Any = 'a', version: str = START_VERSION) -> dict[str, Any]:
    """A readable CmdbObject document with two flat fields, the first holding ``value``."""
    return {
        CmdbObjectKey.PUBLIC_ID.value: public_id,
        CmdbObjectKey.TYPE_ID.value: 1,
        CmdbObjectKey.AUTHOR_ID.value: AUTHOR_ID,
        CmdbObjectKey.VERSION.value: version,
        CmdbObjectKey.FIELDS.value: [_field('first', value), _field('second', 'b')],
    }


def _make_object(fields: list[dict[str, Any]]) -> CmdbObject:
    """A minimal CmdbObject carrying ``fields``."""
    return CmdbObject(
        public_id=OBJECT_ID, type_id=1, version=START_VERSION, creation_time=EDIT_TIME, author_id=AUTHOR_ID,
        active=True, fields=fields,
    )


def _plan(public_id: int = OBJECT_ID) -> PlannedEdit:
    """The plan of changing the first field of a fresh document."""
    return plan_object_edit(_doc(public_id), _doc(public_id, value='changed'))


# -------------------------------------------------------------------------------------------------------------------- #
#                                               compute_object_version                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestComputeObjectVersion:
    """compute_object_version picks the version bump from the field-level diff size."""

    @pytest.mark.parametrize('field_count,changed_count,expected_attr', [
        (3, 1, 'VERSIONING_PATCH'),   # a single changed field is a patch
        (3, 3, 'VERSIONING_MAJOR'),   # all fields changed is a major
        (4, 3, 'VERSIONING_MINOR'),   # more than half (but not all) is a minor
        (4, 2, 'VERSIONING_PATCH'),   # not >half, not all, not one -> patch
        (0, 0, 'VERSIONING_MAJOR'),   # no fields at all: "every field changed", however little did
    ])
    def test_bump_selection(self, field_count: int, changed_count: int, expected_attr: str) -> None:
        """The correct VERSIONING_* constant is passed to update_version for each diff size."""
        base_fields = [{'name': f'f{i}', 'value': i} for i in range(field_count)]
        current = _make_object(base_fields)

        updated_fields = [dict(field) for field in base_fields]
        for i in range(changed_count):
            updated_fields[i] = {'name': f'f{i}', 'value': 1000 + i}
        updated = _make_object(updated_fields)

        updated.update_version = MagicMock(return_value='bumped')

        new_version, changes = compute_object_version(current, updated)

        assert new_version == 'bumped'
        assert len(changes['new']) == changed_count
        updated.update_version.assert_called_once_with(getattr(CmdbObject, expected_attr))

    def test_the_updated_object_carries_the_new_version(self) -> None:
        """The bump is written onto the updated object, so a log reading it off agrees with the document."""
        current = _make_object([_field('first', 'a'), _field('second', 'b')])
        updated = _make_object([_field('first', 'changed'), _field('second', 'b')])

        new_version, _ = compute_object_version(current, updated)

        assert new_version == PATCHED_VERSION
        assert updated.version == PATCHED_VERSION


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  plan_object_edit                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_plan_object_edit_records_before_version_and_diff() -> None:
    """The plan holds the object as it was, the bumped version and the changed entry both ways."""
    plan = _plan()

    assert plan.before.version == START_VERSION
    assert plan.version == PATCHED_VERSION
    assert plan.changes == {'old': [_field('first', 'a')], 'new': [_field('first', 'changed')]}


def test_plan_object_edit_leaves_the_callers_documents_as_they_were() -> None:
    """Reading a document into a CmdbObject normalises it in place - the plan must work on copies."""
    before, after = _doc(), _doc(value='changed')
    before_copy, after_copy = dict(before), dict(after)

    plan_object_edit(before, after)

    assert before == before_copy
    assert after == after_copy


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  build_edit_stamp                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_edit_stamp_credits_the_user_at_the_given_time() -> None:
    """Both keys, with the user's public_id."""
    stamp = build_edit_stamp(MagicMock(public_id=EDITOR_ID), EDIT_TIME)

    assert stamp == {CmdbObjectKey.LAST_EDIT_TIME.value: EDIT_TIME, CmdbObjectKey.EDITOR_ID.value: EDITOR_ID}


def test_build_edit_stamp_without_a_user_stamps_only_the_time() -> None:
    """An internal caller has nobody to credit, so editor_id is left as it is."""
    stamp = build_edit_stamp(None, EDIT_TIME)

    assert stamp == {CmdbObjectKey.LAST_EDIT_TIME.value: EDIT_TIME}


def test_build_edit_stamp_defaults_to_now_in_utc() -> None:
    """Without a time, the stamp is taken now - timezone-aware, like every other write."""
    stamp = build_edit_stamp(None)

    assert stamp[CmdbObjectKey.LAST_EDIT_TIME.value].tzinfo is not None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  load_object_writes                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_load_object_writes_reads_every_planned_object_in_one_query() -> None:
    """One $in over the planned ids, not a read per object."""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []

    load_object_writes(objects_manager, {OBJECT_ID: _plan(), OTHER_OBJECT_ID: _plan(OTHER_OBJECT_ID)})

    objects_manager.find_objects.assert_called_once_with(
        {CmdbObjectKey.PUBLIC_ID.value: {'$in': [OBJECT_ID, OTHER_OBJECT_ID]}}, as_dict=True,
    )


def test_load_object_writes_pairs_each_read_back_object_with_its_plan() -> None:
    """before and changes come from the plan, after from the read-back."""
    plan = _plan()
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [_doc(value='changed', version=PATCHED_VERSION)]

    writes = load_object_writes(objects_manager, {OBJECT_ID: plan})

    assert writes == [ObjectWrite(plan.before, writes[0].after, plan.changes)]
    assert writes[0].after.version == PATCHED_VERSION


def test_load_object_writes_leaves_out_an_object_that_is_gone() -> None:
    """An object deleted between the write and the read-back has nothing to log."""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [_doc(OTHER_OBJECT_ID)]

    writes = load_object_writes(objects_manager, {OBJECT_ID: _plan(), OTHER_OBJECT_ID: _plan(OTHER_OBJECT_ID)})

    assert [write.before.get_public_id() for write in writes] == [OTHER_OBJECT_ID]


def test_load_object_writes_leaves_out_what_the_check_rejects() -> None:
    """A batch write that skipped some targets passes the check that tells its own edits apart."""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [_doc(OBJECT_ID), _doc(OTHER_OBJECT_ID)]

    writes = load_object_writes(
        objects_manager, {OBJECT_ID: _plan(), OTHER_OBJECT_ID: _plan(OTHER_OBJECT_ID)},
        is_written=lambda doc, plan: doc[CmdbObjectKey.PUBLIC_ID.value] == OBJECT_ID,
    )

    assert [write.before.get_public_id() for write in writes] == [OBJECT_ID]


def test_load_object_writes_without_plans_reads_nothing() -> None:
    """Nothing written, nothing to read."""
    objects_manager = MagicMock()

    assert not load_object_writes(objects_manager, {})
    objects_manager.find_objects.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                               hand_over_object_writes                                                #
# -------------------------------------------------------------------------------------------------------------------- #
def test_hand_over_object_writes_passes_every_write_to_the_callback() -> None:
    """Each written object reaches the callback once."""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [_doc(OBJECT_ID), _doc(OTHER_OBJECT_ID)]
    on_write = MagicMock()

    hand_over_object_writes(objects_manager, {OBJECT_ID: _plan(), OTHER_OBJECT_ID: _plan(OTHER_OBJECT_ID)}, on_write)

    assert on_write.call_count == 2


def test_hand_over_object_writes_without_a_callback_reads_nothing() -> None:
    """No callback, no read-back query."""
    objects_manager = MagicMock()

    hand_over_object_writes(objects_manager, {OBJECT_ID: _plan()}, None)

    objects_manager.find_objects.assert_not_called()


def test_a_failed_read_back_is_logged_per_object_and_never_raised(caplog: pytest.LogCaptureFixture) -> None:
    """The objects are already stored, so a failed read-back reports each lost entry and moves on."""
    objects_manager = MagicMock()
    objects_manager.find_objects.side_effect = RuntimeError('database gone')
    on_write = MagicMock()

    with caplog.at_level(logging.ERROR):
        hand_over_object_writes(
            objects_manager, {OBJECT_ID: _plan(), OTHER_OBJECT_ID: _plan(OTHER_OBJECT_ID)}, on_write,
        )

    on_write.assert_not_called()
    assert caplog.text.count(OBJECT_LOG_LOST_MARKER) == 2
    assert f'{OBJECT_LOG_LOST_MARKER} action=EDIT object_id={OBJECT_ID}' in caplog.text
