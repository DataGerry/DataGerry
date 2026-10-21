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
Round trips of the model builders that read and write their documents through a key enum

Every builder here reads its document by key (``from_data`` / the constructor) and writes it back by key
(``to_json`` / ``to_dict``). Each test hands it a document in which EVERY key holds a different value, so a key read
from - or written to - the wrong place cannot pass: the output differs from the input. The key sets are taken from
the enums, so a key the enum names but the builder drops fails too
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.models.category_model.category_constants import CategoryNodeKey
from cmdb.models.category_model.category_node import CategoryNode
from cmdb.models.category_model.cmdb_category import CmdbCategory
from cmdb.models.group_model.cmdb_user_group import CmdbUserGroup
from cmdb.models.group_model.group_constants import GroupKey
from cmdb.models.location_model.location_constants import LocationKey, LocationNodeKey
from cmdb.models.location_model.location_node import LocationNode
from cmdb.models.log_model.cmdb_object_log import CmdbObjectLog
from cmdb.models.log_model.object_log_constants import ObjectLogKey
from cmdb.models.rack_model.cmdb_rack_mount import CmdbRackMount
from cmdb.models.rack_model.rack_mount_constants import RackMountKey
from cmdb.models.right_model.all_rights import ALL_RIGHTS_FLAT
from cmdb.models.right_model.base_right import BaseRight
from cmdb.models.right_model.right_constants import RightKey
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.section_template_model.section_template_constants import SectionTemplateKey
from cmdb.models.type_model.section_key_enum import SectionKey
from cmdb.models.type_model.section_reference_key_enum import SectionReferenceKey
from cmdb.models.type_model.type_constants import LEGACY_EXTERNALS_KEY, ExternalLinkKey, TypeSummaryKey
from cmdb.models.type_model.type_external_link import TypeExternalLink
from cmdb.models.type_model.type_field_section import TypeFieldSection
from cmdb.models.type_model.type_multi_data_section import TypeMultiDataSection
from cmdb.models.type_model.type_reference_section import TypeReferenceSection
from cmdb.models.type_model.type_reference_section_entry import TypeReferenceSectionEntry
from cmdb.models.type_model.type_render_meta import TypeRenderMeta
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.models.type_model.type_section import TypeSection
from cmdb.models.type_model.type_summary import TypeSummary
from cmdb.models.webhook_model.cmdb_webhook_event import CmdbWebhookEvent
from cmdb.models.webhook_model.cmdb_webhook_model import CmdbWebhook
from cmdb.models.webhook_model.webhook_constants import WebhookKey
from cmdb.models.webhook_model.webhook_event_constants import WebhookEventKey
# -------------------------------------------------------------------------------------------------------------------- #

STAMP: datetime = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
LATER: datetime = datetime(2026, 2, 3, 4, 5, 6, tzinfo=timezone.utc)
LATEST: datetime = datetime(2026, 3, 4, 5, 6, 7, tzinfo=timezone.utc)


def _distinct(keys: list[str], **typed: Any) -> dict[str, Any]:
    """A document whose every key holds its own value: the given typed ones, else the key's name reversed."""
    return {key: typed.get(key, f'{key[::-1]}-value') for key in keys}


# -------------------------------------------------------------------------------------------------------------------- #
#                                         documents read and written by from_data / to_json                            #
# -------------------------------------------------------------------------------------------------------------------- #
def _rack_mount() -> dict[str, Any]:
    keys = [key.value for key in RackMountKey]
    return _distinct(
        keys, public_id=11, rack_id=12, object_id=13, kind='MOUNT', area='FRONT', start_slot=14, height=15,
        author_id=16, start_date=STAMP, end_date=LATER, creation_time=LATEST, last_edit_time=STAMP,
    )


def _webhook_event() -> dict[str, Any]:
    return _distinct(
        [key.value for key in WebhookEventKey], public_id=21, webhook_id=22, response_code=203, status=True,
        event_time=STAMP, object_before={'before': 1}, object_after={'after': 2}, changes={'changed': 3},
    )


def _webhook() -> dict[str, Any]:
    return _distinct(
        [key.value for key in WebhookKey], public_id=31, owner_id=32, active=False, event_types=['CREATE'],
    )


def _section_template() -> dict[str, Any]:
    return _distinct(
        [key.value for key in SectionTemplateKey], public_id=41, is_global=True, predefined=False,
        fields=[{'name': 'only-field'}],
    )


def _object_log() -> dict[str, Any]:
    keys = [key.value for key in ObjectLogKey if key is not ObjectLogKey.TYPE_ID]
    return _distinct(
        keys, public_id=51, object_id=52, user_id=53, action=2, log_time=STAMP,
        changes={'old': [], 'new': []}, render_state=b'{}',
    )


