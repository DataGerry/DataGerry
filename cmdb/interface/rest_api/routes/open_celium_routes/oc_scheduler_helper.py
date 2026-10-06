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
Helper methods shared by the OpenCelium Scheduler (Automation) REST routes
"""
from dataclasses import dataclass
from logging import Logger, getLogger
from typing import Any, Callable

from flask import abort

from cmdb.manager import CachedUserManager, DgServicePortalManager, OcConnectionManager, OcSchedulerManager
from cmdb.open_celium import map_oc_name
from cmdb.open_celium import CachedOcIdType, unmap_oc_name, is_hosted_cloud

from cmdb.models.user_model import CmdbUser
from cmdb.interface.route_utils import get_cached_user_manager
from cmdb.interface.rest_api.routes.open_celium_routes.oc_subscription_helper import (
    oc_id_in_subscription,
    read_or_seed_cached_user,
)
from cmdb.framework.write_ledger import WriteLedger
from cmdb.interface.rest_api.routes.routes_helper import undone_on_failure
from cmdb.interface.rest_api.routes.open_celium_routes.oc_routes_constants import (
    OPEN_CELIUM_SERVICE,
    SERVICE_PORTAL,
    OcAutomationMessage,
    OcResponseKey,
)

from cmdb.errors.dg_service_portal import DgServicePortalSaveError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)


def assert_scheduler_access(request_user: CmdbUser, scheduler_id: int) -> None:
    """
    In cloud mode, asserts the given Automation (scheduler) belongs to the requesting user

    The scheduler case of ``oc_id_in_subscription``: the user's cache entry is read (seeded from the DataGerry
    Service Portal once on a miss) and the id looked up in it. On-premise this is a no-op (there is no per-tenant
    OpenCelium id mapping). Consolidates the cache-first access check the
    scheduler read / execute / update routes each performed inline.

    Args:
        request_user (CmdbUser): The user making the request
        scheduler_id (int): The schedulerId to validate access for

    Raises:
        HTTPException: 400 when the scheduler is not accessible to the requesting user
    """
    if not is_hosted_cloud():
        return

    is_valid: bool = oc_id_in_subscription(
        request_user, CachedOcIdType.SCHEDULERS, scheduler_id, get_cached_user_manager(), DgServicePortalManager(),
    )

    if not is_valid:
        abort(400, f"The target Automation with ID:{scheduler_id} was not found!")


def get_accessible_scheduler_ids(request_user: CmdbUser) -> list[int] | None:
    """
    Returns the OpenCelium scheduler ids visible to the requesting user (cloud mode)

    Reads the ids from the user's cache entry (seeded from the DataGerry Service Portal once on a miss), and asks
    the portal for the id list only when it knows no such user either. Consolidates the cache-first id-list
    lookup the scheduler list / running-list routes each performed inline.

    Args:
        request_user (CmdbUser): The user whose accessible scheduler ids are resolved

    Returns:
        list[int] | None: The accessible scheduler ids, or None/empty when the user has none
    """
    cached_user_manager = get_cached_user_manager()
    dg_sp_manager = DgServicePortalManager()

    cached_user = read_or_seed_cached_user(cached_user_manager, dg_sp_manager, request_user.email)

    if cached_user:
        return cached_user_manager.get_oc_ids(
            cached_user,
            request_user.database,
            CachedOcIdType.SCHEDULERS,
        )

    return dg_sp_manager.get_scheduler_ids(request_user.email, request_user.database)


def unmap_scheduler_titles(scheduler: dict[str, Any]) -> None:
    """
    Strips the tenant prefix from a scheduler's title and its connection/connector titles (in place)

    Shared by the scheduler read-list and update routes, which return the same nested shape
    (`scheduler.title`, `scheduler.connection.title` and the two connector titles).

    Args:
        scheduler (dict[str, Any]): A scheduler dict with a nested `connection` and its connectors
    """
    scheduler[OcResponseKey.TITLE.value] = unmap_oc_name(scheduler[OcResponseKey.TITLE.value])

    connection = scheduler[OcResponseKey.CONNECTION.value]
    connection[OcResponseKey.TITLE.value] = unmap_oc_name(connection[OcResponseKey.TITLE.value])

    from_connector = connection[OcResponseKey.FROM_CONNECTOR.value]
    from_connector[OcResponseKey.TITLE.value] = unmap_oc_name(from_connector[OcResponseKey.TITLE.value])

    to_connector = connection[OcResponseKey.TO_CONNECTOR.value]
    to_connector[OcResponseKey.TITLE.value] = unmap_oc_name(to_connector[OcResponseKey.TITLE.value])


def record_remote_create(ledger: WriteLedger, service: str, description: str, delete: Callable[[], bool]) -> None:
    """
    Records an object just created in a remote service, undone by deleting it again

    OpenCelium and the Service Portal answer a delete with a bool, and a remote object cannot be read back the way a
    MongoDB document can, so the delete's own answer is what the undo is verified by: the undo remembers whether the
    service acknowledged the delete, and the verification reports exactly that. A delete that raises or is refused
    leaves the object in the ledger's residue, named by ``description``

    Args:
        ledger (WriteLedger): The request's ledger
        service (str): The service the object lives in, as the residue names it
        description (str): What was created, as the residue names it - with its id
        delete (Callable[[], bool]): Deletes the object; True when the service acknowledged it
    """
    acknowledged: dict[str, bool] = {'deleted': False}

    def undo() -> None:
        acknowledged['deleted'] = bool(delete())

    ledger.compensated(service, description, undo=undo, verify=lambda: acknowledged['deleted'])


def require_portal_registration(registered: bool, what: str) -> None:
    """
    Refuses to carry on when the Service Portal did not acknowledge an id DataGerry registered with it

    The portal's save calls answer a bool. Stepping over a False registers nothing while the request carries on - the
    created OpenCelium object then sits outside the user's subscription, refused by every later subscription check

    Args:
        registered (bool): What the portal's save call answered
        what (str): The id that was registered, for the error

    Raises:
        DgServicePortalSaveError: When the portal did not acknowledge the registration
    """
    if not registered:
        raise DgServicePortalSaveError(f"The Service Portal did not register {what}")


def read_automation_body(params: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Reads the connection and scheduler parts of an Automation create, refusing what the create cannot use

    Both titles are checked here, before anything is written: the scheduler's is read only after the connection
    exists, so a missing one used to fail the request with the connection already created

    Args:
        params (Any): The parsed JSON body

    Raises:
        HTTPException: 400 when ``connection`` or ``scheduler`` is missing, or either carries no ``title``

    Returns:
        tuple[dict[str, Any], dict[str, Any]]: The connection data and the scheduler data
    """
    params = params if isinstance(params, dict) else {}

    if not params.get(OcResponseKey.CONNECTION.value):
        abort(400, "No 'connection' data provided to create the Automation!")

    if not params.get(OcResponseKey.SCHEDULER.value):
        abort(400, "No 'scheduler' data provided to create the Automation!")

    conn_data: dict[str, Any] = params[OcResponseKey.CONNECTION.value]
    sched_data: dict[str, Any] = params[OcResponseKey.SCHEDULER.value]

    if not conn_data.get(OcResponseKey.TITLE.value):
        abort(400, OcAutomationMessage.NO_CONNECTION_TITLE.value)

    if not sched_data.get(OcResponseKey.TITLE.value):
        abort(400, OcAutomationMessage.NO_SCHEDULER_TITLE.value)

    return conn_data, sched_data


