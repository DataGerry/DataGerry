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
Unit tests for the person / person-group membership helpers

Pure tests: no Mongo. ``sync_membership`` and ``record_delete_cascade`` are the reciprocal write and the delete's undo record:
pinned here are what each writes against what the other side stores, that the inverse is recorded BEFORE the
write, and that the inverse restores exactly the listing that was read
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.framework.write_ledger import WriteLedger
from cmdb.framework.write_ledger_constants import WriteKind
from cmdb.models.person_group_model import PersonReferenceType
from cmdb.manager.person_reference_helper import (
    control_measure_assignment_reference_criteria,
    risk_assessment_reference_criteria,
)
from cmdb.interface.rest_api.routes.user_management_routes.person_membership_helper import (
    listing_ids,
    record_delete_cascade,
    sync_membership,
)
# -------------------------------------------------------------------------------------------------------------------- #

HELPER_PATH: str = 'cmdb.interface.rest_api.routes.user_management_routes.person_membership_helper'
MEMBER_KEY: str = 'group_members'
MEMBER_ID: int = 7
COUNTERPART_COLLECTION: str = 'management.personGroup'


class _Counterpart:
    """
    A counterpart collection kept in memory: which documents list the member

    ``find`` answers the documents whose membership array holds the member; the two bulk writes are patched
    onto ``add`` / ``pull`` so they change that listing, and record what they were asked
    """

    def __init__(self, listing: set[int]) -> None:
        self.listing: set[int] = set(listing)
        self.writes: list[tuple[str, list[int]]] = []
        self.manager = MagicMock()
        self.manager.collection = COUNTERPART_COLLECTION
        self.manager.find.side_effect = lambda criteria: [{'public_id': i} for i in sorted(self.listing)]

    def add(self, _dbm: Any, _db: Any, _collection: Any, _key: Any, _member: Any, ids: list[int]) -> None:
        """The '$addToSet' of the member into the given documents"""
        self.writes.append(('add', ids))
        self.listing |= set(ids)

    def pull(self, _dbm: Any, _db: Any, _collection: Any, _key: Any, _member: Any, ids: list[int]) -> None:
        """The '$pull' of the member out of the given documents"""
        self.writes.append(('pull', ids))
        self.listing -= set(ids)


@pytest.fixture(name='counterpart')
def fixture_counterpart(monkeypatch: pytest.MonkeyPatch) -> _Counterpart:
    """Groups 1 and 2 list the member; the two bulk writes change that listing."""
    side = _Counterpart({1, 2})
    monkeypatch.setattr(f'{HELPER_PATH}.add_member_to_documents', side.add)
    monkeypatch.setattr(f'{HELPER_PATH}.remove_member_from_documents', side.pull)

    return side


class TestListingIds:
    """The counterparts listing a member, read with the membership filter."""

    def test_reads_the_member_filter(self, counterpart: _Counterpart) -> None:
        """One find, on the membership array."""
        assert listing_ids(counterpart.manager, MEMBER_KEY, MEMBER_ID) == {1, 2}
        counterpart.manager.find.assert_called_once_with(criteria={MEMBER_KEY: MEMBER_ID})


