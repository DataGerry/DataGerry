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
mode (collection validation followed by pending database updates).

In cloud mode the routine walks every tenant database (``execute_update_checks``) and sets a failing
tenant aside instead of failing the process: the app records it in ``unavailable_tenants`` and answers its
requests 503 (``cmdb.interface.tenant_availability``) while every other tenant is served
"""
from logging import Logger, getLogger
from typing import Iterable
import sys

from flask import Blueprint
from flask_cors import CORS
from pymongo.errors import ConnectionFailure
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
from cmdb.interface.rest_api.routes.cmdb_license.license_guard import gate_blueprint
from cmdb.interface.rest_api.responses.error_handlers import (
    database_locked,
    database_unavailable,
    http_exception,
)

from cmdb.manager.system_manager.system_config_reader import SystemConfigReader
from cmdb.utils import find_cause
from cmdb.errors.database import DatabaseConnectionError, DocumentLockTimeoutError, DocumentNetworkError
from cmdb.errors.updater import TenantUpdatesFailedError
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

#: Where DispatcherMiddleware mounts this app (see `cmdb.interface.gunicorn`). Flask reads
#: APPLICATION_ROOT for SERVER_NAME-based URL building and as the session-cookie path default
REST_APPLICATION_ROOT: str = '/rest/'

#: A blueprint and the URL prefix it is mounted at
BlueprintMount = tuple[Blueprint, str]

#: A failure that is the database server's, not one tenant's: the driver lost the server, or a layer above it
#: said so. Found anywhere in the cause chain, it stops the tenant loop instead of marking the tenant -
#: otherwise an outage would wait out the server-selection timeout once per tenant and then fence them all
DATABASE_OUTAGE_ERRORS: tuple[type[Exception], ...] = (
    ConnectionFailure,
    DatabaseConnectionError,
    DocumentNetworkError,
)

# -------------------------------------------------------------------------------------------------------------------- #


def create_rest_api(database_manager: MongoDatabaseManager) -> BaseCmdbApp:
    """
    Builds and returns the fully configured REST API Flask application

    Constructs a ``BaseCmdbApp`` bound to the given database manager, picks the Flask config
    profile based on ``cmdb.__MODE__`` (DEBUG, TESTING, or production), enables CORS, registers
    URL converters, blueprints and error handlers, and - unless running under TESTING - executes
    the mode-appropriate setup routine (on-prem setup, cloud update checks, or local-mode update
    checks). A failure inside that startup routine is logged and terminates the process via
    ``sys.exit(1)``; the supervising ``ProcessManager`` then shuts the whole application down rather
    than bring up an incompletely-initialised API.

    **In cloud mode one tenant cannot stop the others.** A tenant database that fails its validation
    or update is recorded in ``app.unavailable_tenants`` and answered 503 until the next start, while
    every other tenant is served (``execute_update_checks``). Startup still fails for everyone when
    the failure is not a tenant's: the database server is unreachable, the service portal cannot list
    the tenants, or every tenant failed

    **CORS is unrestricted.** Only ``expose_headers`` is configured - ``X-API-Version``,
    ``X-Total-Count`` and ``Content-Disposition``, the last so a cross-origin frontend can read the
    filename an export route sent - and flask-cors' defaults apply for everything else, so any origin
    may call the API with any of the standard methods. That is not a session-riding hole - DataGerry
    authenticates with a Bearer JWT in a header rather than a cookie, and ``supports_credentials``
    stays False, so a foreign origin has no token to ride - but it does mean an operator cannot
    restrict origins for a hardened deployment

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
    # `Content-Disposition` carries the download filename every export route builds
    # (cmdb.framework.exporter.export_filename_helper). A browser can only read a response header that
    # is exposed, so without it a cross-origin frontend - which is exactly the `ng serve` setup the
    # Angular app is developed in - reads none and falls back to naming downloads itself
    CORS(app=app, expose_headers=['X-API-Version', 'X-Total-Count', 'Content-Disposition'])

    app.config.from_object(app_config[config_name_for_mode(cmdb.__MODE__)])

    # Error bodies go through Flask's own JSON provider, which pretty-prints whenever DEBUG is on - and the
    # development and testing configs set it. Compact always, so an error answers in the same encoding as
    # every success body (DEFAULT_JSON_INDENT)
    app.json.compact = True

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
                    app.unavailable_tenants = execute_update_checks(database_manager)
                else:
                    app.unavailable_tenants = execute_update_checks(database_manager, local_mode=True)
            except Exception as err:
                LOGGER.error(
                    "Initialisation of DataGerry failed. Exception: %s. Type: %s", err, type(err), exc_info=True
                )
                sys.exit(1)

    return app


