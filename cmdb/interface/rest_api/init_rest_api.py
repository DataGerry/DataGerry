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
# import copy
# from datetime import datetime, timezone
# from flask import request
from flask_cors import CORS

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_services import (
    get_db_names_from_service_portal,
    CollectionValidator,
    DatabaseUpdater,
)

import cmdb
# from cmdb.models.object_model.cmdb_object import CmdbObject
# from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.interface.config import app_config
from cmdb.interface.custom_converters import RegexConverter
from cmdb.interface.rest_api.responses.error_handlers import (
    internal_server_error,
    page_gone,
    not_acceptable,
    method_not_allowed,
    page_not_found,
    forbidden,
    unauthorized,
    bad_request,
    service_unavailable,
)

from cmdb.manager.system_manager.system_config_reader import SystemConfigReader
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
def create_rest_api(database_maanger: MongoDatabaseManager) -> BaseCmdbApp:
    """
    Builds and returns the fully configured REST API Flask application

    Constructs a ``BaseCmdbApp`` bound to the given database manager, picks the Flask config
    profile based on ``cmdb.__MODE__`` (DEBUG, TESTING, or production), enables CORS with the
    DataGerry-specific response headers exposed, registers URL converters, blueprints and
    error handlers, and - unless running under TESTING - executes the mode-appropriate setup
    routine (on-prem setup, cloud update checks, or local-mode update checks). A failure
    inside that startup routine is logged and terminates the process via ``sys.exit(1)`` so
    the supervising ``ProcessManager`` does not bring up an incompletely-initialised API

    Args:
        database_maanger (MongoDatabaseManager): Manager that owns the MongoDB connection
            used by every blueprint and by the startup routines

    Returns:
        BaseCmdbApp: The ready-to-serve Flask application

    Raises:
        SystemExit: When the startup routine fails outside TESTING mode
    """
    app = BaseCmdbApp(__name__, database_manager=database_maanger)
    app.url_map.strict_slashes = True

    # Import App Extensions
    CORS(app=app, expose_headers=['X-API-Version', 'X-Total-Count'])

    # Lock the external REST API (HTTP Basic auth) behind the REST_API license feature. On-premise
    # only; a no-op in cloud/local mode. The UI (login + Bearer JWT) is unaffected.
    from cmdb.interface.rest_api.routes.cmdb_license.license_guard import enforce_rest_api_license
    app.before_request(enforce_rest_api_license)

    if cmdb.__MODE__ == 'DEBUG':
        config = app_config['development']
        app.config.from_object(config)
    elif cmdb.__MODE__ == 'TESTING':
        config = app_config['testing']
        app.config.from_object(config)
    else:
        config = app_config['production']
        app.config.from_object(config)


    # @app.before_request
    # def log_request_info():
    #     logging.info(f"Incoming Request: {request.method} {request.path}")
        # logging.info(f"Headers: {dict(request.headers)}")
        # logging.info(f"Body: {request.get_data(as_text=True)}")


    # @app.after_request
    # def log_response_info(response):
    #     route = request.endpoint  # Name of the function that handled the request
    #     rule = request.url_rule   # The matched route pattern (e.g., '/hello')

    #     logging.info(f"Response for route: {route} ({rule}). Status: {response.status}")

        # # log response body
        # if not response.direct_passthrough:
        #     try:
        #         body = response.get_data(as_text=True)
        #         logging.info(f"Body: {body}")
        #     except Exception:
        #         logging.info("Could not read response body")

        # return response

    with app.app_context():
        register_converters(app)
        register_error_pages(app)
        register_blueprints(app)

        if cmdb.__MODE__ != 'TESTING':
            try:
                LOGGER.info("Starting DataGerry Routine!")

                if not cmdb.__CLOUD_MODE__:
                    start_datagerry_setup(database_maanger)
                    # debug_create_users(1, database_maanger)
                    # debug_create_types(500, database_maanger)
                elif not cmdb.__LOCAL_MODE__:
                    # Check for updates in __CLOUD_MODE__
                    execute_update_checks(database_maanger)
                else:
                    # LOCAL_MODE
                    execute_update_checks(database_maanger, local_mode=True)
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