class TestSyncMembership:
    """The reciprocal write, computed against what the other side stores."""

    def test_adds_the_missing_and_pulls_the_unselected(self, counterpart: _Counterpart) -> None:
        """Selected {2, 3} against a listing of {1, 2}: add to 3, pull from 1, leave 2 alone."""
        sync_membership(WriteLedger(), counterpart.manager, MEMBER_KEY, MEMBER_ID, [2, 3])

        assert counterpart.writes == [('add', [3]), ('pull', [1])]
        assert counterpart.listing == {2, 3}

    def test_repairs_a_one_sided_membership(self, counterpart: _Counterpart) -> None:
        """
        Group 1 lists the member although the member's own list never had it

        A diff against the member's own list would never pull it; comparing with the stored listing does.
        """
        sync_membership(WriteLedger(), counterpart.manager, MEMBER_KEY, MEMBER_ID, [2])

        assert counterpart.writes == [('pull', [1])]

    def test_writes_and_records_nothing_when_already_in_sync(self, counterpart: _Counterpart) -> None:
        """No write, and nothing for an undo to do."""
        ledger = WriteLedger()

        sync_membership(ledger, counterpart.manager, MEMBER_KEY, MEMBER_ID, {1, 2})

        assert not counterpart.writes
        assert not ledger.entries

    def test_the_inverse_is_recorded_before_the_write(self, counterpart: _Counterpart) -> None:
        """A write that raises part-way is still undone: the entry is already there."""
        ledger = WriteLedger()

        def failing_add(*_args: Any) -> None:
            assert len(ledger.entries) == 1
            raise RuntimeError('boom')

        with pytest.MonkeyPatch.context() as patcher:
            patcher.setattr(f'{HELPER_PATH}.add_member_to_documents', failing_add)

            with pytest.raises(RuntimeError):
                sync_membership(ledger, counterpart.manager, MEMBER_KEY, MEMBER_ID, [3])

        assert ledger.entries[0].kind is WriteKind.COMPENSATED

    def test_the_undo_restores_the_listing_that_was_read(self, counterpart: _Counterpart) -> None:
        """Pulled from what it added, re-added where it pulled - and verified clean."""
        ledger = WriteLedger()
        sync_membership(ledger, counterpart.manager, MEMBER_KEY, MEMBER_ID, [2, 3])

        assert not ledger.undo()
        assert counterpart.listing == {1, 2}
        assert counterpart.writes[2:] == [('add', [1]), ('pull', [3])]

    def test_an_undo_that_does_not_take_is_residue(self, counterpart: _Counterpart) -> None:
        """The verification re-reads the listing, so an inverse that changed nothing is reported."""
        ledger = WriteLedger()
        sync_membership(ledger, counterpart.manager, MEMBER_KEY, MEMBER_ID, [3])
        counterpart.manager.find.side_effect = lambda criteria: [{'public_id': 3}]

        residue = ledger.undo()

        assert [item.kind for item in residue] == [WriteKind.COMPENSATED, WriteKind.COMPENSATED]
        assert {item.collection for item in residue} == {COUNTERPART_COLLECTION}

    def test_the_add_and_the_pull_are_undone_independently(self, counterpart: _Counterpart) -> None:
        """
        The inverse of the pull failing does not stop the add from being taken back

        One step for both would skip the second half of its inverse when the first half raised.
        """
        ledger = WriteLedger()
        sync_membership(ledger, counterpart.manager, MEMBER_KEY, MEMBER_ID, [2, 3])

        def failing_add(*_args: Any) -> None:
            raise RuntimeError('down')

        with pytest.MonkeyPatch.context() as patcher:
            patcher.setattr(f'{HELPER_PATH}.add_member_to_documents', failing_add)
            residue = ledger.undo()

        assert [item.description for item in residue] == [f"member {MEMBER_ID} pulled from the '{MEMBER_KEY}' of [1]"]
        assert 3 not in counterpart.listing


class TestRecordDeleteCascade:
    """Every write of delete_with_follow_up, recorded in the order the cascade makes them."""

    @pytest.mark.parametrize('reference_type', list(PersonReferenceType))
    def test_records_snapshots_membership_and_the_delete(
        self, counterpart: _Counterpart, reference_type: PersonReferenceType,
    ) -> None:
        """Two assessments and one assignment reference the entity; two groups list it."""
        ledger = WriteLedger()
        entity, assessments, assignments = MagicMock(), MagicMock(), MagicMock()
        assessments.find.return_value = [{'public_id': 11}, {'public_id': 12}]
        assignments.find.return_value = [{'public_id': 21}]
        snapshot = {'public_id': MEMBER_ID}

        record_delete_cascade(ledger, entity, counterpart.manager, MEMBER_KEY, snapshot, reference_type,
                              (assessments, assignments))

        assessments.find.assert_called_once_with(
            criteria=risk_assessment_reference_criteria(MEMBER_ID, reference_type)
        )
        assignments.find.assert_called_once_with(
            criteria=control_measure_assignment_reference_criteria(MEMBER_ID, reference_type)
        )
        assert [(entry.kind, entry.public_id) for entry in ledger.entries] == [
            (WriteKind.UPDATE, 11),
            (WriteKind.UPDATE, 12),
            (WriteKind.UPDATE, 21),
            (WriteKind.COMPENSATED, None),
            (WriteKind.DELETE, MEMBER_ID),
        ]
        assert not counterpart.writes

    def test_the_membership_undo_re_adds_the_member(self, counterpart: _Counterpart) -> None:
        """After the cascade pulled the member from groups 1 and 2, the undo puts it back into both."""
        ledger = WriteLedger()
        record_delete_cascade(ledger, MagicMock(), counterpart.manager, MEMBER_KEY, {'public_id': MEMBER_ID},
                              PersonReferenceType.PERSON, (MagicMock(find=MagicMock(return_value=[])),
                                                           MagicMock(find=MagicMock(return_value=[]))))
        counterpart.listing.clear()

        compensated = [entry for entry in ledger.entries if entry.kind is WriteKind.COMPENSATED]
        compensated[0].undo()

        assert counterpart.listing == {1, 2}
        assert compensated[0].verify()

    def test_nothing_listed_records_no_membership_step(self, counterpart: _Counterpart) -> None:
        """A member no counterpart lists has no pull to undo."""
        counterpart.listing.clear()
        ledger = WriteLedger()

        record_delete_cascade(ledger, MagicMock(), counterpart.manager, MEMBER_KEY, {'public_id': MEMBER_ID},
                              PersonReferenceType.PERSON, (MagicMock(find=MagicMock(return_value=[])),
                                                           MagicMock(find=MagicMock(return_value=[]))))

        assert [entry.kind for entry in ledger.entries] == [WriteKind.DELETE]