def register_converters(app: BaseCmdbApp) -> None:
    """
    Registers the ``regex`` URL converter on the Flask app's URL map

    The converter lets route patterns embed an arbitrary Python regex, e.g.
    ``/<regex("[a-z0-9]{8}"):token>``. It is consumed by blueprints that need parameter
    validation beyond what Werkzeug's built-in converters offer

    Args:
        app (BaseCmdbApp): The Flask app whose URL map is being extended
    """
    app.url_map.converters['regex'] = RegexConverter


def register_blueprints(app: BaseCmdbApp) -> None:
    """
    Mounts every feature-area blueprint on the Flask app with its URL prefix

    **Every mount point is declared in this file**, so it is the single source of truth for the URL map:
    one helper per domain, each importing the blueprints it mounts. The imports are local to keep module
    import time low and to break import cycles between the blueprints and the manager layer. The URL
    prefixes (``/objects``, ``/isms/risks``, ``/ipam/subnet``, ...) are the frontend's contract. Four
    blueprints also carry a ``url_prefix`` on their own ``APIBlueprint(...)`` constructor; the value
    passed here is identical and takes precedence, so the prefix is readable without opening the route
    module. ``connection_routes`` is the one blueprint mounted at the ``/rest`` root and takes no prefix.

    **A licensed group is listed once.** ``_register_gated`` gates each blueprint of a group behind its
    feature and then registers it, so a blueprint cannot be mounted without the gate its group carries -
    and the gate is always attached before the registration, which is the order Flask requires
    (``gate_blueprint`` adds a ``before_request`` hook, and Flask refuses - ``AssertionError`` - a setup
    method on a blueprint that is already registered). The licensed groups are ISMS (with the shared
    object-group / person / person-group entities), IPAM (with the rack and port surfaces) and OpenCelium
    Automations; the config-file routes and OpenCelium's own licence routes are mounted ungated, each
    route carrying the licence it needs

    Args:
        app (BaseCmdbApp): Flask app the blueprints are mounted on
    """
    _register_core(app)
    _register_framework(app)
    _register_documents_and_ai(app)
    _register_relations(app)
    _register_user_management(app)
    _register_import_export(app)
    _register_reports_and_webhooks(app)
    _register_isms(app)
    _register_ipam_racks_and_ports(app)
    _register_open_celium(app)


def _register_gated(app: BaseCmdbApp, feature: LicenseFeature, mounts: Iterable[BlueprintMount]) -> None:
    """
    Gates every blueprint of a licensed group behind its feature, then registers it

    One list drives both steps, so no blueprint of the group is served without its gate, and each gate is
    attached before its blueprint is registered (Flask raises ``AssertionError`` the other way round)

    Args:
        app (BaseCmdbApp): Flask app the blueprints are mounted on
        feature (LicenseFeature): The licence feature every route of the group requires on premise
        mounts (Iterable[BlueprintMount]): The group's blueprints with the prefix each is mounted at
    """
    for blueprint, url_prefix in mounts:
        gate_blueprint(blueprint, feature)
        app.register_blueprint(blueprint, url_prefix=url_prefix)