#pylint: disable=R0914, R0915
def register_blueprints(app: BaseCmdbApp) -> None:
    """
    Mounts every feature-area blueprint on the Flask app with its URL prefix

    Imports are intentionally local to keep module import time low and to break import cycles
    between blueprints and the manager layer. Blueprints are grouped by domain (auth, framework,
    user management, ISMS, IPAM, OpenCelium, ...) and registered under stable URL prefixes such
    as ``/objects``, ``/isms/risks`` or ``/ipam/subnet`` that the frontend depends on. Pylint
    rules R0914 (too many locals) and R0915 (too many statements) are disabled because the
    registration list is intentionally flat for readability. The DEBUG-only ``debug_blueprint``
    is appended last and is only loaded when ``cmdb.__MODE__`` is DEBUG

    Args:
        app (BaseCmdbApp): Flask app the blueprints are mounted on
    """
    #pylint: disable=import-outside-toplevel
    from cmdb.interface.rest_api.routes.auth_routes import auth_blueprint
    from cmdb.interface.rest_api.routes.system_routes.setup_routes import setup_blueprint
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
    from cmdb.interface.rest_api.routes.exporter_routes.exporter_type_routes import type_export_blueprint
    from cmdb.interface.rest_api.routes.framework_routes.cmdb_logs import logs_blueprint
    from cmdb.interface.rest_api.routes.framework_routes.setting_routes import settings_blueprint
    from cmdb.interface.rest_api.routes.importer_routes.import_routes import importer_blueprint
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
    app.register_blueprint(setup_blueprint, url_prefix='/setup')
    app.register_blueprint(date_blueprint, url_prefix='/date')
    app.register_blueprint(objects_blueprint, url_prefix='/objects')
    app.register_blueprint(types_blueprint, url_prefix='/types')
    app.register_blueprint(special_types_blueprint, url_prefix='/special_types')
    app.register_blueprint(connection_routes)
    app.register_blueprint(categories_blueprint, url_prefix='/categories')
    app.register_blueprint(location_blueprint, url_prefix='/locations')
    app.register_blueprint(section_template_blueprint, url_prefix='/section_templates')
    app.register_blueprint(users_blueprint, url_prefix='/users')
    app.register_blueprint(user_settings_blueprint, url_prefix='/users/<int:user_id>/settings')
    app.register_blueprint(groups_blueprint, url_prefix='/groups')
    app.register_blueprint(rights_blueprint, url_prefix='/rights')
    app.register_blueprint(search_blueprint)
    app.register_blueprint(exporter_blueprint, url_prefix='/exporter')
    app.register_blueprint(type_export_blueprint)
    app.register_blueprint(logs_blueprint, url_prefix='/logs')
    app.register_blueprint(settings_blueprint)
    app.register_blueprint(importer_blueprint)
    app.register_blueprint(docapi_blueprint)
    app.register_blueprint(docs_blueprint, url_prefix='/docs')
    app.register_blueprint(media_file_blueprint)
    app.register_blueprint(special_blueprint)
    app.register_blueprint(report_categories_blueprint, url_prefix='/report_categories')
    app.register_blueprint(reports_blueprint, url_prefix='/reports')
    app.register_blueprint(webhook_blueprint, url_prefix='/webhooks')
    app.register_blueprint(webhook_event_blueprint, url_prefix='/webhook_events')
    app.register_blueprint(relations_blueprint, url_prefix='/relations')
    app.register_blueprint(object_relations_blueprint, url_prefix='/object_relations')
    app.register_blueprint(object_relation_logs_blueprint, url_prefix='/object_relation_logs')
    app.register_blueprint(extendable_option_blueprint, url_prefix='/extendable_options')
    app.register_blueprint(ci_explorer_blueprint, url_prefix='/ci_explorer')
    app.register_blueprint(config_file_blueprint, url_prefix='/config_file')
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
    # (objects_helper.handle_delete_from_object_groups) calls ObjectGroupsManager directly rather
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
<<<<<<< HEAD
    app.register_blueprint(ci_explorer_blueprint, url_prefix='/ci_explorer')
    app.register_blueprint(config_file_blueprint, url_prefix='/config_file')
    app.register_blueprint(chatgpt_blueprint, url_prefix='/chatgpt')
