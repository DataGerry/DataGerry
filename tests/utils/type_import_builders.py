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
Shared fixtures for the CmdbType import unit tests

The import splits over three modules (rules / repairs / helper) whose unit tests all drive the same
shapes: an uploaded type entry, the importing user, and manager stubs recording what the code under
test read and wrote. They live here so the three test modules pin one behaviour each without
re-declaring the scaffolding
"""
from types import SimpleNamespace
from typing import Any

from cmdb.models.type_model import CmdbType
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

NEW_PUBLIC_ID: int = 4711
EXISTING_PUBLIC_ID: int = 4712
MISSING_PUBLIC_ID: int = 9999
BOOM: str = 'boom'
IMPORTER_ID: int = 42
IMPORTER = SimpleNamespace(public_id=IMPORTER_ID)  # the CmdbUser stand-in the entry steps receive

# Dotted paths of the modules under test, for monkeypatching a collaborator by name
HELPER: str = 'cmdb.interface.rest_api.routes.importer_routes.importer_type_helper'
RULES: str = 'cmdb.interface.rest_api.routes.importer_routes.importer_type_rules'
REPAIRS: str = 'cmdb.interface.rest_api.routes.importer_routes.importer_type_repairs'

UNSET: object = object()  # tells a stub "use the default", so None stays a meaningful value


def raise_boom(*_args: Any) -> None:
    """Stands in for a step that fails, with a message the assertions can match on."""
    raise RuntimeError(BOOM)


def unreachable(*_args: Any) -> None:
    """Fails the test if a collaborator is called where none should be needed."""
    raise AssertionError('this collaborator should not be reached')


def type_field(name: str, field_type: str = 'text') -> dict[str, Any]:
    """A type field definition, labelled by its name."""
    return {'type': field_type, 'name': name, 'label': name}


def type_structure(fields: list[dict[str, Any]], sections: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Builds the minimal uploaded-type shape the structure validation reads

    Sections are labelled by their name unless the caller sets a label itself - a section label is
    required (see _missing_section_labels_error) and spelling it out in every case under test would
    only obscure what that case is about.
    """
    labelled = [
        {'label': section.get('name') or 'Section', **section} if isinstance(section, dict) else section
        for section in sections
    ]

    return {'fields': fields, 'render_meta': {'sections': labelled}}


def ref_section_entry(type_id: int) -> dict[str, Any]:
    """An uploaded type whose only section references another type."""
    return {
        'name': 'server',
        'fields': [type_field('ref-1-field', 'ref-section-field')],
        'render_meta': {
            'sections': [{
                'type': 'ref-section',
                'name': 'ref-1',
                'label': 'Reference',
                'fields': [],
                'reference': {'type_id': type_id, 'section_name': 'main', 'selected_fields': ['host']},
            }],
        },
    }


def stored_type(
    special_type: str | None = None,
    selectable_as_parent: bool = True,
    fields: list[dict[str, Any]] | None = None,
) -> CmdbType:
    """A stored CmdbType stand-in for the rules that can only be decided against it."""
    doc = make_type_doc(EXISTING_PUBLIC_ID, 'stored-type', special_type, fields=fields)
    doc['selectable_as_parent'] = selectable_as_parent

    return CmdbType.from_data(doc)


#pylint: disable=too-many-instance-attributes
class StubTypesManager:
    """Records the writes the import performs and can be told to fail at a chosen step."""

    #pylint: disable=too-many-arguments, too-many-positional-arguments
    def __init__(
        self,
        new_public_id: int | Exception = NEW_PUBLIC_ID,
        matched_count: int = 1,
        insert_error: Exception | None = None,
        update_error: Exception | None = None,
        special_type_claimed: bool = False,
        existing_named_type: dict[str, Any] | None = None,
        existing_type_ids: set[int] | None = None,
        existence_error: Exception | None = None,
        stored_type_instance: Any = UNSET,
        existing_group_ids: set[int] | None = None,
    ) -> None:
        self.new_public_id = new_public_id
        self.matched_count = matched_count
        self.special_type_claimed = special_type_claimed
        self.existing_named_type = existing_named_type
        self.existing_type_ids = existing_type_ids if existing_type_ids is not None else set()
        self.existing_group_ids = existing_group_ids if existing_group_ids is not None else set()
        self.existence_error = existence_error
        self.insert_error = insert_error
        self.update_error = update_error
        # What the pre-update read hands back; by default the type being updated exists
        self.stored_type = stored_type() if stored_type_instance is UNSET else stored_type_instance
        self.inserted: list[Any] = []
        self.updated: list[tuple[int, Any]] = []
        self.existence_lookups: list[list[int]] = []
        self.group_lookups: list[Any] = []
        self.instance_reads: list[int] = []

    def get_new_type_public_id(self) -> int:
        """Return the next public_id, or raise when the stub was configured to fail."""
        if isinstance(self.new_public_id, Exception):
            raise self.new_public_id

        return self.new_public_id

    def insert_type(self, new_type: Any) -> None:
        """Record the insert, or raise when the stub was configured to fail."""
        if self.insert_error:
            raise self.insert_error

        self.inserted.append(new_type)

    def get_one_by(self, criteria: dict[str, Any]) -> dict[str, Any] | None:
        """Return the stored type matching the name criteria, if the stub was given one."""
        _ = criteria

        return self.existing_named_type

    def get_type_instance(self, public_id: int) -> Any:
        """Record the read and hand back the stored type the update reconciles against."""
        self.instance_reads.append(public_id)

        return self.stored_type

    def get_existing_type_ids(self, public_ids: list[int]) -> set[int]:
        """Record the existence lookup and report which of the referenced type ids exist."""
        if self.existence_error:
            raise self.existence_error

        self.existence_lookups.append(public_ids)

        return {public_id for public_id in public_ids if public_id in self.existing_type_ids}

    def get_many_from_other_collection(self, collection: str, **requirements: Any) -> list[dict[str, Any]]:
        """Stand in for the cross-collection read the ACL-group repair uses."""
        self.group_lookups.append((collection, requirements))
        wanted = requirements.get('public_id', {}).get('$in', [])

        return [{'public_id': group_id} for group_id in wanted if group_id in self.existing_group_ids]

    def check_special_type_exists(self, special_type: str) -> bool:
        """Report whether the special-type marker is already claimed by another type."""
        _ = special_type

        return self.special_type_claimed

    def update_type(self, public_id: int, update_type: Any) -> SimpleNamespace:
        """Record the update and report how many documents it matched, mirroring UpdateResult."""
        if self.update_error:
            raise self.update_error

        self.updated.append((public_id, update_type))

        return SimpleNamespace(matched_count=self.matched_count)


def no_templates() -> "StubSectionTemplatesManager":
    """A section-templates stub that knows no template - what every test not about them needs."""
    return StubSectionTemplatesManager()


class StubSectionTemplatesManager:
    """Hands back the global section templates a test seeded, recording what was asked for."""

    def __init__(self, templates: list[dict[str, Any]] | None = None, find_error: Exception | None = None) -> None:
        self.templates = templates or []
        self.find_error = find_error
        self.queries: list[dict[str, Any]] = []

    def find(self, criteria: dict[str, Any]) -> list[dict[str, Any]]:
        """Return the seeded templates matching the name filter of the criteria."""
        if self.find_error:
            raise self.find_error

        self.queries.append(criteria)
        wanted = criteria.get('name', {}).get('$in', [])

        return [template for template in self.templates if template.get('name') in wanted]
