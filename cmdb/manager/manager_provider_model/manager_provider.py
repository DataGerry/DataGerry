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
Central wiring point that hands a ready-to-use manager to a stateless API route

A route never constructs a manager itself: it asks `ManagerProvider.get_manager(ManagerType.X,
request_user)` and gets back an instance already bound to the right database. That indirection
exists for one reason - **cloud mode**. In local mode every manager talks to the single database
the `MongoDatabaseManager` was built with; in cloud mode each request is served against the
requesting user's own tenant database, and the provider is the one place that decides which

What the registry actually holds
--------------------------------
`MANAGER_CLASSES` maps a `ManagerType` to a class constructible as `Cls(dbm)` (local mode) or
`Cls(dbm, database)` (cloud mode). That contract - not "subclasses `BaseManager`" - is the real
membership rule, which is why `SecurityManager`, `SettingsManager` and `LicenseService` belong
here despite not being `BaseManager`/`GenericManager` subclasses. A manager that needs no
database handle (e.g. `RightsManager`) is constructed directly by its route and must NOT be
registered

Registering a new manager (three coordinated edits)
---------------------------------------------------
1. Export the class from `cmdb.manager` (its package `__init__`)
2. Add a `ManagerType` member whose value is the class name verbatim
3. Add the `ManagerType -> class` entry to `MANAGER_CLASSES` below