=======
>>>>>>> origin/version-3.2

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

    # IPAM routes. The dedicated /ipam surface (overviews, network tree, validation, assignable
    # lookups) is part of the licensed IPAM feature, so every route is gated on-premise. The IPAM
    # data itself stays readable through the generic /objects and /types routes (guarded separately
    # at write time); only these dedicated IPAM surfaces are locked here.
    for ipam_blueprint in (
        ipam_validation_blueprint,
        ipam_supernet_blueprint,
        ipam_subnet_blueprint,
        ipam_assignable_blueprint,
        ipam_tree_blueprint,
    ):
        gate_blueprint(ipam_blueprint, LicenseFeature.IPAM)

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

    app.register_blueprint(oc_connectors_blueprint, url_prefix='/open_celium')
    app.register_blueprint(oc_invokers_blueprint, url_prefix='/open_celium')
    app.register_blueprint(oc_templates_blueprint, url_prefix='/open_celium')
    app.register_blueprint(oc_connections_blueprint, url_prefix='/open_celium')
    app.register_blueprint(oc_schedulers_blueprint, url_prefix='/open_celium')
    app.register_blueprint(oc_licenses_blueprint, url_prefix='/open_celium')
    app.register_blueprint(oc_connection_log_blueprint, url_prefix='/open_celium')

    if cmdb.__MODE__ == 'DEBUG':
        from cmdb.interface.rest_api.routes.debug_routes import debug_blueprint
        app.register_blueprint(debug_blueprint)

    # LOGGER.debug(f"routes: {app.url_map}")


def register_error_pages(app: BaseCmdbApp) -> None:
    """
    Wires the JSON error handlers for the HTTP status codes the REST API emits

    Covers the client- and server-error codes the route layer actually raises via ``abort()``:
    400 (bad request), 401 (unauthorized), 403 (forbidden), 404 (not found), 405 (method not
    allowed), 406 (not acceptable), 410 (gone), 500 (internal server error) and 503 (service
    unavailable). Each handler is a thin wrapper from ``responses.error_handlers`` that returns
    a structured JSON body instead of Flask's default HTML page

    Args:
        app (BaseCmdbApp): Flask app the error handlers are attached to
    """
    app.register_error_handler(400, bad_request)
    app.register_error_handler(401, unauthorized)
    app.register_error_handler(403, forbidden)
    app.register_error_handler(404, page_not_found)
    app.register_error_handler(405, method_not_allowed)
    app.register_error_handler(406, not_acceptable)
    app.register_error_handler(410, page_gone)
    app.register_error_handler(500, internal_server_error)
    app.register_error_handler(503, service_unavailable)

# -------------------------------------------------------------------------------------------------------------------- #

def start_datagerry_setup(dbm: MongoDatabaseManager) -> None:
    """
    Runs the on-prem startup routine against the single configured database

    Reads the database name from ``etc/cmdb.conf`` via ``SystemConfigReader``, validates that
    every required collection / index exists (creating any that are missing in local mode),
    and applies pending schema updates from ``cmdb/database/updater/versions`` when the
    installed schema version is behind. Invoked by ``create_rest_api`` when DataGerry runs in
    on-prem mode (i.e. ``cmdb.__CLOUD_MODE__`` is False)

    Args:
        dbm (MongoDatabaseManager): Manager owning the MongoDB connection used for both
            validation and updates
    """
    db_name = SystemConfigReader().get_value('database_name', 'Database')

    CollectionValidator(db_name, dbm, local_mode=True).validate_collections()

    database_updater = DatabaseUpdater(dbm, db_name)

    if database_updater.is_update_available():
        database_updater.run_updates()


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
        # Validate Collections
        CollectionValidator(db_name, dbm).validate_collections()

        database_updater = DatabaseUpdater(dbm, db_name)

        if database_updater.is_update_available():
            database_updater.run_updates()


