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
The ConfigItem count the DataGerry service portal is told about (cloud mode)

Every write that changes how many CmdbObjects exist reports the new count, with a per-type breakdown, so the
portal can hold the subscription's ConfigItem limit against it: the object create, the single and the bulk delete,
the object import and the configuration reset. They all report through ``handle_sync_config_item_count``, which is
why it lives here rather than beside any of them: the framework layer may be imported by the routes and by the
importer alike, and imports no route itself.

**The sync is hosted-cloud telemetry, best-effort, and decided in one place.** On-premise and on a developer's
local cloud stack it reads nothing and sends nothing. On a hosted installation a missing portal configuration, a
failed count read (a lost connection included) or a failed request is logged and the sync skipped: the write it
reports on is already stored, so it must never fail the request. A programming error is not caught
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import ObjectsManager, TypesManager, DgServicePortalManager
from cmdb.open_celium.oc_helpers import is_hosted_cloud
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.user_model.cmdb_user import CmdbUser
from cmdb.framework.config_item_sync_constants import ConfigItemTypeCountKey

from cmdb.errors.database import TRANSIENT_DATABASE_ERRORS
from cmdb.errors.manager.objects_manager import ObjectsManagerIterationError
from cmdb.errors.manager.types_manager import TypesManagerGetError
from cmdb.errors.security import NoAccessTokenError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# What a failed count read raises - the database's failure, not the caller's: a failed read, or a lost connection /
# lock timeout the managers pass on unwrapped
COUNT_READ_ERRORS: tuple[type[Exception], ...] = (
    ObjectsManagerIterationError, TypesManagerGetError, *TRANSIENT_DATABASE_ERRORS,
)


def build_type_object_counts(request_user: CmdbUser) -> tuple[list[dict[str, Any]], int]:
    """
    Builds the per-type object-count list for the Service Portal sync payload

    Counts every CmdbObject grouped by its type_id in a single aggregation, then resolves each
    type_id to its CmdbType label via one bulk lookup. CmdbTypes with no objects are omitted, and
    a counted type_id whose CmdbType no longer exists is skipped - so the returned breakdown may
    sum to less than the total. The total is taken from the same aggregation and counts every
    document (no active filter), so it always equals an unfiltered ``count_documents()``

    Args:
        request_user (CmdbUser): The CmdbUser making the request

    Raises:
        ObjectsManagerIterationError: If the objects could not be counted
        TypesManagerGetError: If the CmdbTypes could not be read

    Returns:
        tuple[list[dict[str, Any]], int]: Entries shaped ``{"name": <type label>, "count": <int>}``
            and the exact total number of CmdbObjects
    """
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

    counts_by_type, total_count = objects_manager.count_objects_grouped_by_type_with_total()

    if not counts_by_type:
        return [], total_count

    types_lookup: dict[int, CmdbType] = types_manager.get_types_lookup(list(counts_by_type.keys()))

    type_counts: list[dict[str, Any]] = []

    for type_id, count in counts_by_type.items():
        object_type: CmdbType | None = types_lookup.get(type_id)

        if object_type is None:
            continue

        type_counts.append({
            ConfigItemTypeCountKey.NAME.value: object_type.label,
            ConfigItemTypeCountKey.COUNT.value: count,
        })

    return type_counts, total_count


def handle_sync_config_item_count(request_user: CmdbUser) -> None:
    """
    Syncs the current ConfigItem count, with its per-type breakdown, to the DataGerry service portal

    Only on a hosted cloud installation (``is_hosted_cloud``); anywhere else nothing is read or sent. The portal's
    configuration is checked first, so a tenant without one costs no count read. The total and the breakdown come
    from one aggregation (``build_type_object_counts``). Best-effort: a missing portal configuration
    (``NoAccessTokenError``), a failed count read (``COUNT_READ_ERRORS``) and a failed request (handled by
    ``sync_config_items``) are logged and the sync skipped. A programming error is not caught

    Args:
        request_user (CmdbUser): The CmdbUser whose write changed the count; names the tenant to the portal
    """
    if not is_hosted_cloud():
        return

    try:
        portal: DgServicePortalManager = DgServicePortalManager()
    except NoAccessTokenError as err:
        LOGGER.error("[handle_sync_config_item_count] The service portal is not configured, sync skipped: %s", err)
        return

    try:
        type_counts, total_count = build_type_object_counts(request_user)
    except COUNT_READ_ERRORS as err:
        LOGGER.error("[handle_sync_config_item_count] Could not count the ConfigItems, sync skipped: %s", err)
        return

    portal.sync_config_items(request_user, total_count, type_counts)
