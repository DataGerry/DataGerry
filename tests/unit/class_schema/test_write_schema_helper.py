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
Unit tests for cmdb.class_schema.write_schema_helper

A document schema describes what is STORED (public_id included - a stored document validating against
its own schema is asserted by the model tests). A request schema describes what a CLIENT may send, and
the identity is not part of that. These tests pin the derivation between the two, and that every write
route the repo has really validates against the derived form - the route-level half is what stops a
payload id from reaching a manager. The update form (build_update_schema) also loses every default, so a key a
body leaves out stays out; the object PUT's schema is pinned through the validator the routes use.
"""
import re
import pathlib

import pytest
from cerberus import Validator

from cmdb.class_schema.write_schema_helper import build_update_schema, build_write_schema
from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.isms_model.isms_threat import IsmsThreat
from cmdb.models.object_model import CmdbObject
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_constants import (
    OBJECT_COMMENT_RULE,
    OBJECT_UPDATE_SCHEMA,
    OBJECT_UPDATE_SERVER_OWNED_KEYS,
    ObjectPatchKey,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_patch_helper import get_object_patch_schema
# -------------------------------------------------------------------------------------------------------------------- #

ROUTES_DIR: pathlib.Path = pathlib.Path(__file__).resolve().parents[3] / 'cmdb' / 'interface' / 'rest_api' / 'routes'

# The routes that validate a document schema directly, each by contract:
#   * the object routes - POST /objects/ honours a free public_id (a taken one is a 400) and the object
#     importer imports under the id its file names, so the identity is not stripped there
#   * the risk-assessment DUPLICATE route - its body's public_id names the SOURCE assessment to copy,
#     which is client input rather than the identity of anything being written
DOCUMENT_SCHEMA_BY_CONTRACT: dict[str, tuple[str, ...]] = {
    'objects_routes.py': ('CmdbObject.SCHEMA',),
    'risk_assessment_routes.py': ('IsmsRiskAssessment.SCHEMA',),
}


class TestTheDerivation:
    """What build_write_schema removes, and what it must leave alone."""

    def test_the_identity_is_dropped(self) -> None:
        """public_id is server-owned, so it is not part of a request contract."""
        derived = build_write_schema({'public_id': {'type': 'integer'}, 'name': {'type': 'string'}})

        assert derived == {'name': {'type': 'string'}}

    def test_every_other_rule_is_carried_over_unchanged(self) -> None:
        """A write route keeps validating exactly what it validated before, minus the identity."""
        document = {
            'public_id': {'type': 'integer'},
            'name': {'type': 'string', 'required': True, 'empty': False},
            'source': {'type': 'integer', 'nullable': True},
        }

        derived = build_write_schema(document)

        assert derived['name'] == document['name']
        assert derived['source'] == document['source']

    def test_the_document_schema_is_not_modified(self) -> None:
        """The model's SCHEMA is a shared object - deriving must not mutate it."""
        document = {'public_id': {'type': 'integer'}, 'name': {'type': 'string'}}

        build_write_schema(document)

        assert 'public_id' in document

    def test_a_wider_server_owned_set_can_be_given(self) -> None:
        """The default is the identity alone; a caller may strip more."""
        document = {'public_id': {'type': 'integer'}, 'author_id': {'type': 'integer'},
                    'name': {'type': 'string'}}

        assert build_write_schema(document, ['public_id', 'author_id']) == {'name': {'type': 'string'}}

    def test_a_schema_without_an_identity_is_unchanged(self) -> None:
        """Not every schema declares the key; dropping what is absent is a no-op."""
        document = {'name': {'type': 'string'}}

        assert build_write_schema(document) == document


class TestTheUpdateDerivation:
    """What build_update_schema removes on top of build_write_schema"""

    def test_every_default_is_dropped(self) -> None:
        """The other rules of the key stay as they were"""
        document = {'public_id': {'type': 'integer'},
                    'active': {'type': 'boolean', 'required': False, 'default': True}}

        assert build_update_schema(document) == {'active': {'type': 'boolean', 'required': False}}

    def test_the_server_owned_keys_are_dropped_as_well(self) -> None:
        """The same set build_write_schema takes"""
        document = {'public_id': {'type': 'integer'}, 'version': {'type': 'string', 'default': '1.0.0'},
                    'name': {'type': 'string'}}

        assert build_update_schema(document, ['version']) == {'public_id': {'type': 'integer'},
                                                               'name': {'type': 'string'}}

    def test_the_document_schema_keeps_its_defaults(self) -> None:
        """The create still needs them - the rule dicts are copied, not edited"""
        document = {'active': {'type': 'boolean', 'default': True}}

        build_update_schema(document)

        assert document == {'active': {'type': 'boolean', 'default': True}}

    def test_a_nested_schema_is_carried_over_unchanged(self) -> None:
        """Only the top level loses its defaults"""
        nested = {'type': 'dict', 'schema': {'flag': {'type': 'boolean', 'default': False}}}

        assert build_update_schema({'options': nested})['options'] == nested