@dataclass(frozen=True)
class AutomationWriters:
    """
    The managers an Automation create writes through; the two cloud ones are None on-premise

    Attributes:
        connections (OcConnectionManager): Creates and deletes the OpenCelium connection
        schedulers (OcSchedulerManager): Creates and deletes the OpenCelium scheduler
        portal (DgServicePortalManager | None): Registers and unregisters both ids (cloud mode)
        cache (CachedUserManager | None): Evicts the user's entry once its ids are stale (cloud mode)
    """
    connections: OcConnectionManager
    schedulers: OcSchedulerManager
    portal: DgServicePortalManager | None
    cache: CachedUserManager | None


def create_automation(
        writers: AutomationWriters,
        request_user: CmdbUser,
        conn_data: dict[str, Any],
        sched_data: dict[str, Any]) -> dict[str, Any]:
    """
    Creates an Automation's connection and scheduler - and, in cloud mode, registers both ids - all or nothing

    Every remote write is recorded in a WriteLedger as it succeeds (``record_remote_create``); when a later step
    fails, the ones already made are deleted again newest first - scheduler id, scheduler, connection id, connection,
    the order the delete route uses - and the original error is re-raised for the route to answer. A portal
    registration the portal does not acknowledge is such a failure (``require_portal_registration``). An undo that
    cannot finish aborts 500 naming what it left behind (``OcAutomationMessage.RESIDUE``)

    Args:
        writers (AutomationWriters): The managers to write through
        request_user (CmdbUser): The user creating it; email and database scope the portal registrations
        conn_data (dict[str, Any]): The connection, its title already mapped in cloud mode
        sched_data (dict[str, Any]): The scheduler; its connectionId is set here, its title mapped in cloud mode

    Raises:
        OcConnectionCreateError / OcSchedulerCreateError: When OpenCelium refuses a create (after the undo)
        DgServicePortalSaveError: When the portal does not acknowledge a registration (after the undo)
        HTTPException: 500 when the undo left something behind

    Returns:
        dict[str, Any]: The created scheduler, as OpenCelium answered it
    """
    email: str = request_user.email
    database: str = request_user.database

    with undone_on_failure(OcAutomationMessage.RESIDUE.value) as ledger:
        connection_id: int = writers.connections.create_connection(conn_data)[OcResponseKey.CONNECTION_ID.value]
        record_remote_create(ledger, OPEN_CELIUM_SERVICE, f"connection {connection_id}",
                             lambda: writers.connections.delete_connection(connection_id))

        if writers.portal:
            require_portal_registration(writers.portal.save_connection_id(connection_id, email, database),
                                        f"connection {connection_id}")
            record_remote_create(ledger, SERVICE_PORTAL, f"connectionId {connection_id}",
                                 lambda: writers.portal.delete_connection_id(connection_id, email, database))
            # The cached OpenCelium ids are stale now
            writers.cache.delete_cached_user(email)

        sched_data[OcResponseKey.CONNECTION_ID.value] = connection_id

        if writers.portal:
            sched_data[OcResponseKey.TITLE.value] = map_oc_name(database, sched_data[OcResponseKey.TITLE.value])

        created_scheduler: dict[str, Any] = writers.schedulers.create_scheduler(sched_data)
        scheduler_id: int = created_scheduler[OcResponseKey.SCHEDULER_ID.value]
        record_remote_create(ledger, OPEN_CELIUM_SERVICE, f"scheduler {scheduler_id}",
                             lambda: writers.schedulers.delete_scheduler(scheduler_id))

        if writers.portal:
            require_portal_registration(writers.portal.save_scheduler_id(scheduler_id, email, database),
                                        f"scheduler {scheduler_id}")
            record_remote_create(ledger, SERVICE_PORTAL, f"schedulerId {scheduler_id}",
                                 lambda: writers.portal.delete_scheduler_id(scheduler_id, email, database))
            writers.cache.delete_cached_user(email)

    return created_scheduler