# def debug_create_users(amount: int, dbm: MongoDatabaseManager) -> None:
#     """
#     Seeds the CmdbObject collection with ``amount`` dummy user objects for load testing

#     Inserts the documents directly via ``dbm.insert`` and so bypasses the manager layer and
#     its validators / hooks. Each generated user reuses the same template document with the
#     name field suffixed by the loop index so usernames remain unique. Intended for ad-hoc
#     debugging only; the call sites in ``create_rest_api`` are commented out

#     Args:
#         amount (int): Number of dummy user objects to insert
#         dbm (MongoDatabaseManager): Manager used to perform the raw inserts
#     """
#     user_dummy_data = {
#         "type_id": 2,
#         "author_id": 1,
#         "last_edit_time": None,
#         "editor_id": None,
#         "active": True,
#         "fields": [
#             {
#                 "name": "text-45910",
#                 "value": "TestUser"
#             },
#             {
#                 "name": "text-80103",
#                 "value": ""
#             },
#             {
#                 "name": "text-75307",
#                 "value": ""
#             },
#             {
#                 "name": "text-93543",
#                 "value": ""
#             },
#             {
#                 "name": "text-16313",
#                 "value": ""
#             }
#         ],
#         "multi_data_sections": []
#     }

#     for i in range(amount):
#         user_data = copy.deepcopy(user_dummy_data)
#         user_data["fields"][0]["value"] = f"TestUser{i}"  # Make the username unique
#         dbm.insert(CmdbObject.COLLECTION, user_data)


# def debug_create_types(amount: int, dbm: MongoDatabaseManager) -> None:
#     """
#     Seeds the CmdbType collection with ``amount`` dummy types for load testing

#     Inserts the documents directly via ``dbm.insert`` so the manager layer's validation and
#     section-template propagation are skipped. Each generated type reuses the same template
#     document with the loop index appended to ``name``, ``label``, the first field's ``name``
#     and the section's ``name`` / referenced field id so the resulting documents are uniquely
#     addressable. Intended for ad-hoc debugging only; the call sites in ``create_rest_api`` are
#     commented out

#     Args:
#         amount (int): Number of dummy CmdbType documents to insert
#         dbm (MongoDatabaseManager): Manager used to perform the raw inserts
#     """
#     type_dummy_data = {
#         "global_template_ids": [],
#         "fields": [
#             {
#             "type": "text",
#             "name": "text-09f3e7c6-77ba-45ce-9260-6017fac7f060",
#             "label": "Text Field"
#             }
#         ],
#         "active": True,
#         "version": "1.0.0",
#         "author_id": 1,
#         "render_meta": {
#             "icon": "fa fa-cube",
#             "sections": [
#             {
#                 "fields": [
#                     "text-09f3e7c6-77ba-45ce-9260-6017fac7f060"
#                 ],
#                 "type": "section",
#                 "name": "section-97ff6f73-b833-4f29-b7c3-0ec0403378f2",
#                 "label": "Section"
#             }
#             ],
#             "externals": [],
#             "summary": {
#             "fields": []
#             }
#         },
#         "acl": {
#             "activated": False
#         },
#         "name": "test",
#         "label": "Test1",
#         "selectable_as_parent": True,
#         "creation_time": None
#     }

#     for i in range(amount):
#         type_data = copy.deepcopy(type_dummy_data)

#         # Append i to relevant fields
#         type_data["name"] += str(i)
#         type_data["label"] += str(i)
#         type_data["fields"][0]["name"] += str(i)
#         type_data["render_meta"]["sections"][0]["fields"][0] += str(i)
#         type_data["render_meta"]["sections"][0]["name"] += str(i)
#         type_data["creation_time"] = datetime.now(timezone.utc)

#         dbm.insert(CmdbType.COLLECTION, type_data)