ROUND_TRIPS: list[tuple[str, Any, Any, Any]] = [
    ('CmdbRackMount', CmdbRackMount.from_data, CmdbRackMount.to_json, _rack_mount),
    ('CmdbWebhookEvent', CmdbWebhookEvent.from_data, CmdbWebhookEvent.to_json, _webhook_event),
    ('CmdbWebhook', CmdbWebhook.from_data, CmdbWebhook.to_json, _webhook),
    ('CmdbSectionTemplate', CmdbSectionTemplate.from_data, CmdbSectionTemplate.to_json, _section_template),
    ('CmdbObjectLog', CmdbObjectLog.from_data, CmdbObjectLog.to_json, _object_log),
    ('TypeSection', TypeSection.from_data, TypeSection.to_json,
     lambda: _distinct([SectionKey.TYPE.value, SectionKey.NAME.value, SectionKey.LABEL.value])),
    ('TypeFieldSection', TypeFieldSection.from_data, TypeFieldSection.to_json,
     lambda: _distinct([SectionKey.TYPE.value, SectionKey.NAME.value, SectionKey.LABEL.value,
                        SectionKey.FIELDS.value], fields=['field-a'])),
    ('TypeMultiDataSection', TypeMultiDataSection.from_data, TypeMultiDataSection.to_json,
     lambda: _distinct([SectionKey.TYPE.value, SectionKey.NAME.value, SectionKey.LABEL.value,
                        SectionKey.FIELDS.value, SectionKey.HIDDEN_FIELDS.value],
                       fields=['field-a', 'field-b'], hidden_fields=['field-b'])),
    ('TypeReferenceSectionEntry', TypeReferenceSectionEntry.from_data, TypeReferenceSectionEntry.to_json,
     lambda: _distinct([key.value for key in SectionReferenceKey], type_id=61, selected_fields=['field-c'])),
    ('TypeReferenceSection', TypeReferenceSection.from_data, TypeReferenceSection.to_json,
     lambda: _distinct([SectionKey.TYPE.value, SectionKey.NAME.value, SectionKey.LABEL.value,
                        SectionKey.FIELDS.value, SectionKey.REFERENCE.value],
                       fields=['field-d'],
                       reference=_distinct([key.value for key in SectionReferenceKey], type_id=62,
                                           selected_fields=['field-e']))),
    ('TypeExternalLink', TypeExternalLink.from_data, TypeExternalLink.to_json,
     lambda: _distinct([key.value for key in ExternalLinkKey], href='https://host/{}', fields=['field-f'])),
    ('TypeSummary', TypeSummary.from_data, TypeSummary.to_json,
     lambda: {TypeSummaryKey.FIELDS.value: ['field-g', 'field-h']}),
]


@pytest.mark.parametrize('builder, read, write, document', ROUND_TRIPS, ids=[case[0] for case in ROUND_TRIPS])
def test_every_key_round_trips_to_itself(builder: str, read: Any, write: Any, document: Any) -> None:
    """from_data then to_json gives back every key with its own value"""
    stored: dict[str, Any] = document()

    written: dict[str, Any] = write(read(dict(stored)))

    assert {key: written.get(key) for key in stored} == stored, builder


def test_the_render_meta_round_trips_each_key() -> None:
    """icon, sections, externals and summary each come back from their own key"""
    stored: dict[str, Any] = {
        TypeSchemaKey.ICON.value: 'icon-value',
        TypeSchemaKey.SECTIONS.value: [{SectionKey.TYPE.value: 'section', SectionKey.NAME.value: 'section-name',
                                        SectionKey.LABEL.value: 'Section', SectionKey.FIELDS.value: ['field-a']}],
        TypeSchemaKey.EXTERNALS.value: [{ExternalLinkKey.NAME.value: 'link', ExternalLinkKey.HREF.value: 'https://x',
                                         ExternalLinkKey.LABEL.value: 'Link', ExternalLinkKey.ICON.value: 'link-icon',
                                         ExternalLinkKey.FIELDS.value: []}],
        TypeSchemaKey.SUMMARY.value: {TypeSummaryKey.FIELDS.value: ['field-a']},
    }

    assert TypeRenderMeta.to_json(TypeRenderMeta.from_data(dict(stored))) == stored


def test_the_render_meta_reads_the_legacy_externals_key() -> None:
    """An older type document spells the list 'external'; it is read and written back as 'externals'"""
    link: dict[str, Any] = {ExternalLinkKey.NAME.value: 'old', ExternalLinkKey.HREF.value: 'https://old',
                            ExternalLinkKey.LABEL.value: 'Old link', ExternalLinkKey.ICON.value: None,
                            ExternalLinkKey.FIELDS.value: []}

    written = TypeRenderMeta.to_json(TypeRenderMeta.from_data({LEGACY_EXTERNALS_KEY: [link]}))

    assert written[TypeSchemaKey.EXTERNALS.value] == [link]


