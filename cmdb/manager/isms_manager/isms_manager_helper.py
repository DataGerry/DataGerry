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
Shared helper logic for the ISMS managers

Every function here reads and writes through a manager's own ``BaseManager`` methods - another collection of the
manager's database is named with their ``collection`` argument - so a caller catches the typed ``BaseManager*Error``
it expects and nothing else, and a programming error is never mistaken for a database failure.

**The delete-if-unused rule cannot be made atomic without transactions.** A Threat, Vulnerability,
ProtectionGoal or ControlMeasure may only be deleted while nothing references it, and the reference lives in
another collection. ``delete_unless_referenced`` and ``delete_unreferenced_batch`` therefore check, delete, and
check again: an item that gained a reference between the first check and the delete is put back under its
old id and refused. What remains open is a reference written after the second check by a writer that read the
item before it was deleted - that writer stores a dangling id, which every ISMS reader already skips
"""
from logging import Logger, getLogger
from typing import Any, Callable

from pymongo import UpdateOne

from cmdb.manager.base_manager import BaseManager
from cmdb.manager.generic_manager import GenericManager
from cmdb.utils import Builder
from cmdb.framework.write_ledger import WriteLedger

from cmdb.models.isms_model import IsmsImpact, IsmsRisk
from cmdb.models.isms_model.risk_calculation_constants import RiskCalculationKey
from cmdb.models.isms_model.isms_impact_constants import ImpactKey
from cmdb.models.isms_model.isms_likelihood_constants import LikelihoodKey
from cmdb.models.isms_model.isms_risk_constants import RiskKey
from cmdb.manager.isms_manager.isms_manager_constants import (
    GROUPED_ID_KEY,
    MONGO_ID_KEY,
    PUBLIC_ID_KEY,
)

from cmdb.errors.manager import (
    BaseManagerDeleteError,
    BaseManagerGetError,
    BaseManagerInsertError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The errors a delete-if-unused step raises from the manager's own methods: the reference check, the delete, and
# the restore of an item that gained a reference meanwhile
DELETE_IF_UNUSED_ERRORS: tuple[type[Exception], ...] = (
    BaseManagerGetError,
    BaseManagerDeleteError,
    BaseManagerInsertError,
)

# -------------------------------------------------------------------------------------------------------------------- #
#                                               calculation basis lookups                                              #
# -------------------------------------------------------------------------------------------------------------------- #

def load_calculation_basis(manager: BaseManager,
                           collection: str,
                           scale_keys: type[ImpactKey] | type[LikelihoodKey]) -> dict[int, float | None]:
    """
    Loads every document's calculation_basis from a scale collection in a single projected query

    Used for the bounded ISMS scale collections (IsmsImpact, IsmsLikelihood) whose public_id ->
    calculation_basis lookup is needed to (re)derive a RiskAssessment's maximum impact and likelihood
    value without issuing a per-row query. The two scales are separate entities whose documents
    happen to share their key names, so the caller names the key set of the collection it reads

    Args:
        manager (BaseManager): The manager to read through (any manager of the same database)
        collection (str): The scale collection to read (e.g. IsmsImpact.COLLECTION)
        scale_keys (type[ImpactKey] | type[LikelihoodKey]): The key enum of that collection

    Raises:
        BaseManagerGetError: If the scale could not be read

    Returns:
        dict[int, float | None]: Mapping of document public_id to its calculation_basis
    """
    documents: list[dict[str, Any]] = manager.get_many_from_other_collection(
        collection,
        projection={
            scale_keys.PUBLIC_ID.value: 1,
            scale_keys.CALCULATION_BASIS.value: 1,
            MONGO_ID_KEY: 0,
        },
    )

    return {doc[scale_keys.PUBLIC_ID.value]: doc.get(scale_keys.CALCULATION_BASIS.value) for doc in documents}


def load_impact_calculation_basis(manager: BaseManager) -> dict[int, float | None]:
    """
    Loads every IsmsImpact's calculation_basis in a single query

    Thin wrapper over load_calculation_basis for the IsmsImpact collection, shared by the managers
    that recompute a RiskAssessment's maximum impact (ImpactManager and ImpactCategoryManager)

    Args:
        manager (BaseManager): The manager to read through

    Raises:
        BaseManagerGetError: If the IsmsImpacts could not be read

    Returns:
        dict[int, float | None]: Mapping of IsmsImpact public_id to its calculation_basis
    """
    return load_calculation_basis(manager, IsmsImpact.COLLECTION, ImpactKey)


def recompute_max_impact(
        impacts: list[dict[str, Any]],
        basis_by_id: dict[int, float | None]) -> tuple[int | None, float | None]:
    """
    Determines the Impact with the highest calculation_basis in a risk_calculation impact matrix.

    Args:
        impacts (list[dict[str, Any]]): The 'impacts' entries of a risk_calculation matrix
        basis_by_id (dict[int, float | None]): Mapping of Impact public_id to calculation_basis

    Returns:
        tuple[int | None, float | None]: (maximum_impact_id, maximum_impact_value), both None
                                         when no impact in the matrix has a known basis
    """
    max_id: int | None = None
    max_value: float | None = None

    for item in impacts:
        impact_id = item.get(RiskCalculationKey.IMPACT_ID)

        if impact_id is None:
            continue

        basis = basis_by_id.get(impact_id)

        if basis is not None and (max_value is None or basis > max_value):
            max_value = basis
            max_id = impact_id

    return max_id, max_value

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  reference lookups                                                   #
# -------------------------------------------------------------------------------------------------------------------- #

def get_referenced_ids(manager: BaseManager, collection: str, field: str, public_ids: list[int]) -> set[int]:
    """
    Returns which of the given ids another collection references in ``field``, in one grouped aggregation

    The batched counterpart of a single "is it used" check: the documents holding any candidate are matched,
    the field unwound, only the candidates kept and grouped distinct. ``$unwind`` treats a scalar as a one-element
    array, so the same pipeline serves a list field (an IsmsRisk's ``threats``) and a scalar one (an
    IsmsControlMeasureAssignment's ``control_measure_id``)

    Args:
        manager (BaseManager): The manager to read through
        collection (str): The referencing collection
        field (str): The referencing field
        public_ids (list[int]): The candidate ids; an empty list queries nothing

    Raises:
        BaseManagerIterationError: If the aggregation failed

    Returns:
        set[int]: The subset of public_ids referenced by at least one document
    """
    if not public_ids:
        return set()

    pipeline: list[dict[str, Any]] = [
        Builder.match_({field: {'$in': public_ids}}),
        Builder.unwind_(f'${field}'),
        Builder.match_({field: {'$in': public_ids}}),
        Builder.group_(f'${field}'),
    ]

    return {document[GROUPED_ID_KEY] for document in manager.aggregate_all(pipeline, collection)}


def is_referenced_by_risk(manager: BaseManager, risk_reference_field: RiskKey, public_id: int) -> bool:
    """
    Whether an IsmsRisk references the item through one of its id lists

    Args:
        manager (BaseManager): The manager to read through
        risk_reference_field (RiskKey): The IsmsRisk list holding the item's id
        public_id (int): The item's public_id

    Raises:
        BaseManagerGetError: If the IsmsRisks could not be read

    Returns:
        bool: True when at least one IsmsRisk holds the id
    """
    return manager.get_one_by({risk_reference_field.value: public_id}, IsmsRisk.COLLECTION) is not None

# -------------------------------------------------------------------------------------------------------------------- #
#                                                    delete-if-unused                                                  #
# -------------------------------------------------------------------------------------------------------------------- #

def delete_unless_referenced(
        manager: GenericManager,
        public_id: int,
        is_referenced: Callable[[], bool],
        usage_error: type[Exception],
        in_use_message: str) -> bool:
    """
    Deletes an item that nothing references, refusing one that is referenced

    Check, delete, check again (see the module docstring): an item that gained a reference between the first
    check and the delete is re-inserted from the document the delete removed, under its old public_id, and
    refused like one that was referenced from the start

    Args:
        manager (GenericManager): The manager whose item is deleted; its configured 'delete' error is raised
        public_id (int): public_id of the item to delete
        is_referenced (Callable[[], bool]): Whether something references the item now; may raise
            BaseManagerGetError
        usage_error (type[Exception]): Raised, unwrapped, when the item is referenced
        in_use_message (str): The usage_error's message

    Raises:
        usage_error: When the item is referenced, before or right after the delete
        Exception: The manager's configured 'delete' error when a check, the delete or the restore fails

    Returns:
        bool: True if the item was deleted, False when it did not exist
    """
    delete_error: type[Exception] = manager.exceptions.get('delete', Exception)

    try:
        if is_referenced():
            raise usage_error(in_use_message)

        removed: dict[str, Any] | None = manager.find_one_and_delete({PUBLIC_ID_KEY: public_id})

        if removed is None:
            return False

        if not is_referenced():
            return True

        manager.insert(removed, skip_public=True)
    except DELETE_IF_UNUSED_ERRORS as err:
        LOGGER.error("[delete_unless_referenced] %s: %s", type(err).__name__, err)
        raise delete_error(err) from err

    LOGGER.warning("[delete_unless_referenced] %s %s gained a reference while it was deleted - restored",
                   manager.collection, public_id)

    raise usage_error(in_use_message)


def delete_unreferenced_batch(
        manager: GenericManager,
        requested_ids: list[int],
        referenced_ids: Callable[[list[int]], set[int]]) -> tuple[list[int], list[int]]:
    """
    Deletes every requested item that nothing references, in one delete, and reports the referenced ones

    The batched form of delete_unless_referenced: one reference query for the batch, one projected read of
    the unreferenced items that exist (the snapshots a restore needs), one delete_many, one reference query
    over the deleted ids - and one insert of the items that gained a reference meanwhile, which then count as
    referenced. A requested id that does not exist is in neither list

    Args:
        manager (GenericManager): The manager whose items are deleted
        requested_ids (list[int]): The requested public_ids, duplicates allowed
        referenced_ids (Callable[[list[int]], set[int]]): Which of the given ids are referenced; raises the
            manager's own 'get' error

    Raises:
        Exception: The manager's configured 'get' error when reading the items fails, its 'delete' error when
            the delete or the restore fails; whatever ``referenced_ids`` raises

    Returns:
        tuple[list[int], list[int]]: (deleted ids, referenced ids), both sorted ascending
    """
    in_use: set[int] = referenced_ids(requested_ids)
    candidates: list[int] = sorted(set(requested_ids) - in_use)

    if not candidates:
        return [], sorted(in_use)

    try:
        stored: list[dict[str, Any]] = manager.find(criteria={PUBLIC_ID_KEY: {'$in': candidates}})
    except BaseManagerGetError as err:
        raise manager.exceptions.get('get', Exception)(err) from err

    stored_ids: list[int] = [document[PUBLIC_ID_KEY] for document in stored]

    if not stored_ids:
        return [], sorted(in_use)

    try:
        manager.delete_many({PUBLIC_ID_KEY: {'$in': stored_ids}})
    except BaseManagerDeleteError as err:
        raise manager.exceptions.get('delete', Exception)(err) from err

    late: set[int] = referenced_ids(stored_ids)

    if late:
        try:
            manager.insert_many([document for document in stored if document[PUBLIC_ID_KEY] in late],
                                skip_public=True)
        except BaseManagerInsertError as err:
            raise manager.exceptions.get('delete', Exception)(err) from err

        LOGGER.warning("[delete_unreferenced_batch] %s %s gained a reference while they were deleted - restored",
                       manager.collection, sorted(late))

    return sorted(set(stored_ids) - late), sorted(in_use | late)


def delete_isms_item_if_unused_by_risk(
        manager: GenericManager,
        public_id: int,
        risk_reference_field: RiskKey,
        risk_usage_error: type[Exception],
        in_use_message: str) -> bool:
    """
    Deletes an ISMS item, refusing when an IsmsRisk still references it

    Shared by the leaf ISMS entities whose deletion is blocked while a Risk uses them (Threat,
    Vulnerability, ProtectionGoal); they differ only in the IsmsRisk field that references them and
    in their manager-specific exception types

    Args:
        manager (GenericManager): The manager whose item is being deleted
        public_id (int): public_id of the item to delete
        risk_reference_field (RiskKey): The IsmsRisk field holding referenced item ids
        risk_usage_error (type[Exception]): Raised (unwrapped) when a Risk still references the item
        in_use_message (str): Message for the risk_usage_error

    Raises:
        risk_usage_error: When an IsmsRisk references the item via risk_reference_field
        Exception: The manager's configured 'delete' error when the usage check, the delete or the restore fails

    Returns:
        bool: True if the item was deleted, else False
    """
    return delete_unless_referenced(
        manager,
        public_id,
        lambda: is_referenced_by_risk(manager, risk_reference_field, public_id),
        risk_usage_error,
        in_use_message,
    )

def dotted_value(document: dict[str, Any], path: str) -> tuple[bool, Any]:
    """
    Reads a dotted path out of a nested document

    Args:
        document (dict[str, Any]): The document
        path (str): The dotted path, e.g. 'risk_calculation_before.likelihood_value'

    Returns:
        tuple[bool, Any]: (whether the path exists, its value - None when it does not)
    """
    current: Any = document

    for part in path.split('.'):
        if not isinstance(current, dict) or part not in current:
            return False, None

        current = current[part]

    return True, current


def restore_operations(snapshots: list[dict[str, Any]], paths: list[str]) -> list[UpdateOne]:
    """
    One update per snapshot that puts its paths back as they were: ``$set`` the values it had, ``$unset`` the
    paths it lacked

    Args:
        snapshots (list[dict[str, Any]]): The documents as read before the write, each with its public_id
        paths (list[str]): The dotted paths the write changes

    Returns:
        list[UpdateOne]: The operations, in snapshot order
    """
    operations: list[UpdateOne] = []

    for snapshot in snapshots:
        to_set: dict[str, Any] = {}
        to_unset: dict[str, str] = {}

        for path in paths:
            found, value = dotted_value(snapshot, path)

            if found:
                to_set[path] = value
            else:
                to_unset[path] = ''

        update: dict[str, Any] = {}

        if to_set:
            update['$set'] = to_set

        if to_unset:
            update['$unset'] = to_unset

        operations.append(UpdateOne({PUBLIC_ID_KEY: snapshot[PUBLIC_ID_KEY]}, update))

    return operations


def snapshots_restored(manager: BaseManager,
                       collection: str,
                       snapshots: list[dict[str, Any]],
                       paths: list[str]) -> bool:
    """
    Whether every snapshot's paths read back as they were

    Args:
        manager (BaseManager): The manager to read through
        collection (str): The collection the snapshots are of
        snapshots (list[dict[str, Any]]): The documents as read before the write
        paths (list[str]): The dotted paths compared

    Raises:
        BaseManagerGetError: If the read-back failed

    Returns:
        bool: True when every compared path holds its snapshot value (or is absent where it was absent)
    """
    ids: list[int] = [snapshot[PUBLIC_ID_KEY] for snapshot in snapshots]
    stored: dict[int, dict[str, Any]] = {
        document[PUBLIC_ID_KEY]: document
        for document in manager.get_many_from_other_collection(
            collection, projection=snapshot_projection(paths), criteria={PUBLIC_ID_KEY: {'$in': ids}},
        )
    }

    return all(
        snapshot[PUBLIC_ID_KEY] in stored
        and all(dotted_value(stored[snapshot[PUBLIC_ID_KEY]], path) == dotted_value(snapshot, path) for path in paths)
        for snapshot in snapshots
    )


def snapshot_projection(paths: list[str]) -> dict[str, int]:
    """
    The projection that reads a document's public_id and the given paths, nothing else

    Args:
        paths (list[str]): The dotted paths to read

    Returns:
        dict[str, int]: The MongoDB projection
    """
    return {PUBLIC_ID_KEY: 1, MONGO_ID_KEY: 0, **{path: 1 for path in paths}}


def record_follow_up_write(
        ledger: WriteLedger,
        manager: BaseManager,
        collection: str,
        description: str,
        snapshots: list[dict[str, Any]],
        paths: list[str]) -> None:
    """
    Records a follow-up write over other documents in the ledger - before it runs - with its field-level inverse

    Only the paths the write changes are put back, so whatever else changed on those documents meanwhile is
    kept. Nothing is recorded for an empty snapshot list

    Args:
        ledger (WriteLedger): The request's ledger
        manager (BaseManager): The manager to write and read through
        collection (str): The collection the write changes
        description (str): What the write does, as the residue names it
        snapshots (list[dict[str, Any]]): The documents as read before the write
        paths (list[str]): The dotted paths the write changes
    """
    if not snapshots:
        return

    ledger.compensated(
        collection,
        description,
        undo=lambda: manager.bulk_write(restore_operations(snapshots, paths), collection=collection),
        verify=lambda: snapshots_restored(manager, collection, snapshots, paths),
    )
