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
Integration tests for the predefined-section-template select guard against a real MongoDB

Seeds the *shipped* predefined templates (SectionTemplateCreator, the same documents the first-boot
seeding inserts) and resolves them through a real SectionTemplatesManager, so the guard is pinned
against the real template documents rather than a hand-written stand-in. This is what proves the
protected-field lookup still matches the data DataGerry ships: dg-ipam-interface's 'Type' select
(dg-interface-type, the ipv4/ipv6 discriminator the IPAM overviews read) is the shipped field an
object write must never extend.

Every shipped predefined template is now either an MDS section (dg-ipam-interface) or select-free
(dg-modelspec), so the plain-section half of the guard is pinned with an extra PREDEFINED plain
template the fixture inserts. 'dg-rackmounting' used to fill that role and was retired by
updater_20260824
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.section_templates_manager import SectionTemplatesManager
from cmdb.models.section_template_model import CmdbSectionTemplate, SectionTemplateKey
from cmdb.models.special_type_model.ipam_constants import IpamSection, InterfaceField
from cmdb.models.type_model import CmdbType, FieldType, SectionType
from cmdb.framework.section_templates import (
    SectionTemplateCreator,
    get_predefined_template_names,
    resolve_predefined_select_fields,
)
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

MODELSPEC_TEMPLATE: str = 'dg-modelspec'

# A synthetic PREDEFINED plain section carrying a select field, standing in for the shipped one that
# no longer exists (see the module docstring)
PLAIN_PREDEFINED_TEMPLATE_ID: int = 9873
PLAIN_PREDEFINED_TEMPLATE: str = 'integration-predefined-plain-tpl'
PLAIN_PREDEFINED_SELECT_FIELD: str = 'integration-predefined-plain-select'
PLAIN_PREDEFINED_TEXT_FIELD: str = 'integration-predefined-plain-text'

CUSTOM_TEMPLATE_ID: int = 9871
CUSTOM_TEMPLATE_NAME: str = 'integration-custom-tpl'
CUSTOM_SELECT_FIELD: str = 'integration-custom-select'

TYPE_ID: int = 9872
LOCAL_SELECT_FIELD: str = 'integration-local-select'
LOCAL_SECTION: str = 'information'


def _custom_template_doc() -> dict[str, Any]:
    """A user-created global template (not predefined) carrying a select field."""
    return {
        SectionTemplateKey.PUBLIC_ID.value: CUSTOM_TEMPLATE_ID,
        SectionTemplateKey.NAME.value: CUSTOM_TEMPLATE_NAME,
        SectionTemplateKey.LABEL.value: 'Custom',
        SectionTemplateKey.TYPE.value: SectionType.SECTION.value,
        SectionTemplateKey.IS_GLOBAL.value: True,
        SectionTemplateKey.PREDEFINED.value: False,
        SectionTemplateKey.FIELDS.value: [{
            'type': FieldType.SELECT.value,
            'name': CUSTOM_SELECT_FIELD,
            'label': 'Custom',
            'options': [{'name': 'a', 'label': 'A'}],
        }],
    }


def _plain_predefined_template_doc() -> dict[str, Any]:
    """A predefined (system-owned) PLAIN global template carrying a select and a text field."""
    return {
        SectionTemplateKey.PUBLIC_ID.value: PLAIN_PREDEFINED_TEMPLATE_ID,
        SectionTemplateKey.NAME.value: PLAIN_PREDEFINED_TEMPLATE,
        SectionTemplateKey.LABEL.value: 'Predefined plain',
        SectionTemplateKey.TYPE.value: SectionType.SECTION.value,
        SectionTemplateKey.IS_GLOBAL.value: True,
        SectionTemplateKey.PREDEFINED.value: True,
        SectionTemplateKey.FIELDS.value: [
            {
                'type': FieldType.SELECT.value,
                'name': PLAIN_PREDEFINED_SELECT_FIELD,
                'label': 'Predefined select',
                'options': [{'name': 'a', 'label': 'A'}],
            },
            {'type': FieldType.TEXT.value, 'name': PLAIN_PREDEFINED_TEXT_FIELD, 'label': 'Predefined text'},
        ],
    }