# -------------------------------------------------------------------------------------------------------------------- #
#                                         builders with a context of their own                                         #
# -------------------------------------------------------------------------------------------------------------------- #
def test_a_user_group_round_trips_and_resolves_its_right_names() -> None:
    """public_id / name / label from their own keys; the stored right names resolve against the tree by name"""
    tree: list[BaseRight] = list(ALL_RIGHTS_FLAT)
    granted: list[str] = [tree[1].name, tree[3].name]
    stored: dict[str, Any] = {GroupKey.PUBLIC_ID.value: 71, GroupKey.NAME.value: 'group-name',
                              GroupKey.LABEL.value: 'Group Label', GroupKey.RIGHTS.value: granted}

    written = CmdbUserGroup.to_json(CmdbUserGroup.from_data(dict(stored), rights=tree), insert_mode=True)

    assert written == stored


def test_a_right_writes_each_attribute_under_its_own_key() -> None:
    """level, name, label, description and is_master each from their own attribute"""
    right: BaseRight = ALL_RIGHTS_FLAT[0]

    assert BaseRight.to_dict(right) == {
        RightKey.LEVEL.value: right.level, RightKey.NAME.value: right.name, RightKey.LABEL.value: right.label,
        RightKey.DESCRIPTION.value: right.description, RightKey.IS_MASTER.value: right.is_master,
    }


def test_a_location_node_round_trips_with_its_children() -> None:
    """Every location key from its own place, and the nested node under children"""
    parent: dict[str, Any] = {LocationKey.PUBLIC_ID.value: 81, LocationKey.NAME.value: 'parent-name',
                              LocationKey.PARENT.value: 82, LocationKey.TYPE_ICON.value: 'parent-icon',
                              LocationKey.OBJECT_ID.value: 83, LocationKey.TYPE_SELECTABLE.value: False}
    child: dict[str, Any] = {LocationKey.PUBLIC_ID.value: 84, LocationKey.NAME.value: 'child-name',
                             LocationKey.PARENT.value: 81, LocationKey.TYPE_ICON.value: 'child-icon',
                             LocationKey.OBJECT_ID.value: 85, LocationKey.TYPE_SELECTABLE.value: True}
    node = LocationNode(dict(parent))
    node.children = node.get_children(81, [dict(child)])

    assert LocationNode.to_json(node) == {**parent, LocationNodeKey.CHILDREN.value: [child]}


def test_a_category_node_writes_each_part_under_its_own_key() -> None:
    """category, node_order, children and types each from their own attribute"""
    category = CmdbCategory.from_data({'public_id': 91, 'name': 'category-name', 'label': 'Category',
                                       'meta': {'icon': 'cat-icon', 'order': 7}, 'parent': None, 'types': []})
    child_category = CmdbCategory.from_data({'public_id': 92, 'name': 'child-name', 'label': 'Child',
                                             'meta': {'icon': None, 'order': 1}, 'parent': 91, 'types': []})
    node = CategoryNode(category, children=[CategoryNode(child_category)])

    written = CategoryNode.to_json(node)

    assert written[CategoryNodeKey.CATEGORY.value] == CmdbCategory.to_json(category)
    assert written[CategoryNodeKey.NODE_ORDER.value] == 7
    assert written[CategoryNodeKey.CHILDREN.value] == [CategoryNode.to_json(CategoryNode(child_category))]
    assert written[CategoryNodeKey.TYPES.value] == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                  the declared required keys and index keys                                           #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('model, required', [
    (CmdbRackMount, ['rack_id', 'area']),
    (CmdbSectionTemplate, ['name', 'label', 'type', 'fields']),
    (CmdbWebhook, ['name', 'url', 'event_types', 'active']),
    (CmdbWebhookEvent, ['event_time', 'operation', 'webhook_id', 'object_before', 'object_after', 'changes',
                        'status', 'response_code']),
], ids=lambda value: getattr(value, '__name__', ''))
def test_the_required_keys_are_the_stored_spellings(model: Any, required: list[str]) -> None:
    """A document missing one of these is refused by name, so each must be the key the document stores"""
    assert model.REQUIRED_INIT_KEYS == required


@pytest.mark.parametrize('model, index_keys', [
    (CmdbRackMount, {'object_id': [('object_id', 1)], 'rack_id': [('rack_id', 1)],
                     'rack_area': [('rack_id', 1), ('area', 1)]}),
    (CmdbWebhookEvent, {'webhook_id': [('webhook_id', 1)], 'event_time': [('event_time', -1)]}),
    (CmdbUserGroup, {'name': [('name', 1)]}),
], ids=lambda value: getattr(value, '__name__', ''))
def test_the_indexes_cover_the_stored_keys(model: Any, index_keys: dict[str, list[tuple[str, int]]]) -> None:
    """Each declared index (by name) covers the document keys the reads filter on, in order"""
    declared: dict[str, list[tuple[str, int]]] = {index['name']: list(index['keys']) for index in model.INDEX_KEYS}

    assert declared == index_keys


def test_the_rack_mount_object_index_is_partial_on_the_object_key() -> None:
    """An occupant row omits object_id, so the unique index only covers rows that carry it"""
    object_index: dict[str, Any] = next(index for index in CmdbRackMount.INDEX_KEYS if index['name'] == 'object_id')

    assert object_index['partialFilterExpression'] == {'object_id': {'$exists': True}}
