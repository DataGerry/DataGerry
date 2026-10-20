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
The global section templates on the CmdbType write routes

A type's copy of each global template it claims is the template's (``global_template_reconcile``): the create and
the update route put the payload back in line with the stored templates before any guard judges it, so the
structure guard, the identifier rules and the field-default rule see what will be stored
"""
from typing import Any

from flask import abort

from cmdb.manager import SectionTemplatesManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.user_model import CmdbUser
from cmdb.framework.section_templates.global_template_reconcile import (
    GlobalTemplateReconcile,
    claimed_template_names,
    first_template_conflict,
    reconcile_type_with_global_templates,
    resolve_global_templates,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_constants import (
    TEMPLATE_SECTION_FOREIGN_FIELD_MESSAGE,
)
# -------------------------------------------------------------------------------------------------------------------- #

def reconcile_global_template_copies(data: dict[str, Any], request_user: CmdbUser) -> list[str]:
    """
    Puts a type payload's copies of its global section templates back in line with the stored templates, in place

    Args:
        data (dict[str, Any]): The type payload about to be judged and written, modified in place
        request_user (CmdbUser): The caller, whose section-template manager reads the templates

    Raises:
        BaseManagerGetError: If the template lookup fails
        HTTPException: 400 when a field the template does not own sits inside a claimed template's section

    Returns:
        list[str]: The claims that named no stored global template and were dropped from global_template_ids
    """
    claims: list[str] = claimed_template_names(data)

    if not claims:
        return []

    section_templates_manager: SectionTemplatesManager = ManagerProvider.get_manager(
        ManagerType.SECTION_TEMPLATES, request_user,
    )
    outcome: GlobalTemplateReconcile = reconcile_type_with_global_templates(
        data, resolve_global_templates(section_templates_manager, claims),
    )

    abort_on_template_section_conflict(outcome)

    return outcome.dropped_claims


def abort_on_template_section_conflict(outcome: GlobalTemplateReconcile) -> None:
    """
    Refuses a payload whose claimed template's section holds a field the template does not own

    Args:
        outcome (GlobalTemplateReconcile): What the reconcile found

    Raises:
        HTTPException: 400 naming the first such template and its foreign fields
    """
    conflict: tuple[str, list[str]] | None = first_template_conflict(outcome)

    if conflict:
        abort(400, TEMPLATE_SECTION_FOREIGN_FIELD_MESSAGE.format(template=conflict[0], names=', '.join(conflict[1])))