Nothing at import time enforces that the three stay in step - the unit tests for this module do:
they assert the map and the enum cover each other exactly, that every value equals its class
`__name__`, and that every registered class accepts both the local- and cloud-mode argument
shapes
"""
from logging import Logger, getLogger
from typing import Any

from flask import current_app

from cmdb.manager.manager_provider_model.manager_type_enum import ManagerType
from cmdb.manager import (
    CategoriesManager,
    CiExplorerProfileManager,
    DocapiTemplatesManager,
    LogsManager,
    UsersManager,
    GroupsManager,
    MediaFilesManager,
    TypesManager,
    LocationsManager,
    SectionTemplatesManager,
    ObjectsManager,
    ObjectRelationsManager,
    ObjectRelationLogsManager,
    RackMountsManager,
    PortsManager,
    PortConnectionsManager,
    PortInterfaceLinksManager,
    RelationsManager,
    SecurityManager,
    SettingsManager,
    ReportCategoriesManager,
    ReportsManager,
    WebhooksManager,
    WebhooksEventManager,
    RiskClassManager,
    LikelihoodManager,
    ImpactManager,
    ImpactCategoryManager,
    ProtectionGoalManager,
    RiskMatrixManager,
    ExtendableOptionsManager,
    ObjectGroupsManager,
    ThreatManager,
    VulnerabilityManager,
    UserSettingsManager,
    RiskManager,
    ControlMeasureManager,
    PersonsManager,
    PersonGroupsManager,
    RiskAssessmentManager,
    ControlMeasureAssignmentManager,
    LicenseActivationRequestsManager,
    ActiveLicenseManager,
    LicenseService,
)

from cmdb.models.user_model import CmdbUser

from cmdb.errors.manager import BaseManagerInitError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The single source of truth for "which class serves which ManagerType". Built once at import
# time rather than per call: `get_manager` is invoked on essentially every REST request (500+
# call sites), and rebuilding a 45-entry dict literal each time cost ~60x the lookup it feeds
MANAGER_CLASSES: dict[ManagerType, Any] = {
    ManagerType.CATEGORIES: CategoriesManager,
    ManagerType.CI_EXPLORER_PROFILE: CiExplorerProfileManager,
    ManagerType.OBJECTS: ObjectsManager,
    ManagerType.LOGS: LogsManager,
    ManagerType.DOCAPI_TEMPLATES: DocapiTemplatesManager,
    ManagerType.USERS: UsersManager,
    ManagerType.USER_SETTINGS: UserSettingsManager,
    ManagerType.GROUPS: GroupsManager,
    ManagerType.MEDIA_FILES: MediaFilesManager,
    ManagerType.TYPES: TypesManager,
    ManagerType.LOCATIONS: LocationsManager,
    ManagerType.SECTION_TEMPLATES: SectionTemplatesManager,
    ManagerType.SETTINGS: SettingsManager,
    ManagerType.SECURITY: SecurityManager,
    ManagerType.REPORT_CATEGORIES: ReportCategoriesManager,
    ManagerType.REPORTS: ReportsManager,
    ManagerType.WEBHOOKS: WebhooksManager,
    ManagerType.WEBHOOKS_EVENT: WebhooksEventManager,
    ManagerType.RELATIONS: RelationsManager,
    ManagerType.OBJECT_RELATIONS: ObjectRelationsManager,
    ManagerType.RACK_MOUNTS: RackMountsManager,
    ManagerType.PORTS: PortsManager,
    ManagerType.PORT_CONNECTIONS: PortConnectionsManager,
    ManagerType.PORT_INTERFACE_LINKS: PortInterfaceLinksManager,
    ManagerType.OBJECT_RELATION_LOGS: ObjectRelationLogsManager,
    ManagerType.RISK_CLASS: RiskClassManager,
    ManagerType.LIKELIHOOD: LikelihoodManager,
    ManagerType.IMPACT: ImpactManager,
    ManagerType.IMPACT_CATEGORY: ImpactCategoryManager,
    ManagerType.PROTECTION_GOAL: ProtectionGoalManager,
    ManagerType.RISK_MATRIX: RiskMatrixManager,
    ManagerType.EXTENDABLE_OPTIONS: ExtendableOptionsManager,
    ManagerType.OBJECT_GROUP: ObjectGroupsManager,
    ManagerType.THREAT: ThreatManager,
    ManagerType.VULNERABILITY: VulnerabilityManager,
    ManagerType.RISK: RiskManager,
    ManagerType.CONTROL_MEASURE: ControlMeasureManager,
    ManagerType.PERSON: PersonsManager,
    ManagerType.PERSON_GROUP: PersonGroupsManager,
    ManagerType.RISK_ASSESSMENT: RiskAssessmentManager,
    ManagerType.CONTROL_MEASURE_ASSIGNMENT: ControlMeasureAssignmentManager,
    ManagerType.LICENSE_ACTIVATION_REQUESTS: LicenseActivationRequestsManager,
    ManagerType.ACTIVE_LICENSE: ActiveLicenseManager,
    ManagerType.LICENSE_SERVICE: LicenseService,
}

# -------------------------------------------------------------------------------------------------------------------- #
#                                                ManagerProvider - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class ManagerProvider:
    """
    Provides Managers for stateless API route requests

    Stateless is the operative word: nothing is cached between calls, so every route gets a fresh
    instance bound to the database that is correct for *this* request's user. See the module
    docstring for the registry contract and how to register a new manager
    """

    @classmethod
    def get_manager(cls, manager_type: ManagerType, request_user: CmdbUser | None) -> Any:
        """
        Retrieves a manager based on the provided ManagerType and 'cloud_mode' app flag

        Must be called inside a Flask application context: the database handle and the cloud-mode
        flag are both read off `current_app`

        Args:
            manager_type (ManagerType): Enum of available Managers
            request_user (CmdbUser | None): The user which is requesting the manager. May only be
                None in local mode, where the user does not select the database. In cloud mode a
                user is required because it carries the tenant database name

        Returns:
            Any: An instance of the manager class registered for the provided ManagerType

        Raises:
            BaseManagerInitError: If the ManagerType is not registered in MANAGER_CLASSES, or if
                cloud mode is active and no request_user was given
        """
        manager_class: Any | None = MANAGER_CLASSES.get(manager_type)

        if manager_class is None:
            LOGGER.error("[get_manager] No manager found for ManagerType: %s", manager_type)
            raise BaseManagerInitError(f"Invalid ManagerType {manager_type!r}")

        manager_args: tuple[Any, ...] = cls.__get_manager_args(request_user)

        return manager_class(*manager_args)


    @staticmethod
    def __get_manager_args(request_user: CmdbUser | None) -> tuple[Any, ...]:
        """
        Returns the positional arguments a registered manager class is constructed from

        Local mode passes the process-wide database handle alone; cloud mode appends the database
        of the requesting user, which is what routes the call to that user's tenant

        Args:
            request_user (CmdbUser | None): The user which is making the API call. Required in
                cloud mode, ignored in local mode

        Returns:
            tuple[Any, ...]: Arguments for the manager class initialisation - `(dbm,)` in local
                mode, `(dbm, database)` in cloud mode

        The tenant name is refused when it is falsy, not defaulted. `BaseManager` binds to
        `dbm.db_name` for a None or empty `db_name`, so letting one through would silently serve a
        cloud user out of the process-wide database - another tenant's - instead of failing. The
        stored `database` may legitimately be absent (the schema allows null) which is exactly why
        the check is here, where cloud mode is known

        Raises:
            BaseManagerInitError: If cloud mode is active and no request_user was given, or the
                request_user carries no usable database name - in both cases there is no tenant
                database to bind the manager to
        """
        common_args: tuple[Any, ...] = (current_app.database_manager,)

        if current_app.cloud_mode:
            if request_user is None:
                LOGGER.error("[__get_manager_args] No request_user provided while in cloud mode!")
                raise BaseManagerInitError("A request user is required to select the database in cloud mode")

            if not request_user.database:
                LOGGER.error(
                    "[__get_manager_args] CmdbUser ID:%s carries no database while in cloud mode!",
                    request_user.public_id,
                )
                raise BaseManagerInitError(
                    f"The request user (ID: {request_user.public_id}) has no database to select in cloud mode"
                )

            return common_args + (request_user.database,)

        return common_args