def _consuming_type() -> CmdbType:
    """
    Builds a CmdbType using all three template kinds at once: the predefined dg-ipam-interface MDS
    section, a predefined plain section, a user-created global template and one plain section of its
    own - the layout the DataGerry assistant produces for a server profile
    """
    return CmdbType.from_data(make_type_doc(
        TYPE_ID,
        'integration-guard-type',
        fields=[
            {'type': FieldType.SELECT.value, 'name': InterfaceField.TYPE.value, 'label': 'Type'},
            {'type': FieldType.TEXT.value, 'name': InterfaceField.IP.value, 'label': 'IP-Address'},
            {'type': FieldType.SELECT.value, 'name': PLAIN_PREDEFINED_SELECT_FIELD, 'label': 'Predefined select'},
            {'type': FieldType.TEXT.value, 'name': PLAIN_PREDEFINED_TEXT_FIELD, 'label': 'Predefined text'},
            {'type': FieldType.SELECT.value, 'name': CUSTOM_SELECT_FIELD, 'label': 'Custom'},
            {'type': FieldType.SELECT.value, 'name': LOCAL_SELECT_FIELD, 'label': 'Local'},
        ],
        sections=[
            {
                'type': SectionType.MDS_SECTION.value,
                'name': IpamSection.INTERFACE.value,
                'label': 'Interfaces',
                'fields': [InterfaceField.TYPE.value, InterfaceField.IP.value],
            },
            {
                'type': SectionType.SECTION.value,
                'name': PLAIN_PREDEFINED_TEMPLATE,
                'label': 'Predefined plain',
                'fields': [PLAIN_PREDEFINED_SELECT_FIELD, PLAIN_PREDEFINED_TEXT_FIELD],
            },
            {
                'type': SectionType.SECTION.value,
                'name': CUSTOM_TEMPLATE_NAME,
                'label': 'Custom',
                'fields': [CUSTOM_SELECT_FIELD],
            },
            {
                'type': SectionType.SECTION.value,
                'name': LOCAL_SECTION,
                'label': 'Information',
                'fields': [LOCAL_SELECT_FIELD],
            },
        ],
        global_template_ids=[IpamSection.INTERFACE.value, PLAIN_PREDEFINED_TEMPLATE, CUSTOM_TEMPLATE_NAME],
    ))


@pytest.fixture(name='section_templates_manager')
def fixture_section_templates_manager(
    database_manager: MongoDatabaseManager,
    database_name: str,
) -> SectionTemplatesManager:
    """A SectionTemplatesManager bound to the test database."""
    return SectionTemplatesManager(database_manager, database_name)


@pytest.fixture(autouse=True)
def _seed_templates(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the shipped predefined templates plus one user-created global template, cleaning up after."""
    collection = database_manager.get_collection(CmdbSectionTemplate.COLLECTION, database_name)

    predefined = SectionTemplateCreator().get_predefined_templates()

    for offset, template in enumerate(predefined):
        template[SectionTemplateKey.PUBLIC_ID.value] = CUSTOM_TEMPLATE_ID + 100 + offset

    collection.insert_many(predefined + [_plain_predefined_template_doc(), _custom_template_doc()])
    yield
    collection.delete_many({
        SectionTemplateKey.NAME.value: {
            '$in': [template[SectionTemplateKey.NAME.value] for template in predefined]
                   + [PLAIN_PREDEFINED_TEMPLATE, CUSTOM_TEMPLATE_NAME],
        },
    })


# -------------------------------------------------------------------------------------------------------------------- #
#                                            get_predefined_template_names                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetPredefinedTemplateNames:
    """The lookup reads the predefined flag off the real collection."""

    def test_returns_the_shipped_templates(self, section_templates_manager: SectionTemplatesManager) -> None:
        """Every template SectionTemplateCreator ships is reported as predefined."""
        result = get_predefined_template_names(section_templates_manager)

        assert {MODELSPEC_TEMPLATE, IpamSection.INTERFACE.value} <= result

    def test_excludes_a_user_created_global_template(
        self, section_templates_manager: SectionTemplatesManager,
    ) -> None:
        """A global template that is not flagged predefined is not protected."""
        assert CUSTOM_TEMPLATE_NAME not in get_predefined_template_names(section_templates_manager)


# -------------------------------------------------------------------------------------------------------------------- #
#                                          resolve_predefined_select_fields                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class TestResolvePredefinedSelectFields:
    """Resolving a real type against the real predefined templates."""

    def test_protects_the_shipped_select_fields(self, section_templates_manager: SectionTemplatesManager) -> None:
        """A predefined MDS section's discriminator and a predefined plain section's select are both protected."""
        result = resolve_predefined_select_fields(_consuming_type(), section_templates_manager)

        assert result == {
            InterfaceField.TYPE.value: IpamSection.INTERFACE.value,
            PLAIN_PREDEFINED_SELECT_FIELD: PLAIN_PREDEFINED_TEMPLATE,
        }

    def test_leaves_the_other_select_fields_extendable(
        self, section_templates_manager: SectionTemplatesManager,
    ) -> None:
        """A user-created template's field and the type's own field keep the extend-on-write behaviour."""
        result = resolve_predefined_select_fields(_consuming_type(), section_templates_manager)

        assert CUSTOM_SELECT_FIELD not in result
        assert LOCAL_SELECT_FIELD not in result

    def test_type_without_global_templates_is_unprotected(
        self, section_templates_manager: SectionTemplatesManager,
    ) -> None:
        """A plain type carries no protected field at all."""
        plain_type = CmdbType.from_data(make_type_doc(TYPE_ID, 'integration-plain-type'))

        assert resolve_predefined_select_fields(plain_type, section_templates_manager) == {}