def _register_core(app: BaseCmdbApp) -> None:
    """
    Mounts the platform routes: authentication, the /rest root probe, settings, licences and the cloud setup

    The ``/setup`` routes are registered in cloud mode ONLY, and the registration is the whole guard. They
    exist for the DataGerry Service Portal to tear down a tenant - drop its database, evict it from the user
    cache - and an on-premise installation has no portal, no subscriptions and nothing to tear down. They
    carry no ``insert_request_user`` and no ``.protect``; their only decorator is ``verify_api_access``,
    which returns immediately outside cloud mode, so registering them on premise would publish an
    UNAUTHENTICATED ``DELETE /rest/setup/subscriptions?database=<name>`` that drops any database on the
    cluster

    Args:
        app (BaseCmdbApp): Flask app the blueprints are mounted on
    """
    # pylint: disable=import-outside-toplevel
    from cmdb.interface.rest_api.routes.auth_routes import auth_blueprint
    from cmdb.interface.rest_api.routes.setup_routes.setup_routes import setup_blueprint
    from cmdb.interface.rest_api.routes.connection import connection_routes
    from cmdb.interface.rest_api.routes.settings_routes.date_routes import date_blueprint
    from cmdb.interface.rest_api.routes.settings_routes.system_routes import system_blueprint
    from cmdb.interface.rest_api.routes.cmdb_license import license_activation_blueprint, license_blueprint

    app.register_blueprint(auth_blueprint, url_prefix='/auth')

    if cmdb.__CLOUD_MODE__:
        app.register_blueprint(setup_blueprint, url_prefix='/setup')

    # Mounted at the /rest root itself: '/' is the frontend's connection probe and '/frontend_init' its
    # runtime config, so this blueprint carries no prefix
    app.register_blueprint(connection_routes)
    app.register_blueprint(date_blueprint, url_prefix='/date')
    app.register_blueprint(system_blueprint, url_prefix='/settings/system')

    for license_routes in (license_activation_blueprint, license_blueprint):
        app.register_blueprint(license_routes, url_prefix='/license')


def _register_framework(app: BaseCmdbApp) -> None:
    """
    Mounts the CMDB core: objects, types, categories, locations, section templates, options, search and logs

    Args:
        app (BaseCmdbApp): Flask app the blueprints are mounted on
    """
    # pylint: disable=import-outside-toplevel
    from cmdb.interface.rest_api.routes import framework_routes
    from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_routes import objects_blueprint
    from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_routes import types_blueprint
    from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.special_type_routes import special_types_blueprint
    from cmdb.interface.rest_api.routes.framework_routes.cmdb_categories.categories_routes import categories_blueprint
    from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_routes import location_blueprint
    from cmdb.interface.rest_api.routes.framework_routes.cmdb_section_templates.section_template_routes import (
        section_template_blueprint,
    )
    from cmdb.interface.rest_api.routes.framework_routes.search_routes import search_blueprint
    from cmdb.interface.rest_api.routes.framework_routes.cmdb_logs import logs_blueprint

    app.register_blueprint(objects_blueprint, url_prefix='/objects')
    app.register_blueprint(types_blueprint, url_prefix='/types')
    app.register_blueprint(special_types_blueprint, url_prefix='/special_types')
    app.register_blueprint(categories_blueprint, url_prefix='/categories')
    app.register_blueprint(location_blueprint, url_prefix='/locations')
    app.register_blueprint(section_template_blueprint, url_prefix='/section_templates')
    app.register_blueprint(framework_routes.extendable_option_blueprint, url_prefix='/extendable_options')
    app.register_blueprint(search_blueprint, url_prefix='/search')
    app.register_blueprint(logs_blueprint, url_prefix='/logs')


def _register_documents_and_ai(app: BaseCmdbApp) -> None:
    """
    Mounts the document generator (DocAPI templates and rendered documents), the media library, the
    DataGerry Assistant's special routes and the AI text assistant

    Args:
        app (BaseCmdbApp): Flask app the blueprints are mounted on
    """
    # pylint: disable=import-outside-toplevel
    from cmdb.interface.rest_api.routes.framework_routes.cmdb_docapi_templates.docapi_template_routes import (
        docapi_blueprint,
        docs_blueprint,
    )
    from cmdb.interface.rest_api.routes.media_library_routes.media_file_routes import media_file_blueprint
    from cmdb.interface.rest_api.routes.framework_routes.special_routes import special_blueprint
    from cmdb.interface.rest_api.routes.ai_routes.chatgpt_routes import chatgpt_blueprint

    app.register_blueprint(docapi_blueprint, url_prefix='/docapi')
    app.register_blueprint(docs_blueprint, url_prefix='/docs')
    app.register_blueprint(media_file_blueprint, url_prefix='/media_file')
    app.register_blueprint(special_blueprint, url_prefix='/special')
    app.register_blueprint(chatgpt_blueprint, url_prefix='/chatgpt')


