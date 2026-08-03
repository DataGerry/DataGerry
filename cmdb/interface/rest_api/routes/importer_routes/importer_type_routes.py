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
Implementation of all API routes for Type Imports

The blueprint is mounted by init_rest_api at `/import/type`, so this module is self-contained: it can
be imported without an application context and without a parent import blueprint

Both routes take the same multipart upload (a JSON list of exported CmdbTypes) and answer with the same
partial report the object import returns (`ImportReportResponse`: `message`, `success_imports`,
`failed_imports`): every entry is processed independently, so a single bad entry never discards the rest
of the batch. An imported type only adds to the `success_imports` count; a rejected one is reported as
`{failed_type, errors}` - the data the user provided plus the reason - which is the sole difference from
the object import's `failed_object`. The per-entry work lives in importer_type_helper
"""
from logging import Logger, getLogger
from flask import request, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import TypesManager, SectionTemplatesManager

from cmdb.models.user_model import CmdbUser
from cmdb.framework.importer.responses.import_report_response import ImportReportResponse
from cmdb.interface.rest_api.routes.importer_routes.importer_type_helper import (
    parse_uploaded_types,
    run_type_import_batch,
    create_type_from_entry,
    update_type_from_entry,
)
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.routes.cmdb_license.license_guard import feature_locked
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.responses import DefaultResponse
# -------------------------------------------------------------------------------------------------------------------- #

importer_type_blueprint = APIBlueprint('importer_type', __name__)

LOGGER: Logger = getLogger(__name__)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@importer_type_blueprint.route('/create/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@importer_type_blueprint.protect(auth=True, right='base.import.type.*')
def add_type(request_user: CmdbUser) -> Response:
    """
    Adds new CmdbTypes based on uploaded JSON data

    A fresh public_id and creation timestamp are assigned to each imported type, so any public_id in
    the upload is dropped, and the requesting user becomes the author. Only the name, fields and
    sections are really required: the optional `active`, `selectable_as_parent`, `label`, `version`,
    `ci_explorer_label`, `ci_explorer_color` and `acl` are defaulted when the upload omits them.
    A type declaring a `special_type` must name a known one, requires the IPAM feature, and is refused
    when that marker is already claimed; the type name must be present and unique, and the field /
    section structure must be sound. References to types that do not exist here are cleared and a
    missing icon is defaulted. An imported SpecialType is wired up (IPAM ref_types cross-wiring) just
    like a hand-created one. Entries that cannot be imported are collected instead of aborting the
    request; the remaining entries are still inserted

    Args:
        request_user (CmdbUser): The user making the request, used for permission validation

    Raises:
        HTTPException: 400 if the upload is missing or unusable, 500 on an unexpected error

    Returns:
        Response: A Flask Response object containing the partial report - a summary line, the number of
                  created types (`success_imports`) and the `failed_imports` of the entries that could
                  not be imported (each as `{failed_type, errors}`, carrying the uploaded data and the
                  reason). An empty `failed_imports` means every type was imported
    """
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        section_templates_manager: SectionTemplatesManager = ManagerProvider.get_manager(
            ManagerType.SECTION_TEMPLATES, request_user,
        )

        new_type_list = parse_uploaded_types(request)
        # The licence state is per request, not per entry - resolve it once for the whole batch
        ipam_locked: bool = feature_locked(LicenseFeature.IPAM, request_user)

        import_report: ImportReportResponse = run_type_import_batch(
            new_type_list,
            lambda new_type_data: create_type_from_entry(
                new_type_data, types_manager, section_templates_manager, request_user, ipam_locked,
            ),
        )

        return DefaultResponse(import_report).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[add_type] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while creating Types from imported data!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@importer_type_blueprint.route('/update/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@importer_type_blueprint.protect(auth=True, right='base.import.type.*')
def update_type(request_user: CmdbUser) -> Response:
    """
    Updates existing CmdbTypes based on uploaded JSON data

    Updates are applied by public_id. Each type must already exist, otherwise an error is recorded for
    it. The requesting user is recorded as the editor of every type it replaces, while the stored
    author, creation time, version and `special_type` are left untouched - `special_type` is
    immutable and can only be set when a type is created. An update replaces the fields and sections
    wholesale, so it passes the same name / structure rules and the same repairs and defaults as a
    create - and the same follow-up work: the type's Objects are re-aligned with its new field set,
    MDS rows and CmdbLocations are updated, dropped global section templates are cleaned up and the
    SpecialType wiring is re-applied. Entries
    that cannot be updated are collected instead of aborting the request; the remaining entries are
    still updated

    Args:
        request_user (CmdbUser): The user making the request, used for permission and context

    Raises:
        HTTPException: 400 if the upload is missing or unusable, 500 on an unexpected error

    Returns:
        Response: A Flask Response object containing the partial report - a summary line, the number of
                  updated types (`success_imports`) and the `failed_imports` of the entries that could
                  not be updated (each as `{failed_type, errors}`, carrying the uploaded data and the
                  reason). An empty `failed_imports` means every type was updated
    """
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        section_templates_manager: SectionTemplatesManager = ManagerProvider.get_manager(
            ManagerType.SECTION_TEMPLATES, request_user,
        )

        update_type_list = parse_uploaded_types(request)
        # The licence state is per request, not per entry - resolve it once for the whole batch
        ipam_locked: bool = feature_locked(LicenseFeature.IPAM, request_user)

        import_report: ImportReportResponse = run_type_import_batch(
            update_type_list,
            lambda update_type_data: update_type_from_entry(
                update_type_data, types_manager, section_templates_manager, request_user, ipam_locked,
            ),
        )

        return DefaultResponse(import_report).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[update_type] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while updating Types from imported data!")
