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
Reference guards shared by the CmdbPerson and CmdbPersonGroup routes

Both sides of the person / person-group membership are written by the client as a list of public_ids -
a person names their groups, a group names its members. Stored without asking whether those ids
exist, an unknown id would be accepted silently: the document would keep it, the reciprocal
``$addToSet`` would match no document, and the two sides of the membership would disagree from that
moment on, with nothing in the response to say so.

``routes_helper.abort_on_unknown_references`` is the guard both routes run before writing: one projected
``$in`` query, answered with a 400 naming the ids it could not find

``sync_membership`` is the reciprocal write itself, for both sides and every write route: it makes the
counterparts' membership match the selection (added where missing, pulled where no longer selected), so it also
repairs a drift left by an earlier failure, and records its own inverse in the request's WriteLedger.
``record_delete_cascade`` records, before ``delete_with_follow_up`` runs, the inverse of every write of the delete
cascade: the ISMS documents it changes (snapshots), the counterparts it pulls the member from, and the document
itself - so a delete that fails part-way leaves everything as it was
"""
from logging import Logger, getLogger
from typing import Any, Iterable

from cmdb.framework.write_ledger import WriteLedger
from cmdb.manager.generic_manager import GenericManager
from cmdb.manager.person_reference_helper import (
    add_member_to_documents,
    control_measure_assignment_reference_criteria,
    remove_member_from_documents,
    risk_assessment_reference_criteria,
)
from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType
from cmdb.models.cmdb_dao import CmdbDAO
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

__all__: list[str] = [
    'listing_ids',
    'record_delete_cascade',
    'sync_membership',
]


def listing_ids(counterpart_manager: GenericManager, member_key: str, member_id: int) -> set[int]:
    """
    The counterparts whose membership array lists one member

    Args:
        counterpart_manager (GenericManager): The manager of the other side (persons for a group, groups for a
            person)
        member_key (str): The counterparts' membership array (``groups`` / ``group_members``)
        member_id (int): public_id of the member

    Returns:
        set[int]: public_ids of every counterpart listing it
    """
    return {
        document[CmdbDAO.PUBLIC_ID_KEY]
        for document in counterpart_manager.find(criteria={member_key: member_id})
    }


def _add_member(counterpart_manager: GenericManager, member_key: str, member_id: int, ids: Iterable[int]) -> None:
    """
    Adds a member to the given counterparts in one bulk write

    Args:
        counterpart_manager (GenericManager): The manager of the other side
        member_key (str): The counterparts' membership array
        member_id (int): public_id of the member
        ids (Iterable[int]): Counterparts that must list it
    """
    add_member_to_documents(counterpart_manager.dbm, counterpart_manager.db_name, counterpart_manager.collection,
                            member_key, member_id, sorted(ids))


def _pull_member(counterpart_manager: GenericManager, member_key: str, member_id: int, ids: Iterable[int]) -> None:
    """
    Pulls a member out of the given counterparts in one bulk write - nothing at all for an empty selection

    Args:
        counterpart_manager (GenericManager): The manager of the other side
        member_key (str): The counterparts' membership array
        member_id (int): public_id of the member
        ids (Iterable[int]): Counterparts that must not list it
    """
    remove_member_from_documents(counterpart_manager.dbm, counterpart_manager.db_name, counterpart_manager.collection,
                                 member_key, member_id, sorted(ids))


def _record_add(
        ledger: WriteLedger,
        counterpart_manager: GenericManager,
        member_key: str,
        member_id: int,
        ids: set[int]) -> None:
    """
    Records the inverse of adding a member to counterparts that did not list it: pull it out of exactly those

    Args:
        ledger (WriteLedger): The request's ledger
        counterpart_manager (GenericManager): The manager of the other side
        member_key (str): The counterparts' membership array
        member_id (int): public_id of the member
        ids (set[int]): The counterparts being added to, none of which lists the member yet
    """
    ledger.compensated(
        counterpart_manager.collection,
        f"member {member_id} added to the '{member_key}' of {sorted(ids)}",
        undo=lambda: _pull_member(counterpart_manager, member_key, member_id, ids),
        verify=lambda: not listing_ids(counterpart_manager, member_key, member_id) & ids,
    )


def _record_pull(
        ledger: WriteLedger,
        counterpart_manager: GenericManager,
        member_key: str,
        member_id: int,
        ids: set[int]) -> None:
    """
    Records the inverse of pulling a member out of counterparts that listed it: add it back to exactly those

    Args:
        ledger (WriteLedger): The request's ledger
        counterpart_manager (GenericManager): The manager of the other side
        member_key (str): The counterparts' membership array
        member_id (int): public_id of the member
        ids (set[int]): The counterparts being pulled from, all of which list the member
    """
    ledger.compensated(
        counterpart_manager.collection,
        f"member {member_id} pulled from the '{member_key}' of {sorted(ids)}",
        undo=lambda: _add_member(counterpart_manager, member_key, member_id, ids),
        verify=lambda: ids <= listing_ids(counterpart_manager, member_key, member_id),
    )


def sync_membership(
        ledger: WriteLedger,
        counterpart_manager: GenericManager,
        member_key: str,
        member_id: int,
        selected_ids: Iterable[int]) -> None:
    """
    Makes the other side's membership match a member's selection, and records the inverse in the ledger

    The counterparts listing the member are read once; the member is then added to every selected counterpart
    that lacks it and pulled from every counterpart that lists it without being selected. Computed against what
    the other side actually stores - not against the member's own previous list - so a drift an earlier failure
    left behind is repaired by the next save. The add and the pull are recorded as two steps, each before its
    write, so each is undone - and verified - on its own

    Args:
        ledger (WriteLedger): The request's ledger
        counterpart_manager (GenericManager): The manager of the other side
        member_key (str): The counterparts' membership array (``groups`` / ``group_members``)
        member_id (int): public_id of the member whose selection is written
        selected_ids (Iterable[int]): The counterparts the member now belongs to
    """
    selected: set[int] = set(selected_ids)
    listed_before: set[int] = listing_ids(counterpart_manager, member_key, member_id)
    to_add: set[int] = selected - listed_before
    to_pull: set[int] = listed_before - selected

    if to_add:
        _record_add(ledger, counterpart_manager, member_key, member_id, to_add)
        _add_member(counterpart_manager, member_key, member_id, to_add)

    if to_pull:
        _record_pull(ledger, counterpart_manager, member_key, member_id, to_pull)
        _pull_member(counterpart_manager, member_key, member_id, to_pull)


def _record_membership_removal(
        ledger: WriteLedger,
        counterpart_manager: GenericManager,
        member_key: str,
        member_id: int) -> None:
    """
    Records the inverse of the delete cascade pulling a member out of every counterpart - before it runs

    Args:
        ledger (WriteLedger): The request's ledger
        counterpart_manager (GenericManager): The manager of the other side
        member_key (str): The counterparts' membership array
        member_id (int): public_id of the member being deleted
    """
    listed_before: set[int] = listing_ids(counterpart_manager, member_key, member_id)

    if listed_before:
        _record_pull(ledger, counterpart_manager, member_key, member_id, listed_before)


def _record_reference_snapshots(ledger: WriteLedger, manager: Any, criteria: dict[str, Any]) -> None:
    """
    Records every document a cascade is about to change, as an update undone from its snapshot

    One read; recorded before the cascade runs, so an undo of a document the cascade never reached restores it
    to what it already is

    Args:
        ledger (WriteLedger): The request's ledger
        manager (Any): The manager of the referencing collection
        criteria (dict[str, Any]): Exactly what the cascade's writes will match
    """
    for document in manager.find(criteria=criteria):
        ledger.updated(manager, document[CmdbDAO.PUBLIC_ID_KEY], document)


def record_delete_cascade(
        ledger: WriteLedger,
        entity_manager: GenericManager,
        counterpart_manager: GenericManager,
        member_key: str,
        snapshot: dict[str, Any],
        reference_type: PersonReferenceType,
        reference_managers: tuple[GenericManager, GenericManager]) -> None:
    """
    Records the inverse of every write ``delete_with_follow_up`` is about to make, in the order it makes them

    Args:
        ledger (WriteLedger): The request's ledger
        entity_manager (GenericManager): The manager of the person or group being deleted
        counterpart_manager (GenericManager): The manager of the other side of the membership
        member_key (str): The counterparts' membership array
        snapshot (dict[str, Any]): The stored document being deleted
        reference_type (PersonReferenceType): Which of the two kinds is deleted
        reference_managers (tuple[GenericManager, GenericManager]): The IsmsRiskAssessment and the
            IsmsControlMeasureAssignment managers, whose documents the cascade clears the references from
    """
    public_id: int = snapshot[CmdbDAO.PUBLIC_ID_KEY]
    risk_assessments_manager, assignments_manager = reference_managers

    _record_reference_snapshots(
        ledger, risk_assessments_manager, risk_assessment_reference_criteria(public_id, reference_type)
    )
    _record_reference_snapshots(
        ledger, assignments_manager, control_measure_assignment_reference_criteria(public_id, reference_type)
    )
    _record_membership_removal(ledger, counterpart_manager, member_key, public_id)
    ledger.deleted(entity_manager, public_id, snapshot)