def _register_relations(app: BaseCmdbApp) -> None:
    """
    Mounts the relation definitions, the object relations, their change log and the CI Explorer graph

    The object-relation LOG routes are imported from ``relation_routes``, the package of the entity they
    record - not from a log package of their own

    Args:
        app (BaseCmdbApp): Flask app the blueprints are mounted on
    """
    # pylint: disable=import-outside-toplevel
    from cmdb.interface.rest_api.routes.relation_routes.relations_routes import relations_blueprint
    from cmdb.interface.rest_api.routes.relation_routes.object_relation_routes import object_relations_blueprint
    from cmdb.interface.rest_api.routes.relation_routes.object_relation_logs_routes import (
        object_relation_logs_blueprint,
    )
    from cmdb.interface.rest_api.routes.ci_explorer_routes.ci_explorer_routes import ci_explorer_blueprint

    app.register_blueprint(relations_blueprint, url_prefix='/relations')
    app.register_blueprint(object_relations_blueprint, url_prefix='/object_relations')
    app.register_blueprint(object_relation_logs_blueprint, url_prefix='/object_relation_logs')
    app.register_blueprint(ci_explorer_blueprint, url_prefix='/ci_explorer')


def _register_user_management(app: BaseCmdbApp) -> None:
    """
    Mounts the users, their settings, the user groups and the rights catalogue

    Args:
        app (BaseCmdbApp): Flask app the blueprints are mounted on
    """
    # pylint: disable=import-outside-toplevel
    from cmdb.interface.rest_api.routes.user_management_routes.users_routes import users_blueprint
    from cmdb.interface.rest_api.routes.user_management_routes.user_settings_routes import user_settings_blueprint
    from cmdb.interface.rest_api.routes.user_management_routes.cmdb_groups.groups_routes import groups_blueprint
    from cmdb.interface.rest_api.routes.user_management_routes.rights_routes import rights_blueprint

    app.register_blueprint(users_blueprint, url_prefix='/users')
    app.register_blueprint(user_settings_blueprint, url_prefix='/users/<int:user_id>/settings')
    app.register_blueprint(groups_blueprint, url_prefix='/groups')
    app.register_blueprint(rights_blueprint, url_prefix='/rights')


def _register_import_export(app: BaseCmdbApp) -> None:
    """
    Mounts the object and type exporters and importers

    The prefixes do not mirror each other (``/exporter`` + ``/export/type`` against ``/import/type`` +
    ``/import/object``); they are the frontend's contract and stay as they are

    Args:
        app (BaseCmdbApp): Flask app the blueprints are mounted on
    """
    # pylint: disable=import-outside-toplevel
    from cmdb.interface.rest_api.routes.exporter_routes.exporter_object_routes import exporter_blueprint
    from cmdb.interface.rest_api.routes.exporter_routes.exporter_type_routes import exporter_type_blueprint
    from cmdb.interface.rest_api.routes.importer_routes.importer_type_routes import importer_type_blueprint
    from cmdb.interface.rest_api.routes.importer_routes.importer_object_routes import importer_object_blueprint

    app.register_blueprint(exporter_blueprint, url_prefix='/exporter')
    app.register_blueprint(exporter_type_blueprint, url_prefix='/export/type')
    app.register_blueprint(importer_type_blueprint, url_prefix='/import/type')
    app.register_blueprint(importer_object_blueprint, url_prefix='/import/object')


