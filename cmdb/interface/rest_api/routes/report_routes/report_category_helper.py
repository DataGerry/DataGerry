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
Helper methods for the CmdbReportCategory API routes

Holds what the Create / Read / Update / Delete routes share:

* request-payload sanitising - the write whitelist (a client may only set 'name'; 'public_id' comes
  from the URL and 'predefined' is system-owned) plus the required-name guard
* the load-or-404 lookup used by the single read, the update and the delete
* the two write guards - a predefined CmdbReportCategory is read-only, and a category still
  referenced by a CmdbReport can not be deleted

Validation helpers abort with HTTP 400 / 403 / 404 so the routes stay focused on orchestration.
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort

from cmdb.manager import ReportCategoriesManager

from cmdb.models.object_model import CmdbObjectKey
from cmdb.models.reports_model.cmdb_report import CmdbReport
from cmdb.models.reports_model.cmdb_report_category import CmdbReportCategory

from cmdb.interface.rest_api.routes.report_routes.report_constants import (
    CATEGORY_IN_USE_MSG,
    CATEGORY_NAME_REQUIRED_MSG,
    CATEGORY_NOT_FOUND_MSG,
    CATEGORY_PREDEFINED_MSG,
    REPORT_CATEGORY_WRITE_KEYS,
    ReportCategoryAction,
    ReportCategoryKey,
    ReportKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)


def strip_unknown_category_keys(params: dict[str, Any]) -> dict[str, Any]:
    """
    Keeps only the client-settable keys of a CmdbReportCategory write payload

    Everything outside REPORT_CATEGORY_WRITE_KEYS is dropped instead of rejected, mirroring the
    'purge_unknown' behaviour of the Cerberus-validated write routes: the request parameters are read
    straight off the query string, so an unknown parameter would otherwise be persisted verbatim as a
    document key

    Args:
        params (dict[str, Any]): The raw request parameters

    Returns:
        dict[str, Any]: A new dict holding only the whitelisted keys
    """
    return {key: value for key, value in params.items() if key in REPORT_CATEGORY_WRITE_KEYS}


def require_category_name(params: dict[str, Any]) -> str:
    """
    Returns the payload's trimmed 'name', aborting when it is missing or blank

    The name is the only meaningful content of a CmdbReportCategory, and nothing downstream enforces
    it: the request parameters are not schema-validated and GenericManager.insert_item persists a
    plain dict without ever constructing the model. Without this guard a nameless category reaches
    the database and renders as an empty row

    Args:
        params (dict[str, Any]): The sanitised request parameters

    Raises:
        HTTPException: 400 when 'name' is absent, not a string, or whitespace only

    Returns:
        str: The name with surrounding whitespace removed
    """
    name: Any = params.get(ReportCategoryKey.NAME)

    if not isinstance(name, str) or not name.strip():
        abort(400, CATEGORY_NAME_REQUIRED_MSG)

    return name.strip()


def normalize_category_params(params: dict[str, Any]) -> dict[str, Any]:
    """
    Builds the sanitised write payload of a CmdbReportCategory create / update request

    Drops every key a client may not set and requires a non-empty 'name', which is stored trimmed.
    The caller adds the server-owned keys ('public_id' from the URL, 'predefined') afterwards

    Args:
        params (dict[str, Any]): The raw request parameters

    Raises:
        HTTPException: 400 when 'name' is absent, not a string, or whitespace only

    Returns:
        dict[str, Any]: The payload to persist, holding the trimmed 'name' only
    """
    payload: dict[str, Any] = strip_unknown_category_keys(params)
    payload[ReportCategoryKey.NAME] = require_category_name(payload)

    return payload


def load_category_or_404(
        report_categories_manager: ReportCategoriesManager,
        public_id: int,
        as_dict: bool = False,
    ) -> CmdbReportCategory | dict[str, Any]:
    """
    Retrieves a CmdbReportCategory by its public_id, aborting when it does not exist

    Args:
        report_categories_manager (ReportCategoriesManager): Manager used for the lookup
        public_id (int): public_id of the requested CmdbReportCategory
        as_dict (bool): If True return the raw document instead of the model instance. Defaults to False

    Raises:
        ReportCategoriesManagerGetError: If the lookup itself fails
        HTTPException: 404 when no CmdbReportCategory carries the given public_id

    Returns:
        CmdbReportCategory | dict[str, Any]: The model instance, or the raw document when as_dict is set
    """
    report_category: CmdbReportCategory | dict[str, Any] | None = report_categories_manager.get_item(
                                                                                            public_id,
                                                                                            as_dict=as_dict)

    if not report_category:
        abort(404, CATEGORY_NOT_FOUND_MSG.format(public_id=public_id))

    return report_category


def abort_if_predefined(report_category: CmdbReportCategory, action: ReportCategoryAction) -> None:
    """
    Refuses a write on a predefined CmdbReportCategory

    A predefined category is provided by DataGerry (the 'General' category is seeded on first boot and
    is identified by its name), so it is read-only for every client: it can neither be renamed nor
    deleted. The frontend already hides both actions for a predefined row

    Args:
        report_category (CmdbReportCategory): The targeted CmdbReportCategory
        action (ReportCategoryAction): The refused operation, named in the error message

    Raises:
        HTTPException: 403 when the CmdbReportCategory is predefined
    """
    if report_category.predefined:
        abort(403, CATEGORY_PREDEFINED_MSG.format(action=action.value))


def abort_if_category_in_use(report_categories_manager: ReportCategoriesManager, public_id: int) -> None:
    """
    Refuses the deletion of a CmdbReportCategory that CmdbReports still reference

    The referencing reports are counted server-side (no report document is loaded), so the guard costs
    one count regardless of how many reports the category holds

    Args:
        report_categories_manager (ReportCategoriesManager): Manager used for the cross-collection count
        public_id (int): public_id of the CmdbReportCategory about to be deleted

    Raises:
        BaseManagerGetError: If the count itself fails (it is not wrapped as a manager-specific error)
        HTTPException: 403 when at least one CmdbReport references the CmdbReportCategory
    """
    reports_using_category: int = report_categories_manager.count_from_other_collection(
        CmdbReport.COLLECTION, {ReportKey.REPORT_CATEGORY_ID: public_id}
    )

    if reports_using_category > 0:
        abort(403, CATEGORY_IN_USE_MSG.format(public_id=public_id))


def build_category_update_payload(
        params: dict[str, Any],
        public_id: int,
        report_category: CmdbReportCategory,
    ) -> dict[str, Any]:
    """
    Builds the document an update writes for an existing CmdbReportCategory

    Sanitises the request parameters, then pins the two server-owned keys: the identity is taken from
    the URL (never from the payload, which would silently rewrite the document's identity) and
    'predefined' is carried over from the stored category

    Args:
        params (dict[str, Any]): The raw request parameters
        public_id (int): public_id of the CmdbReportCategory being updated, taken from the URL
        report_category (CmdbReportCategory): The stored CmdbReportCategory being updated

    Raises:
        HTTPException: 400 when 'name' is absent, not a string, or whitespace only

    Returns:
        dict[str, Any]: The full document to persist
    """
    payload: dict[str, Any] = normalize_category_params(params)
    payload[CmdbObjectKey.PUBLIC_ID] = public_id
    payload[ReportCategoryKey.PREDEFINED] = report_category.predefined

    return payload
