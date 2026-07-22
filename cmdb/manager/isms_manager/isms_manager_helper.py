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
"""
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.manager.generic_manager import GenericManager

from cmdb.models.isms_model import IsmsImpact, IsmsRisk
from cmdb.models.isms_model.risk_calculation_constants import RiskCalculationKey
# -------------------------------------------------------------------------------------------------------------------- #


def load_calculation_basis(dbm: MongoDatabaseManager, db_name: str, collection: str) -> dict[int, float | None]:
    """
    Loads every document's calculation_basis from a scale collection in a single query.

    Used for the bounded ISMS scale collections (IsmsImpact, IsmsLikelihood) whose public_id ->
    calculation_basis lookup is needed to (re)derive a RiskAssessment's maximum impact and likelihood
    value without issuing a per-row query.

    Args:
        dbm (MongoDatabaseManager): The database manager to query through
        db_name (str): Name of the database holding the collection
        collection (str): The scale collection to read (e.g. IsmsImpact.COLLECTION)

    Returns:
        dict[int, float | None]: Mapping of document public_id to its calculation_basis
    """
    return {
        doc['public_id']: doc.get('calculation_basis')
        for doc in dbm.find(collection=collection, db_name=db_name, filter={})
    }


def load_impact_calculation_basis(dbm: MongoDatabaseManager, db_name: str) -> dict[int, float | None]:
    """
    Loads every IsmsImpact's calculation_basis in a single query.

    Thin wrapper over load_calculation_basis for the IsmsImpact collection, shared by the managers
    that recompute a RiskAssessment's maximum impact (ImpactManager and ImpactCategoryManager).

    Args:
        dbm (MongoDatabaseManager): The database manager to query through
        db_name (str): Name of the database holding the IsmsImpact collection

    Returns:
        dict[int, float | None]: Mapping of IsmsImpact public_id to its calculation_basis
    """
    return load_calculation_basis(dbm, db_name, IsmsImpact.COLLECTION)


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


def delete_isms_item_if_unused_by_risk(
        manager: GenericManager,
        public_id: int,
        risk_reference_field: str,
        risk_usage_error: type[Exception],
        delete_error: type[Exception],
        in_use_message: str) -> bool:
    """
    Deletes an ISMS item, refusing when an IsmsRisk still references it.

    Shared by the leaf ISMS entities whose deletion is blocked while a Risk uses them (Threat,
    Vulnerability, ProtectionGoal); they differ only in the IsmsRisk field that references them and
    in their manager-specific exception types.

    Args:
        manager (GenericManager): The manager whose item is being deleted
        public_id (int): public_id of the item to delete
        risk_reference_field (str): The IsmsRisk field holding referenced item ids
                                    (e.g. 'threats', 'vulnerabilities', 'protection_goals')
        risk_usage_error (type[Exception]): Raised (unwrapped) when a Risk still references the item
        delete_error (type[Exception]): Raised when the deletion otherwise fails
        in_use_message (str): Message for the risk_usage_error

    Raises:
        risk_usage_error: When an IsmsRisk references the item via risk_reference_field
        delete_error: When the deletion fails for any other reason

    Returns:
        bool: True if the item was deleted, else False
    """
    try:
        if manager.get_one_by({risk_reference_field: public_id}, IsmsRisk.COLLECTION):
            raise risk_usage_error(in_use_message)

        return manager.delete_item(public_id)
    except risk_usage_error:
        raise
    except Exception as err:
        raise delete_error(str(err)) from err