def _register_reports_and_webhooks(app: BaseCmdbApp) -> None:
    """
    Mounts the report categories, the reports, the webhooks and their delivery log

    Args:
        app (BaseCmdbApp): Flask app the blueprints are mounted on
    """
    # pylint: disable=import-outside-toplevel
    from cmdb.interface.rest_api.routes.report_routes.report_category_routes import report_categories_blueprint
    from cmdb.interface.rest_api.routes.report_routes.report_routes import reports_blueprint
    from cmdb.interface.rest_api.routes.webhook_routes.webhook_routes import webhook_blueprint
    from cmdb.interface.rest_api.routes.webhook_routes.webhook_event_routes import webhook_event_blueprint

    app.register_blueprint(report_categories_blueprint, url_prefix='/report_categories')
    app.register_blueprint(reports_blueprint, url_prefix='/reports')
    app.register_blueprint(webhook_blueprint, url_prefix='/webhooks')
    app.register_blueprint(webhook_event_blueprint, url_prefix='/webhook_events')


def _register_isms(app: BaseCmdbApp) -> None:
    """
    Mounts the ISMS module and the shared entities it depends on, all gated behind the ISMS licence

    The whole ISMS module is a licensed feature, so every route - all methods, reads included - is gated
    on premise. Persons, person groups and object groups are shared entities ISMS depends on (an
    assessment's responsible / interviewed persons and risk owner; the object group is the risk scope),
    so their routes are gated behind ISMS too. They keep their own top-level prefixes rather than moving
    under ``/isms/``, so the frontend contract is unchanged. The object-delete cascade
    (``objects_side_effects_helper.handle_delete_from_object_groups``) calls ``ObjectGroupsManager``
    directly rather than these routes, so the gate does not reach it

    Args:
        app (BaseCmdbApp): Flask app the blueprints are mounted on
    """
    # pylint: disable=import-outside-toplevel
    from cmdb.interface.rest_api.routes import framework_routes, isms_routes as isms
    from cmdb.interface.rest_api.routes.user_management_routes.persons_routes import person_blueprint
    from cmdb.interface.rest_api.routes.user_management_routes.person_groups_routes import person_group_blueprint
    from cmdb.interface.rest_api.routes.importer_routes.importer_isms_routes import isms_importer_blueprint

    _register_gated(app, LicenseFeature.ISMS, (
        (framework_routes.object_group_blueprint, '/object_groups'),
        (person_blueprint, '/persons'),
        (person_group_blueprint, '/person_groups'),
        (isms.isms_config_blueprint, '/isms/config'),
        (isms.risk_class_blueprint, '/isms/risk_classes'),
        (isms.likelihood_blueprint, '/isms/likelihoods'),
        (isms.impact_blueprint, '/isms/impacts'),
        (isms.impact_category_blueprint, '/isms/impact_categories'),
        (isms.protection_goal_blueprint, '/isms/protection_goals'),
        (isms.risk_matrix_blueprint, '/isms/risk_matrix'),
        (isms.threat_blueprint, '/isms/threats'),
        (isms.vulnerability_blueprint, '/isms/vulnerabilities'),
        (isms.risk_blueprint, '/isms/risks'),
        (isms.control_measure_blueprint, '/isms/control_measures'),
        (isms.risk_assessment_blueprint, '/isms/risk_assessments'),
        (isms.control_measure_assignment_blueprint, '/isms/control_measure_assignments'),
        (isms_importer_blueprint, '/isms/importer'),
        (isms.isms_report_blueprint, '/isms/reports'),
    ))


