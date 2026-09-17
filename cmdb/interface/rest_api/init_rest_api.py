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
Builds the REST API Flask application and wires all blueprints, error handlers, URL converters
and startup hooks into it

This module is the entry point used by the WSGI dispatcher (``cmdb.interface.dispatcher_middleware``)
to mount the ``/rest`` sub-application. ``create_rest_api`` is the single public factory; it
constructs a ``BaseCmdbApp``, applies the mode-specific Flask config (DEBUG / TESTING / production),
enables CORS, registers the regex URL converter, all blueprints and the HTTP error handlers, and -
outside TESTING - kicks off the appropriate startup routine for the current cloud / local / on-prem
mode (collection validation followed by pending database updates)
"""
from logging import Logger, getLogger
import sys

from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_services import (
    get_db_names_from_service_portal,
    CollectionValidator,
    DatabaseUpdater,
)

import cmdb
from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.interface.config import app_config, config_name_for_mode
from cmdb.interface.custom_converters import RegexConverter
from cmdb.interface.rest_api.routes.cmdb_license.license_guard import enforce_rest_api_license
from cmdb.interface.rest_api.responses.error_handlers import http_exception

from cmdb.manager.system_manager.system_config_reader import SystemConfigReader
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

#: Where DispatcherMiddleware mounts this app (see `cmdb.interface.gunicorn`). Flask reads
#: APPLICATION_ROOT for SERVER_NAME-based URL building and as the session-cookie path default
REST_APPLICATION_ROOT: str = '/rest/'

# -------------------------------------------------------------------------------------------------------------------- #


def create_rest_api(database_manager: MongoDatabaseManager) -> BaseCmdbApp:
    """
    Builds and returns the fully configured REST API Flask application

    Constructs a ``BaseCmdbApp`` bound to the given database manager, picks the Flask config
    profile based on ``cmdb.__MODE__`` (DEBUG, TESTING, or production), enables CORS, registers
    URL converters, blueprints and error handlers, and - unless running under TESTING - executes
    the mode-appropriate setup routine (on-prem setup, cloud update checks, or local-mode update
    checks). A failure inside that startup routine is logged and terminates the process via
    ``sys.exit(1)`` so the supervising ``ProcessManager`` does not bring up an
    incompletely-initialised API. In cloud mode that means one tenant database failing its update
    aborts startup for **every** tenant - see discussion-backlog #156

    **CORS is unrestricted.** Only ``expose_headers`` is configured; flask-cors' defaults apply for
    everything else, so any origin may call the API with any of the standard methods. That is not a
    session-riding hole - DataGerry authenticates with a Bearer JWT in a header rather than a cookie,
    and ``supports_credentials`` stays False, so a foreign origin has no token to ride - but it does
    mean an operator cannot restrict origins for a hardened deployment. Recorded as
    discussion-backlog #157

    Args:
        database_manager (MongoDatabaseManager): Manager that owns the MongoDB connection
            used by every blueprint and by the startup routines

    Returns:
        BaseCmdbApp: The ready-to-serve Flask application

    Raises:
        SystemExit: When the startup routine fails outside TESTING mode
    """
    app = BaseCmdbApp(__name__, database_manager=database_manager, static_folder=None)
    app.url_map.strict_slashes = True

    # Import App Extensions
    CORS(app=app, expose_headers=['X-API-Version', 'X-Total-Count'])

    # Lock the external REST API (HTTP Basic auth) behind the REST_API license feature. On-premise
    # only; a no-op in cloud/local mode. The UI (login + Bearer JWT) is unaffected.
    app.before_request(enforce_rest_api_license)

    app.config.from_object(app_config[config_name_for_mode(cmdb.__MODE__)])

    # The mount point belongs to whoever knows it. DispatcherMiddleware mounts this app at /rest,
    # so it is set here rather than on the shared Config class - where it also reached the SPA host,
    # which is mounted at /
    app.config['APPLICATION_ROOT'] = REST_APPLICATION_ROOT

    with app.app_context():
        register_converters(app)
        register_error_pages(app)
        register_blueprints(app)

        if cmdb.__MODE__ != 'TESTING':
            try:
                LOGGER.info("Starting DataGerry Routine!")

                if not cmdb.__CLOUD_MODE__:
                    start_datagerry_setup(database_manager)
                elif not cmdb.__LOCAL_MODE__:
                    # Check for updates in __CLOUD_MODE__
                    execute_update_checks(database_manager)
                else:
                    # LOCAL_MODE
                    execute_update_checks(database_manager, local_mode=True)
            except Exception as err:
                LOGGER.error(
                    "Initialisation of DataGerry failed. Exception: %s. Type: %s", err, type(err), exc_info=True
                )
                sys.exit(1)

    return app


def register_converters(app: BaseCmdbApp):
    """
    Registers the ``regex`` URL converter on the Flask app's URL map

    The converter lets route patterns embed an arbitrary Python regex, e.g.
    ``/<regex("[a-z0-9]{8}"):token>``. It is consumed by blueprints that need parameter
    validation beyond what Werkzeug's built-in converters offer

    Args:
        app (BaseCmdbApp): The Flask app whose URL map is being extended
    """
    app.url_map.converters['regex'] = RegexConverter


# pylint: disable=R0914, R0915
def register_blueprints(app: BaseCmdbApp) -> None:
    """
    Mounts every feature-area blueprint on the Flask app with its URL prefix

    Imports are intentionally local to keep module import time low and to break import cycles
    between blueprints and the manager layer. Blueprints are grouped by domain (auth, framework,
    user management, ISMS, IPAM, OpenCelium, ...) and registered under stable URL prefixes such
    as ``/objects``, ``/isms/risks`` or ``/ipam/subnet`` that the frontend depends on

    **Every mount point is declared here**, so this list is the single source of truth for the URL
    map. Four blueprints also carry a ``url_prefix`` on their own ``APIBlueprint(...)`` constructor;
    the value passed here is identical and takes precedence, so the prefix is readable without
    opening the route module. ``connection_routes`` is the one blueprint mounted at the ``/rest``
    root and therefore takes no prefix

    Some registrations are order-sensitive: ``gate_blueprint`` installs a ``before_request`` hook,
    which Flask only propagates to a blueprint registered *after* the hook was attached, so the
    licensed feature groups (ISMS, IPAM, OpenCelium and the OpenCelium-scoped config-file route)
    are gated first and registered immediately afterwards

    Pylint rules R0914 (too many locals) and R0915 (too many statements) are disabled because the
    registration list is intentionally flat for readability; splitting it per domain is recorded as
    discussion-backlog #158

    Args:
        app (BaseCmdbApp): Flask app the blueprints are mounted on
    """
    # pylint: disable=import-outside-toplevel
    from cmdb.interface.rest_api.routes.auth_routes import auth_blueprint
    from cmdb.interface.rest_api.routes.setup_routes.setup_routes import setup_blueprint
    from cmdb.interface.rest_api.routes.settings_routes.date_routes import date_blueprint
    from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_routes import objects_blueprint
    from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_routes import types_blueprint
    from cmdb.interface.rest_api.routes.connection import connection_routes
    from cmdb.interface.rest_api.routes.framework_routes.cmdb_categories.categories_routes import categories_blueprint
    from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_routes import location_blueprint
    from cmdb.interface.rest_api.routes.framework_routes.cmdb_section_templates.section_template_routes import (
        section_template_blueprint,
    )
    from cmdb.interface.rest_api.routes.user_management_routes.users_routes import users_blueprint
    from cmdb.interface.rest_api.routes.user_management_routes.user_settings_routes import user_settings_blueprint
    from cmdb.interface.rest_api.routes.user_management_routes.cmdb_groups.groups_routes import groups_blueprint
    from cmdb.interface.rest_api.routes.user_management_routes.rights_routes import rights_blueprint
    from cmdb.interface.rest_api.routes.framework_routes.search_routes import search_blueprint
    from cmdb.interface.rest_api.routes.exporter_routes.exporter_object_routes import exporter_blueprint
    from cmdb.interface.rest_api.routes.exporter_routes.exporter_type_routes import exporter_type_blueprint
    from cmdb.interface.rest_api.routes.framework_routes.cmdb_logs import logs_blueprint
    from cmdb.interface.rest_api.routes.settings_routes.system_routes import system_blueprint
    from cmdb.interface.rest_api.routes.importer_routes.importer_type_routes import importer_type_blueprint
    from cmdb.interface.rest_api.routes.importer_routes.importer_object_routes import importer_object_blueprint
    from cmdb.interface.rest_api.routes.framework_routes.cmdb_docapi_templates.docapi_template_routes import (
        docapi_blueprint,
        docs_blueprint,
    )
    from cmdb.interface.rest_api.routes.media_library_routes.media_file_routes import media_file_blueprint
    from cmdb.interface.rest_api.routes.framework_routes.special_routes import special_blueprint
    from cmdb.interface.rest_api.routes.report_routes.report_category_routes import report_categories_blueprint
    from cmdb.interface.rest_api.routes.report_routes.report_routes import reports_blueprint
    from cmdb.interface.rest_api.routes.webhook_routes.webhook_routes import webhook_blueprint
    from cmdb.interface.rest_api.routes.webhook_routes.webhook_event_routes import webhook_event_blueprint
    from cmdb.interface.rest_api.routes.relation_routes.relations_routes import relations_blueprint
    from cmdb.interface.rest_api.routes.relation_routes.object_relation_routes import object_relations_blueprint
    from cmdb.interface.rest_api.routes.rack_routes.rack_mount_routes import rack_mounts_blueprint
    from cmdb.interface.rest_api.routes.rack_routes.rack_assignable_routes import rack_assignable_blueprint
    from cmdb.interface.rest_api.routes.port_routes import (
        port_blueprint,
        port_bulk_blueprint,
        port_interface_link_blueprint,
        port_preview_blueprint,
    )
    from cmdb.interface.rest_api.routes.port_connection_routes import port_connection_blueprint
    from cmdb.interface.rest_api.routes.log_routes.object_relation_logs_routes import object_relation_logs_blueprint
    from cmdb.interface.rest_api.routes.user_management_routes.persons_routes import person_blueprint
    from cmdb.interface.rest_api.routes.user_management_routes.person_groups_routes import person_group_blueprint
    from cmdb.interface.rest_api.routes.importer_routes.importer_isms_routes import isms_importer_blueprint
    from cmdb.interface.rest_api.routes.ci_explorer_routes.ci_explorer_routes import ci_explorer_blueprint
    from cmdb.interface.rest_api.routes.config_routes.config_file_routes import config_file_blueprint
    from cmdb.interface.rest_api.routes.ai_routes.chatgpt_routes import chatgpt_blueprint
    from cmdb.interface.rest_api.routes.framework_routes import (
        extendable_option_blueprint,
        object_group_blueprint,
    )
    from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.special_type_routes import special_types_blueprint
    from cmdb.interface.rest_api.routes.isms_routes import (
        risk_class_blueprint,
        likelihood_blueprint,
        impact_blueprint,
        impact_category_blueprint,
        protection_goal_blueprint,
        risk_matrix_blueprint,
        isms_config_blueprint,
        threat_blueprint,
        vulnerability_blueprint,
        risk_blueprint,
        control_measure_blueprint,
        risk_assessment_blueprint,
        control_measure_assignment_blueprint,
        isms_report_blueprint,
    )
    from cmdb.interface.rest_api.routes.open_celium_routes import (
        oc_connectors_blueprint,
        oc_invokers_blueprint,
        oc_templates_blueprint,
        oc_connections_blueprint,
        oc_schedulers_blueprint,
        oc_licenses_blueprint,
        oc_connection_log_blueprint
    )
    from cmdb.interface.rest_api.routes.ipam_routes.ipam_validation_routes import ipam_validation_blueprint
    from cmdb.interface.rest_api.routes.ipam_routes.ipam_supernet_routes import ipam_supernet_blueprint
    from cmdb.interface.rest_api.routes.ipam_routes.ipam_subnet_routes import ipam_subnet_blueprint
    from cmdb.interface.rest_api.routes.ipam_routes.ipam_assignable_routes import ipam_assignable_blueprint
    from cmdb.interface.rest_api.routes.ipam_routes.ipam_tree_routes import ipam_tree_blueprint
    from cmdb.interface.rest_api.routes.cmdb_license import license_activation_blueprint, license_blueprint

    app.register_blueprint(auth_blueprint, url_prefix='/auth')

    # CLOUD ONLY, and the registration is the whole guard. These three routes exist for the DataGerry
    # Service Portal to tear down a tenant - drop its database, evict it from the user cache - and an
    # on-premise installation has no portal, no subscriptions and nothing to tear down.
    #
    # They carry no `@insert_request_user` and no `.protect`; their only decorator is
    # `verify_api_access`, which returns immediately when the process is not in cloud mode. So
    # registering them on-premise published an UNAUTHENTICATED `DELETE /rest/setup/subscriptions?
    # database=<name>` that drops any database on the cluster - verified against the running app.
    # Not registering them is what closes that, and it changes nothing for the portal.
    if cmdb.__CLOUD_MODE__:
        app.register_blueprint(setup_blueprint, url_prefix='/setup')

    app.register_blueprint(date_blueprint, url_prefix='/date')
    app.register_blueprint(objects_blueprint, url_prefix='/objects')
    app.register_blueprint(types_blueprint, url_prefix='/types')
    app.register_blueprint(special_types_blueprint, url_prefix='/special_types')
    # Mounted at the /rest root itself: '/' is the frontend's connection probe and
    # '/frontend_init' its runtime config, so this blueprint carries no prefix
    app.register_blueprint(connection_routes)
    app.register_blueprint(categories_blueprint, url_prefix='/categories')
    app.register_blueprint(location_blueprint, url_prefix='/locations')
    app.register_blueprint(section_template_blueprint, url_prefix='/section_templates')
    app.register_blueprint(users_blueprint, url_prefix='/users')
    app.register_blueprint(user_settings_blueprint, url_prefix='/users/<int:user_id>/settings')
    app.register_blueprint(groups_blueprint, url_prefix='/groups')
    app.register_blueprint(rights_blueprint, url_prefix='/rights')
    app.register_blueprint(search_blueprint, url_prefix='/search')
    app.register_blueprint(exporter_blueprint, url_prefix='/exporter')
    app.register_blueprint(exporter_type_blueprint, url_prefix='/export/type')
    app.register_blueprint(logs_blueprint, url_prefix='/logs')
    app.register_blueprint(system_blueprint, url_prefix='/settings/system')
    app.register_blueprint(importer_type_blueprint, url_prefix='/import/type')
    app.register_blueprint(importer_object_blueprint, url_prefix='/import/object')
    app.register_blueprint(docapi_blueprint, url_prefix='/docapi')
    app.register_blueprint(docs_blueprint, url_prefix='/docs')
    app.register_blueprint(media_file_blueprint, url_prefix='/media_file')
    app.register_blueprint(special_blueprint, url_prefix='/special')
    app.register_blueprint(report_categories_blueprint, url_prefix='/report_categories')
    app.register_blueprint(reports_blueprint, url_prefix='/reports')
    app.register_blueprint(webhook_blueprint, url_prefix='/webhooks')
    app.register_blueprint(webhook_event_blueprint, url_prefix='/webhook_events')
    app.register_blueprint(relations_blueprint, url_prefix='/relations')
    app.register_blueprint(object_relations_blueprint, url_prefix='/object_relations')
    app.register_blueprint(object_relation_logs_blueprint, url_prefix='/object_relation_logs')
    app.register_blueprint(extendable_option_blueprint, url_prefix='/extendable_options')
    app.register_blueprint(ci_explorer_blueprint, url_prefix='/ci_explorer')
    app.register_blueprint(chatgpt_blueprint, url_prefix='/chatgpt')

    # Feature-gating guard, shared by the ISMS and OpenCelium blueprint locks below
    from cmdb.interface.rest_api.routes.cmdb_license.license_guard import gate_blueprint
    from cmdb.security.license.license_constants import LicenseFeature

    # ISMS Blueprints. The whole ISMS module is a licensed feature, so every route (all methods,
    # reads included) is gated on-premise. Gating is registered before the blueprints so all
    # current and future ISMS routes are covered.
    for isms_blueprint in (
        isms_config_blueprint,
        risk_class_blueprint,
        likelihood_blueprint,
        impact_blueprint,
        impact_category_blueprint,
        protection_goal_blueprint,
        risk_matrix_blueprint,
        threat_blueprint,
        vulnerability_blueprint,
        risk_blueprint,
        control_measure_blueprint,
        risk_assessment_blueprint,
        control_measure_assignment_blueprint,
        isms_importer_blueprint,
        isms_report_blueprint,
    ):
        gate_blueprint(isms_blueprint, LicenseFeature.ISMS)

    # Persons, Person Groups and Object Groups are shared entities the ISMS feature depends on
    # (risk-assessment responsible/interviewed persons and risk owner; the object group is the risk
    # scope). On-premise they are part of the licensed ISMS surface, so their HTTP routes are gated
    # behind the ISMS feature too. They keep their own top-level url_prefixes (not moved under
    # /isms/) so the frontend contract is unchanged. The internal object-delete cascade
    # (objects_side_effects_helper.handle_delete_from_object_groups) calls ObjectGroupsManager directly
    # than these routes, so it is unaffected by the gate. Gated before registration so the
    # before_request guard binds (Flask runs a blueprint's deferred setup at registration time).
    for isms_shared_blueprint in (
        object_group_blueprint,
        person_blueprint,
        person_group_blueprint,
    ):
        gate_blueprint(isms_shared_blueprint, LicenseFeature.ISMS)

    app.register_blueprint(object_group_blueprint, url_prefix='/object_groups')
    app.register_blueprint(person_blueprint, url_prefix='/persons')
    app.register_blueprint(person_group_blueprint, url_prefix='/person_groups')

    # ISMS Blueprints
    app.register_blueprint(isms_config_blueprint, url_prefix='/isms/config')
    app.register_blueprint(risk_class_blueprint, url_prefix='/isms/risk_classes')
    app.register_blueprint(likelihood_blueprint, url_prefix='/isms/likelihoods')
    app.register_blueprint(impact_blueprint, url_prefix='/isms/impacts')
    app.register_blueprint(impact_category_blueprint, url_prefix='/isms/impact_categories')
    app.register_blueprint(protection_goal_blueprint, url_prefix='/isms/protection_goals')
    app.register_blueprint(risk_matrix_blueprint, url_prefix='/isms/risk_matrix')
    app.register_blueprint(threat_blueprint, url_prefix='/isms/threats')
    app.register_blueprint(vulnerability_blueprint, url_prefix='/isms/vulnerabilities')
    app.register_blueprint(risk_blueprint, url_prefix='/isms/risks')
    app.register_blueprint(control_measure_blueprint, url_prefix='/isms/control_measures')
    app.register_blueprint(risk_assessment_blueprint, url_prefix='/isms/risk_assessments')
    app.register_blueprint(control_measure_assignment_blueprint, url_prefix='/isms/control_measure_assignments')
    app.register_blueprint(isms_importer_blueprint, url_prefix='/isms/importer')
    app.register_blueprint(isms_report_blueprint, url_prefix='/isms/reports')

    # Feature surfaces gated behind the licensed IPAM feature on-premise. The dedicated /ipam surface
    # (overviews, network tree, validation, assignable lookups) belongs to the feature outright; the
    # /racks surface (mounts, overview, assignable lookups) is gated behind it as an INTERIM decision
    # until the Rack View gets a LicenseFeature of its own - a Rack is NOT an IPAM type, see
    # SpecialType.get_license_gated_types. The data itself stays readable through the generic
    # /objects and /types routes (guarded separately at write time); only these dedicated surfaces
    # are locked here.
    for ipam_gated_blueprint in (
        ipam_validation_blueprint,
        ipam_supernet_blueprint,
        ipam_subnet_blueprint,
        ipam_assignable_blueprint,
        ipam_tree_blueprint,
        rack_mounts_blueprint,
        rack_assignable_blueprint,
        # The /ports and /port_connections surfaces belong to Port Connectivity, which is gated
        # behind IPAM by decision D6: a Type can not declare `uses_ports` without that licence
        # either, so a licensed-out installation has no ports to read and nothing to connect
        port_blueprint,
        port_interface_link_blueprint,
        port_preview_blueprint,
        port_bulk_blueprint,
        port_connection_blueprint,
    ):
        gate_blueprint(ipam_gated_blueprint, LicenseFeature.IPAM)

    # Registered here, AFTER the gate loop: gate_blueprint installs a before_request hook and Flask
    # runs a blueprint's deferred setup at registration time, so gating a blueprint that is already
    # registered silently does nothing.
    app.register_blueprint(rack_mounts_blueprint, url_prefix='/racks')
    app.register_blueprint(rack_assignable_blueprint, url_prefix='/racks')
    app.register_blueprint(port_blueprint, url_prefix='/ports')
    app.register_blueprint(port_interface_link_blueprint, url_prefix='/ports')
    app.register_blueprint(port_preview_blueprint, url_prefix='/ports')
    app.register_blueprint(port_bulk_blueprint, url_prefix='/ports')
    app.register_blueprint(port_connection_blueprint, url_prefix='/port_connections')

    # IPAM routes
    app.register_blueprint(ipam_validation_blueprint, url_prefix='/ipam/validate')
    app.register_blueprint(ipam_supernet_blueprint, url_prefix='/ipam/supernet')
    app.register_blueprint(ipam_subnet_blueprint, url_prefix='/ipam/subnet')
    app.register_blueprint(ipam_assignable_blueprint, url_prefix='/ipam/assignable-objects')
    app.register_blueprint(ipam_tree_blueprint, url_prefix='/ipam/tree')

    # License routes
    app.register_blueprint(license_activation_blueprint, url_prefix='/license')
    app.register_blueprint(license_blueprint, url_prefix='/license')

    # OpenCelium routes. The whole integration is the licensed "Automations" feature, so every
    # route is gated on-premise (OpenCelium's OWN license routes stay ungated). Gating is
    # registered before the blueprints so all current and future routes are covered.
    for oc_automations_blueprint in (
        oc_connectors_blueprint,
        oc_invokers_blueprint,
        oc_templates_blueprint,
        oc_connections_blueprint,
        oc_schedulers_blueprint,
        oc_connection_log_blueprint,
    ):
        gate_blueprint(oc_automations_blueprint, LicenseFeature.AUTOMATIONS)

    # The config-file status route only ever answers for the OpenCelium section and is consumed by
    # the Automations view alone, so it is gated with the routes it serves. Registered here, AFTER
    # the gate call, for the same reason as the IPAM blueprints above
    gate_blueprint(config_file_blueprint, LicenseFeature.AUTOMATIONS)
    app.register_blueprint(config_file_blueprint, url_prefix='/config_file')

    app.register_blueprint(oc_connectors_blueprint, url_prefix='/open_celium')
    app.register_blueprint(oc_invokers_blueprint, url_prefix='/open_celium')
    app.register_blueprint(oc_templates_blueprint, url_prefix='/open_celium')
    app.register_blueprint(oc_connections_blueprint, url_prefix='/open_celium')
    app.register_blueprint(oc_schedulers_blueprint, url_prefix='/open_celium')
    app.register_blueprint(oc_licenses_blueprint, url_prefix='/open_celium')
    app.register_blueprint(oc_connection_log_blueprint, url_prefix='/open_celium')


def register_error_pages(app: BaseCmdbApp) -> None:
    """
    Wires the REST API's single error handler, for every HTTP status there is

    ``http_exception`` is registered for the ``HTTPException`` **class**, so it answers the
    structured JSON body the frontend parses (``{description, message, response, status}``) for any
    status - the ones the route layer aborts, the ones Werkzeug raises while parsing a request, and
    the ones a future route invents. Flask routes an unhandled non-HTTP exception here too, having
    converted it to an ``InternalServerError`` first

    **It used to be a whitelist of nine codes** (400, 401, 403, 404, 405, 406, 410, 500, 503) and
    anything else fell through to Flask's HTML page, breaking the envelope for a client that reads
    ``message`` off it. That was reachable: **415 answered HTML on the running API**, because
    Werkzeug raises it before any route runs - so no ``abort()`` census could see it (tier 2 T135).
    Two of the nine (406 and 410) were never raised anywhere in ``cmdb/`` and were kept as defensive
    catches; under a class handler that reasoning is no longer needed

    Args:
        app (BaseCmdbApp): Flask app the error handler is attached to
    """
    app.register_error_handler(HTTPException, http_exception)


# -------------------------------------------------------------------------------------------------------------------- #


def bring_database_up_to_date(dbm: MongoDatabaseManager, db_name: str, local_mode: bool = False) -> None:
    """
    Brings one database to the current schema: validate the collections, then migrate or stamp

    **A database this call CREATES is stamped at the current version instead of being migrated.**
    ``CollectionValidator`` builds a new database from the current models - current collections,
    current indexes, current predefined data - so it is already at the current schema, and every
    registered migration is a no-op against it (each either transforms data that cannot exist yet, or
    seeds exactly what the validator has just seeded). Replaying them would be work with no effect.

    This is what the cloud tenant-creation path has always done (``route_utils.init_db_routine``
    stamps a new tenant and runs nothing). The on-premise boot did the opposite: with no stored
    version, ``get_current_update_version`` seeds ``BASELINE_UPDATER_VERSION``, which sits BELOW the
    earliest registered migration, so a brand-new installation replayed the entire history. The two
    now agree, which also retires a constraint nothing stated or tested: that every future migration
    must additionally be correct against an empty, already-current database.

    An EXISTING database is migrated exactly as before - the stamp is only ever applied to one this
    call brought into being.

    Args:
        dbm (MongoDatabaseManager): Manager owning the MongoDB connection
        db_name (str): Name of the database to bring up to date
        local_mode (bool): Passed to CollectionValidator, where it gates the key generation and the
            default admin user. Defaults to False
    """
    # Read BEFORE validating: validate_collections creates the database when it is missing, so asking
    # afterwards would always answer "it exists" and the distinction would be lost
    database_existed: bool = dbm.check_database_exists(db_name)

    CollectionValidator(db_name, dbm, local_mode=local_mode).validate_collections()

    database_updater = DatabaseUpdater(dbm, db_name)

    if not database_existed:
        database_updater.set_update_version(database_updater.get_highest_update_version())

        return

    if database_updater.is_update_available():
        database_updater.run_updates()


def start_datagerry_setup(dbm: MongoDatabaseManager) -> None:
    """
    Runs the on-prem startup routine against the single configured database

    Reads the database name from ``etc/cmdb.conf`` via ``SystemConfigReader`` and hands it to
    ``bring_database_up_to_date``, which validates the collections and then either migrates an
    existing database or stamps a newly created one at the current version. Invoked by
    ``create_rest_api`` when DataGerry runs in on-prem mode (i.e. ``cmdb.__CLOUD_MODE__`` is False)

    Args:
        dbm (MongoDatabaseManager): Manager owning the MongoDB connection used for both
            validation and updates
    """
    db_name = SystemConfigReader().get_value('database_name', 'Database')

    bring_database_up_to_date(dbm, db_name, local_mode=True)


def execute_update_checks(dbm: MongoDatabaseManager, local_mode: bool = False) -> None:
    """
    Runs collection validation and pending schema updates across every tenant database

    Fetches the list of tenant database names from the service portal
    (``get_db_names_from_service_portal``) and, for each one, runs ``CollectionValidator`` and
    applies any pending updates. Invoked by ``create_rest_api`` in both cloud mode and local
    mode; the difference is which source the service-portal lookup consults, which is
    controlled by the ``local_mode`` flag

    Args:
        dbm (MongoDatabaseManager): Manager owning the MongoDB connection reused for every
            tenant database
        local_mode (bool): Forwarded to ``get_db_names_from_service_portal`` to pick the
            local-mode database list instead of the cloud one. Defaults to False (cloud)
    """
    # First retrieve all database names
    db_names = get_db_names_from_service_portal(local_mode)

    # # Check each database if it is up to date
    for db_name in db_names:
        bring_database_up_to_date(dbm, db_name)