class TestTheObjectUpdateSchema:
    """The PUT /objects/<id> body schema, through the validator the routes use"""

    def test_it_is_the_document_schema_less_the_server_owned_keys_plus_the_comment(self) -> None:
        """public_id stays - the route pins it; author, times and version go; the edit-log comment comes in"""
        assert set(OBJECT_UPDATE_SCHEMA) == (
            set(CmdbObject.SCHEMA) - OBJECT_UPDATE_SERVER_OWNED_KEYS | {ObjectPatchKey.COMMENT.value}
        )
        assert CmdbDAO.PUBLIC_ID_KEY in OBJECT_UPDATE_SCHEMA
        assert OBJECT_UPDATE_SERVER_OWNED_KEYS == {'author_id', 'creation_time', 'last_edit_time', 'version'}

    def test_an_omitted_key_stays_out_of_the_validated_document(self) -> None:
        """The document schema would fill version, active and multi_data_sections in"""
        body = {'fields': []}
        update_validator = Validator(OBJECT_UPDATE_SCHEMA, purge_unknown=True)
        document_validator = Validator(CmdbObject.SCHEMA, purge_unknown=True)

        assert update_validator.validate(body)
        assert document_validator.validate({**body, 'author_id': 1})
        assert update_validator.document == body
        assert {'version', 'active', 'multi_data_sections'} <= set(document_validator.document)

    def test_a_sent_server_owned_key_is_purged(self) -> None:
        """Neither required nor read: a version or an author in the body never reaches the route"""
        validator = Validator(OBJECT_UPDATE_SCHEMA, purge_unknown=True)

        assert validator.validate({'fields': [], 'version': 'abc', 'author_id': 9})
        assert validator.document == {'fields': []}

    def test_a_sent_comment_reaches_the_route(self) -> None:
        """The document schema does not declare it, so without the update schema's rule it was purged"""
        update_validator = Validator(OBJECT_UPDATE_SCHEMA, purge_unknown=True)
        document_validator = Validator(CmdbObject.SCHEMA, purge_unknown=True)

        assert update_validator.validate({'fields': [], 'comment': 'assigned'})
        assert document_validator.validate({'fields': [], 'author_id': 1, 'comment': 'assigned'})
        assert update_validator.document['comment'] == 'assigned'
        assert 'comment' not in document_validator.document

    def test_the_comment_is_never_part_of_the_document_schema(self) -> None:
        """It is never stored, so the create and the stored-document contract do not know it"""
        assert ObjectPatchKey.COMMENT.value not in CmdbObject.SCHEMA

    def test_put_and_patch_share_one_comment_rule(self) -> None:
        """Equal rules, separate dicts - a validator can never change the shared one"""
        patch_rule = get_object_patch_schema()[ObjectPatchKey.COMMENT.value]
        put_rule = OBJECT_UPDATE_SCHEMA[ObjectPatchKey.COMMENT.value]

        assert patch_rule == put_rule == OBJECT_COMMENT_RULE
        assert patch_rule is not OBJECT_COMMENT_RULE and put_rule is not OBJECT_COMMENT_RULE

    def test_fields_stay_required(self) -> None:
        """A full replace names every field it keeps"""
        assert not Validator(OBJECT_UPDATE_SCHEMA, purge_unknown=True).validate({'active': False})


class TestAgainstARealSchema:
    """The derivation on a real model, through the validator the routes actually use."""

    def test_a_payload_identity_is_purged_rather_than_refused(self) -> None:
        """
        purge_unknown is what makes this work: the id is DROPPED, not rejected

        Refusing it would break every client that round-trips a GET body back into a PUT - which is
        how the frontend writes, since it always sends the whole object.
        """
        validator = Validator(build_write_schema(IsmsThreat.SCHEMA), purge_unknown=True)

        assert validator.validate({'public_id': 4711, 'name': 'a threat'})
        assert validator.document == {'name': 'a threat'}

    def test_the_document_schema_still_accepts_a_stored_document(self) -> None:
        """The stored form keeps its identity - only the request contract loses it."""
        assert CmdbDAO.PUBLIC_ID_KEY in IsmsThreat.SCHEMA


class TestEveryWriteRouteUsesTheDerivedForm:
    """
    A census, so a new write route cannot quietly re-open the hole

    A route that validates a document schema declaring public_id accepts a client-chosen identity: on
    create it is stored as given, on update it is `$set` onto the document and the row changes identity.
    """

    @pytest.mark.parametrize('route_file', sorted(ROUTES_DIR.rglob('*_routes.py')), ids=lambda p: p.name)
    def test_no_route_validates_a_bare_document_schema(self, route_file: pathlib.Path) -> None:
        """Every `.validate(X.SCHEMA)` is wrapped in build_write_schema, or is a documented exception."""
        allowed: tuple[str, ...] = DOCUMENT_SCHEMA_BY_CONTRACT.get(route_file.name, ())
        offenders = [
            match for match in re.findall(r"\.validate\((\w+\.SCHEMA)\)", route_file.read_text())
            if match not in allowed
        ]

        assert not offenders, (
            f"{route_file.name} validates {offenders} directly; wrap it in build_write_schema(...) so a "
            f"client-supplied public_id is purged before the handler sees it"
        )

    def test_the_exception_list_holds_only_the_two_documented_contracts(self) -> None:
        """Each exception costs a client-settable identity, so the list stays short and explained."""
        assert DOCUMENT_SCHEMA_BY_CONTRACT == {
            'objects_routes.py': ('CmdbObject.SCHEMA',),
            'risk_assessment_routes.py': ('IsmsRiskAssessment.SCHEMA',),
        }
        assert CmdbDAO.PUBLIC_ID_KEY in CmdbObject.SCHEMA