def _register_ipam_racks_and_ports(app: BaseCmdbApp) -> None:
    """
    Mounts the IPAM, rack and port surfaces, all gated behind the IPAM licence

    The ``/ipam`` surface (overviews, network tree, validation, assignable lookups) belongs to the feature
    outright. The ``/racks`` surface is gated behind it as an INTERIM decision until the Rack View has a
    licence feature of its own - a Rack is NOT an IPAM type (``SpecialType.get_license_gated_types``). The
    ``/ports`` and ``/port_connections`` surfaces belong to Port Connectivity, gated behind IPAM by
    decision D6: a type cannot declare ``uses_ports`` without that licence either, so an installation
    without it has no ports to read and nothing to connect. The data itself stays readable through the
    generic ``/objects`` and ``/types`` routes (guarded separately at write time); only these dedicated
    surfaces are locked

    Args:
        app (BaseCmdbApp): Flask app the blueprints are mounted on
    """
    # pylint: disable=import-outside-toplevel
    from cmdb.interface.rest_api.routes import port_routes
    from cmdb.interface.rest_api.routes.port_connection_routes import port_connection_blueprint
    from cmdb.interface.rest_api.routes.rack_routes.rack_mount_routes import rack_mounts_blueprint
    from cmdb.interface.rest_api.routes.rack_routes.rack_assignable_routes import rack_assignable_blueprint
    from cmdb.interface.rest_api.routes.ipam_routes.ipam_validation_routes import ipam_validation_blueprint
    from cmdb.interface.rest_api.routes.ipam_routes.ipam_supernet_routes import ipam_supernet_blueprint
    from cmdb.interface.rest_api.routes.ipam_routes.ipam_subnet_routes import ipam_subnet_blueprint
    from cmdb.interface.rest_api.routes.ipam_routes.ipam_assignable_routes import ipam_assignable_blueprint
    from cmdb.interface.rest_api.routes.ipam_routes.ipam_tree_routes import ipam_tree_blueprint

    _register_gated(app, LicenseFeature.IPAM, (
        *((rack_routes, '/racks') for rack_routes in (rack_mounts_blueprint, rack_assignable_blueprint)),
        *((ports, '/ports') for ports in (
            port_routes.port_blueprint,
            port_routes.port_interface_link_blueprint,
            port_routes.port_preview_blueprint,
            port_routes.port_bulk_blueprint,
        )),
        (port_connection_blueprint, '/port_connections'),
        (ipam_validation_blueprint, '/ipam/validate'),
        (ipam_supernet_blueprint, '/ipam/supernet'),
        (ipam_subnet_blueprint, '/ipam/subnet'),
        (ipam_assignable_blueprint, '/ipam/assignable-objects'),
        (ipam_tree_blueprint, '/ipam/tree'),
    ))


def _register_open_celium(app: BaseCmdbApp) -> None:
    """
    Mounts the OpenCelium integration (the licensed Automations feature) and the config-file status routes

    Every OpenCelium route is gated behind Automations on premise, except OpenCelium's OWN licence routes,
    which stay ungated. The config-file blueprint is not gated as a whole either: it is the home of every
    config-file status route, and each route carries the licence of the section it reports on (the
    OpenCelium one: ``requires_feature(AUTOMATIONS)``)

    Args:
        app (BaseCmdbApp): Flask app the blueprints are mounted on
    """
    # pylint: disable=import-outside-toplevel
    from cmdb.interface.rest_api.routes import open_celium_routes as oc
    from cmdb.interface.rest_api.routes.config_routes.config_file_routes import config_file_blueprint

    app.register_blueprint(config_file_blueprint, url_prefix='/config_file')

    _register_gated(app, LicenseFeature.AUTOMATIONS, (
        (automations, '/open_celium') for automations in (
            oc.oc_connectors_blueprint,
            oc.oc_invokers_blueprint,
            oc.oc_templates_blueprint,
            oc.oc_connections_blueprint,
            oc.oc_schedulers_blueprint,
            oc.oc_connection_log_blueprint,
        )
    ))
    app.register_blueprint(oc.oc_licenses_blueprint, url_prefix='/open_celium')


def register_error_pages(app: BaseCmdbApp) -> None:
    """
    Wires the REST API's single error handler, for every HTTP status there is

    ``http_exception`` is registered for the ``HTTPException`` **class**, so it answers the
    structured JSON body the frontend parses (``{description, message, response, status}``) for any
    status - the ones the route layer aborts, the ones Werkzeug raises while parsing a request, and
    the ones a future route invents. Flask routes an unhandled non-HTTP exception here too, having
    converted it to an ``InternalServerError`` first

    **A whitelist of codes would not be enough.** Werkzeug raises some statuses before any route
    runs - 415 among them - so a status no ``abort()`` in ``cmdb/`` names can still reach a client,
    and under a whitelist it would fall through to Flask's HTML page and break the envelope for a
    client that reads ``message`` off it. Handling the exception CLASS covers every status without
    anyone having to enumerate them

    The two transient database errors get handlers of their own - a lost connection answers **503**, a lock
    timeout **423**, both in the same envelope - so every route says "try again" for them rather than 500

    Args:
        app (BaseCmdbApp): Flask app the error handlers are attached to
    """
    app.register_error_handler(HTTPException, http_exception)
    app.register_error_handler(DocumentNetworkError, database_unavailable)
    app.register_error_handler(DocumentLockTimeoutError, database_locked)


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


def execute_update_checks(dbm: MongoDatabaseManager, local_mode: bool = False) -> frozenset[str]:
    """
    Brings every tenant database up to date and returns the ones that failed

    Fetches the tenant database names from the service portal (``get_db_names_from_service_portal``) and
    runs ``bring_database_up_to_date`` on each: an existing database is validated and migrated, a missing
    one is created and stamped at the current version. Invoked by ``create_rest_api`` in cloud mode and in
    local mode; ``local_mode`` only picks which list the portal lookup returns.

    **A failing tenant is set aside, not fatal.** Its failure is logged with its name and traceback, the
    remaining tenants are still updated, and its name is returned so the app can answer its requests 503
    (``cmdb.interface.tenant_availability``). The next start retries it. Three failures still stop
    startup for everyone, because none of them is a tenant's own:

    - the portal cannot list the tenants - without the list nothing is known to be up to date
    - the database server is unreachable (``DATABASE_OUTAGE_ERRORS`` anywhere in the cause chain) - it
      would fail every tenant in turn, each only after the server-selection timeout
    - every tenant failed (``TenantUpdatesFailedError``) - nothing could be served

    Args:
        dbm (MongoDatabaseManager): Manager owning the MongoDB connection reused for every tenant database
        local_mode (bool): Forwarded to ``get_db_names_from_service_portal`` to pick the local-mode database
            list instead of the cloud one. Defaults to False (cloud)

    Raises:
        TenantUpdatesFailedError: When every listed tenant failed
        Exception: Whatever the portal lookup raised, or the outage error a tenant's update raised

    Returns:
        frozenset[str]: The tenant databases that failed; empty when all are up to date
    """
    db_names: list[str] = get_db_names_from_service_portal(local_mode)

    failed: list[str] = [db_name for db_name in db_names if not update_tenant_database(dbm, db_name)]

    if db_names and len(failed) == len(db_names):
        raise TenantUpdatesFailedError(f"Every tenant database failed its startup update: {', '.join(failed)}")

    return frozenset(failed)


def update_tenant_database(dbm: MongoDatabaseManager, db_name: str) -> bool:
    """
    Brings one tenant database up to date, reporting a tenant failure instead of raising it

    Args:
        dbm (MongoDatabaseManager): Manager owning the MongoDB connection
        db_name (str): The tenant database to validate and migrate

    Raises:
        Exception: The error itself when it is a database outage (``is_database_outage``) - logged with the
            tenant it struck, then re-raised so startup stops

    Returns:
        bool: True when the tenant is up to date, False when its validation or update failed (logged)
    """
    try:
        bring_database_up_to_date(dbm, db_name)
    except Exception as err:
        if is_database_outage(err):
            LOGGER.error("The database server failed while updating tenant database '%s': %s", db_name, err)
            raise

        LOGGER.error(
            "Tenant database '%s' failed its startup update and is unavailable until the next start: %s",
            db_name, err, exc_info=True,
        )

        return False

    return True


def is_database_outage(err: BaseException) -> bool:
    """
    Tells whether an error means the database server, rather than one database, failed

    Args:
        err (BaseException): The error a tenant's update raised

    Returns:
        bool: True when a ``DATABASE_OUTAGE_ERRORS`` class is anywhere in its cause chain
    """
    return any(find_cause(err, error_class) for error_class in DATABASE_OUTAGE_ERRORS)
