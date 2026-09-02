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
Unit tests for cmdb.interface.rest_api.routes.importer_routes.importer_type_rules

One class per rule the type import judges an uploaded entry by: the structural rules gathered by
validate_type_structure (names, labels, field / section types, options, the location field, section
membership, summary + external links), the name and special_type rules, the boolean flags, and the
rules that can only be answered against the stored type. Every rule returns a message instead of
raising, so no Flask app and no database are involved - the manager is a stub throughout.
"""
from typing import Any

import pytest

from cmdb.models.type_model import TypeSchemaKey, DG_LOCATION_FIELD_NAME
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.interface.rest_api.routes.importer_routes.importer_type_constants import (
    STRUCTURE_ERROR_SEPARATOR,
    TypeImportError,
)
from cmdb.interface.rest_api.routes.importer_routes.importer_type_rules import (
    special_type_license_error,
    uses_ports_license_error,
    validate_create_special_type,
    validate_type_structure,
    normalize_boolean_flags,
    missing_type_name_error,
    type_name_conflict_error,
    stored_type_update_blocker,
    as_public_id,
)
from cmdb.interface.rest_api.routes.importer_routes.importer_type_helper import (
    create_type_from_entry,
    update_type_from_entry,
)
from tests.utils.ipam_doc_builders import make_type_doc
from tests.utils.type_import_builders import (
    EXISTING_PUBLIC_ID,
    IMPORTER,
    RULES,
    StubTypesManager,
    no_templates,
    stored_type,
    type_field,
    type_structure,
    unreachable,
)
# -------------------------------------------------------------------------------------------------------------------- #


class TestValidateTypeStructure:
    """Field-name uniqueness, section-name uniqueness, and one-section-per-field."""

    def test_sound_structure_passes(self) -> None:
        """Unique names with every field in exactly one section is valid."""
        entry = type_structure(
            [type_field('host'), type_field('city')],
            [{'type': 'section', 'name': 'main', 'fields': ['host', 'city']}],
        )

        assert validate_type_structure(entry) is None

    def test_duplicate_field_names_are_reported(self) -> None:
        """A field name is an identifier - it may not repeat."""
        entry = type_structure(
            [type_field('host'), type_field('host')],
            [{'type': 'section', 'name': 'main', 'fields': ['host']}],
        )

        assert validate_type_structure(entry) == TypeImportError.DUPLICATE_FIELD_NAMES.format(names=['host'])

    def test_duplicate_section_names_are_reported(self) -> None:
        """Section names must be unique within the type."""
        entry = type_structure(
            [type_field('host'), type_field('city')],
            [
                {'type': 'section', 'name': 'main', 'fields': ['host']},
                {'type': 'section', 'name': 'main', 'fields': ['city']},
            ],
        )

        assert validate_type_structure(entry) == \
            TypeImportError.DUPLICATE_SECTION_NAMES.format(names=['main'])

    def test_field_in_two_sections_is_reported(self) -> None:
        """A field belongs to exactly one section."""
        entry = type_structure(
            [type_field('host')],
            [
                {'type': 'section', 'name': 'a', 'fields': ['host']},
                {'type': 'section', 'name': 'b', 'fields': ['host']},
            ],
        )

        assert validate_type_structure(entry) == \
            TypeImportError.FIELD_IN_MULTIPLE_SECTIONS.format(names=['host'])

    def test_field_without_a_section_is_reported(self) -> None:
        """An orphaned field belongs to no section and is rejected."""
        entry = type_structure([type_field('host'), type_field('orphan')],
                           [{'type': 'section', 'name': 'main', 'fields': ['host']}])

        assert validate_type_structure(entry) == \
            TypeImportError.FIELD_WITHOUT_SECTION.format(names=['orphan'])

    def test_every_problem_is_reported_together(self) -> None:
        """One round trip surfaces all structural findings, joined into the entry's message."""
        entry = type_structure(
            [type_field('host'), type_field('host'), type_field('orphan')],
            [
                {'type': 'section', 'name': 'main', 'fields': ['host']},
                {'type': 'section', 'name': 'main', 'fields': ['host']},
            ],
        )

        result = validate_type_structure(entry)

        assert 'Duplicate field name(s)' in result
        assert 'Duplicate section name(s)' in result
        assert 'more than one section' in result
        assert 'not assigned to any section' in result

    def test_mds_hidden_fields_count_as_assigned(self) -> None:
        """A multi-data-section's hidden_fields are an assignment, not an orphan."""
        entry = type_structure(
            [type_field('visible'), type_field('tucked-away')],
            [{
                'type': 'multi-data-section', 'name': 'mds',
                'fields': ['visible'], 'hidden_fields': ['tucked-away'],
            }],
        )

        assert validate_type_structure(entry) is None

    def test_ref_section_implicit_field_counts_as_assigned(self) -> None:
        """A ref-section owns '<section>-field' by convention, though it lists no fields itself.

        Regression guard: without this carve-out every type containing a ref-section would be rejected
        as having an orphaned field (see cmdb_multi_render._merge_reference_section).
        """
        entry = type_structure(
            [type_field('host'), type_field('refsec-field', 'ref-section-field')],
            [
                {'type': 'section', 'name': 'main', 'fields': ['host']},
                {'type': 'ref-section', 'name': 'refsec',
                 'reference': {'type_id': 2, 'section_name': 'main', 'selected_fields': []},
                 'fields': []},
            ],
        )

        assert validate_type_structure(entry) is None

    @pytest.mark.parametrize('entry', ['not-a-dict', None, 42], ids=['string', 'none', 'number'])
    def test_non_dict_entry_is_left_to_the_other_checks(self, entry: Any) -> None:
        """A malformed entry is not this check's business - it is reported by the build step."""
        assert validate_type_structure(entry) is None

    def test_missing_fields_and_sections_are_sound(self) -> None:
        """A type carrying neither fields nor sections has nothing to contradict."""
        assert validate_type_structure({}) is None

    def test_malformed_section_entry_is_skipped(self) -> None:
        """A non-dict section in the list is ignored rather than crashing the check."""
        entry = type_structure(
            [type_field('host')],
            ['not-a-section', {'type': 'section', 'name': 'main', 'fields': ['host']}],
        )

        assert validate_type_structure(entry) is None

    def test_ref_section_without_a_name_claims_nothing(self) -> None:
        """A nameless ref-section cannot own an implicit field, so the real field stays orphaned."""
        entry = type_structure(
            [type_field('refsec-field', 'ref')],
            [{'type': 'ref-section', 'name': '', 'fields': []}],
        )

        # typed 'ref' rather than 'ref-section-field', so it is NOT exempt and stays orphaned
        assert validate_type_structure(entry) == STRUCTURE_ERROR_SEPARATOR.join([
            TypeImportError.MISSING_SECTION_NAMES.format(positions=[0]),
            TypeImportError.FIELD_WITHOUT_SECTION.format(names=['refsec-field']),
        ])


class TestFieldTypeRule:
    """Every field must declare a known FieldType."""

    def test_known_types_pass(self) -> None:
        """A type whose fields all use known FieldTypes is valid."""
        entry = type_structure(
            [type_field('a', 'text'), type_field('b', 'number'), type_field('c', 'checkbox')],
            [{'type': 'section', 'name': 'main', 'fields': ['a', 'b', 'c']}],
        )

        assert validate_type_structure(entry) is None

    def test_unknown_type_is_reported_with_the_field_name(self) -> None:
        """The message names the offending field and its bogus type."""
        entry = type_structure(
            [type_field('a', 'text'), type_field('bogus', 'not-a-type')],
            [{'type': 'section', 'name': 'main', 'fields': ['a', 'bogus']}],
        )

        result = validate_type_structure(entry)

        assert 'bogus (not-a-type)' in result
        assert 'text' in result  # the message lists the allowed types

    def test_missing_type_is_reported(self) -> None:
        """A field with no type at all is invalid."""
        entry = type_structure(
            [{'name': 'a', 'label': 'A'}],
            [{'type': 'section', 'name': 'main', 'fields': ['a']}],
        )

        assert 'a (None)' in validate_type_structure(entry)


class TestSectionFieldMustExistRule:
    """A section may only reference fields the type actually defines."""

    def test_undefined_section_field_is_reported(self) -> None:
        """A section naming a field that is not in `fields` is rejected."""
        entry = type_structure(
            [type_field('a')],
            [{'type': 'section', 'name': 'main', 'fields': ['a', 'ghost']}],
        )

        assert validate_type_structure(entry) == \
            TypeImportError.SECTION_FIELD_NOT_DEFINED.format(names=['ghost'])

    def test_mds_hidden_field_must_exist_too(self) -> None:
        """A hidden_fields entry is also a reference and must resolve."""
        entry = type_structure(
            [type_field('visible')],
            [{'type': 'multi-data-section', 'name': 'mds',
              'fields': ['visible'], 'hidden_fields': ['ghost']}],
        )

        assert 'ghost' in validate_type_structure(entry)


class TestSectionTypeRule:
    """Every section must declare a known SectionType."""

    @pytest.mark.parametrize('section_type', ['section', 'multi-data-section'], ids=['plain', 'mds'])
    def test_known_section_types_pass(self, section_type: str) -> None:
        """A section using a known SectionType is valid."""
        entry = type_structure(
            [type_field('host')],
            [{'type': section_type, 'name': 'main', 'fields': ['host']}],
        )

        assert validate_type_structure(entry) is None

    def test_unknown_section_type_is_reported_with_the_section_name(self) -> None:
        """An unknown marker would be imported as a plain section, so it is refused."""
        entry = type_structure(
            [type_field('host')],
            [{'type': 'mutli-data-section', 'name': 'main', 'fields': ['host']}],
        )

        assert validate_type_structure(entry) == TypeImportError.INVALID_SECTION_TYPES.format(
            sections=['main (mutli-data-section)'],
            allowed='section, multi-data-section, ref-section',
        )

    def test_missing_section_type_is_reported(self) -> None:
        """A section without a type is as unusable as one with an unknown type."""
        entry = type_structure([type_field('host')], [{'name': 'main', 'fields': ['host']}])

        assert 'main (None)' in validate_type_structure(entry)


class TestNameCompletenessRules:
    """A field or section without a name cannot be identified, so it is reported by position."""

    @pytest.mark.parametrize('name', ['', '   ', None, 42], ids=['empty', 'blank', 'none', 'number'])
    def test_field_without_a_usable_name_is_reported(self, name: Any) -> None:
        """The offending field is pointed at by its position in the uploaded fields list."""
        entry = type_structure(
            [type_field('host'), {'type': 'text', 'name': name, 'label': 'broken'}],
            [{'type': 'section', 'name': 'main', 'fields': ['host']}],
        )

        assert TypeImportError.MISSING_FIELD_NAMES.format(positions=[1]) in validate_type_structure(entry)

    def test_section_without_a_usable_name_is_reported(self) -> None:
        """The offending section is pointed at by its position in the uploaded section list."""
        entry = type_structure(
            [type_field('host')],
            [{'type': 'section', 'name': None, 'fields': ['host']}],
        )

        assert TypeImportError.MISSING_SECTION_NAMES.format(positions=[0]) in validate_type_structure(entry)

    def test_named_fields_and_sections_pass(self) -> None:
        """Nothing is reported when every field and section carries a name."""
        entry = type_structure(
            [type_field('host')],
            [{'type': 'section', 'name': 'main', 'fields': ['host']}],
        )

        assert validate_type_structure(entry) is None


class TestEmptySectionRule:
    """A section must hold at least one field."""

    def test_section_without_fields_is_reported(self) -> None:
        """An empty plain section renders as an empty box, so it is refused."""
        entry = type_structure(
            [type_field('host')],
            [
                {'type': 'section', 'name': 'main', 'fields': ['host']},
                {'type': 'section', 'name': 'empty', 'fields': []},
            ],
        )

        assert validate_type_structure(entry) == TypeImportError.EMPTY_SECTION.format(names=['empty'])

    def test_section_with_a_missing_fields_key_is_reported(self) -> None:
        """A section that brings no fields list at all holds nothing either."""
        entry = type_structure(
            [type_field('host')],
            [
                {'type': 'section', 'name': 'main', 'fields': ['host']},
                {'type': 'section', 'name': 'empty'},
            ],
        )

        assert TypeImportError.EMPTY_SECTION.format(names=['empty']) in validate_type_structure(entry)

    def test_mds_hidden_fields_count_as_content(self) -> None:
        """An MDS section whose only field is hidden is not empty."""
        entry = type_structure(
            [type_field('host')],
            [{'type': 'multi-data-section', 'name': 'mds', 'fields': [], 'hidden_fields': ['host']}],
        )

        assert validate_type_structure(entry) is None

    def test_ref_section_is_exempt(self) -> None:
        """A ref-section owns no field list of its own - its content is the referenced section."""
        entry = type_structure(
            [type_field('host'), type_field('ref-1-field', 'ref-section-field')],
            [
                {'type': 'section', 'name': 'main', 'fields': ['host']},
                {'type': 'ref-section', 'name': 'ref-1', 'fields': []},
            ],
        )

        assert validate_type_structure(entry) is None

    def test_nameless_empty_section_is_only_reported_once(self) -> None:
        """An empty section without a name is covered by the missing-name rule alone."""
        entry = type_structure([type_field('host')], [
            {'type': 'section', 'name': 'main', 'fields': ['host']},
            {'type': 'section', 'name': '', 'fields': []},
        ])

        assert validate_type_structure(entry) == TypeImportError.MISSING_SECTION_NAMES.format(positions=[1])


class TestSummaryAndExternalFieldRules:
    """render_meta.summary and the external links may only name defined fields."""

    @staticmethod
    def _with_render_meta(**render_meta: Any) -> dict[str, Any]:
        """Builds an uploaded type with one defined field plus the given render_meta extras."""
        return {
            'fields': [type_field('host')],
            'render_meta': {
                'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': ['host']}],
                **render_meta,
            },
        }

    def test_summary_of_defined_fields_passes(self) -> None:
        """A summary naming a defined field is sound."""
        assert validate_type_structure(self._with_render_meta(summary={'fields': ['host']})) is None

    def test_empty_summary_passes(self) -> None:
        """A type without a summary line has nothing to contradict."""
        assert validate_type_structure(self._with_render_meta(summary={'fields': []})) is None

    def test_undefined_summary_field_is_reported(self) -> None:
        """A summary field the type does not define would render as a blank."""
        entry = self._with_render_meta(summary={'fields': ['host', 'ghost']})

        assert validate_type_structure(entry) == TypeImportError.SUMMARY_FIELD_NOT_DEFINED.format(names=['ghost'])

    def test_malformed_summary_is_skipped(self) -> None:
        """A summary that is not a dictionary is left to the build step."""
        assert validate_type_structure(self._with_render_meta(summary='nonsense')) is None

    def test_undefined_external_field_is_reported(self) -> None:
        """An external link can only interpolate fields the type defines."""
        entry = self._with_render_meta(externals=[
            {'name': 'wiki', 'href': 'http://example.org/{}', 'fields': ['ghost']},
        ])

        assert validate_type_structure(entry) == TypeImportError.EXTERNAL_FIELD_NOT_DEFINED.format(names=['ghost'])

    def test_external_of_defined_fields_passes(self) -> None:
        """An external link naming a defined field is sound."""
        entry = self._with_render_meta(externals=[
            {'name': 'wiki', 'href': 'http://example.org/{}', 'fields': ['host']},
        ])

        assert validate_type_structure(entry) is None

    def test_legacy_external_spelling_is_validated_too(self) -> None:
        """Older documents spell the list 'external'; TypeRenderMeta reads it, so the rules do too."""
        entry = self._with_render_meta(external=[
            {'name': 'wiki', 'href': 'http://example.org/{}', 'fields': ['ghost']},
        ])

        assert validate_type_structure(entry) == TypeImportError.EXTERNAL_FIELD_NOT_DEFINED.format(names=['ghost'])


class TestTypeNameConflictError:
    """The type name must be unique across the installation."""

    def test_free_name_passes(self) -> None:
        """No stored type with that name means the name is available."""
        assert type_name_conflict_error({'name': 'fresh'}, StubTypesManager()) is None

    def test_taken_name_is_reported_on_create(self) -> None:
        """A stored type already using the name blocks the create."""
        types_manager = StubTypesManager(existing_named_type={'public_id': 99, 'name': 'taken'})

        assert type_name_conflict_error({'name': 'taken'}, types_manager) == \
            TypeImportError.TYPE_NAME_EXISTS.format(name='taken')

    def test_a_type_may_keep_its_own_name_on_update(self) -> None:
        """The type being replaced is excluded, so keeping its own name is not a conflict."""
        types_manager = StubTypesManager(existing_named_type={'public_id': 7, 'name': 'mine'})

        assert type_name_conflict_error({'name': 'mine', 'public_id': 7}, types_manager, 7) is None

    def test_another_types_name_still_conflicts_on_update(self) -> None:
        """Renaming onto a name a different type already holds is refused."""
        types_manager = StubTypesManager(existing_named_type={'public_id': 99, 'name': 'theirs'})

        assert type_name_conflict_error({'name': 'theirs', 'public_id': 7}, types_manager, 7) == \
            TypeImportError.TYPE_NAME_EXISTS.format(name='theirs')

    @pytest.mark.parametrize('entry', [{}, {'name': ''}, 'not-a-dict'], ids=['absent', 'empty', 'non-dict'])
    def test_entry_without_a_name_is_left_to_the_build_step(self, entry: Any) -> None:
        """A nameless entry is rejected when the CmdbType is built, not here."""
        assert type_name_conflict_error(entry, StubTypesManager()) is None


class TestMalformedRenderMetaIsTolerated:
    """Nonsense in the presentation data is skipped rather than crashing a rule."""

    def test_non_list_externals_are_skipped(self) -> None:
        """An externals value that is not a list is left to the build step."""
        entry = {
            'fields': [type_field('host')],
            'render_meta': {
                'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': ['host']}],
                'externals': 'nonsense',
            },
        }

        assert validate_type_structure(entry) is None

    def test_non_list_summary_fields_are_skipped(self) -> None:
        """A summary whose fields value is not a list references nothing."""
        entry = {
            'fields': [type_field('host')],
            'render_meta': {
                'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': ['host']}],
                'summary': {'fields': 'host'},
            },
        }

        assert validate_type_structure(entry) is None


class TestMissingTypeNameError:
    """A type needs a name, and it is reported as such instead of as a model failure."""

    @pytest.mark.parametrize('name', ['', '   ', None, 7], ids=['empty', 'blank', 'none', 'number'])
    def test_unusable_name_is_reported(self, name: Any) -> None:
        """A missing or blank name is rejected."""
        assert missing_type_name_error({'name': name}) == TypeImportError.MISSING_TYPE_NAME.value

    def test_absent_name_key_is_reported(self) -> None:
        """An entry without a name key at all is rejected."""
        assert missing_type_name_error({}) == TypeImportError.MISSING_TYPE_NAME.value

    def test_named_type_passes(self) -> None:
        """A named type passes."""
        assert missing_type_name_error({'name': 'server'}) is None

    @pytest.mark.parametrize('entry', ['a string', 42, None], ids=['str', 'int', 'none'])
    def test_non_dict_entry_is_left_to_the_build_step(self, entry: Any) -> None:
        """A malformed entry is not this check's business."""
        assert missing_type_name_error(entry) is None


class TestSpecialTypeLicenseError:
    """special_type_license_error blocks importing an IPAM special type onto an unlicensed instance."""

    def test_special_type_is_rejected_when_ipam_is_locked(self) -> None:
        """A locked instance reports the entry instead of installing the special type."""
        entry = {TypeSchemaKey.SPECIAL_TYPE.value: 'SUBNET'}

        result = special_type_license_error(entry, ipam_locked=True)

        assert result == TypeImportError.SPECIAL_TYPE_NOT_LICENSED.format(special_type='SUBNET')

    def test_special_type_is_allowed_when_ipam_is_licensed(self) -> None:
        """A licensed instance imports the special type normally."""
        entry = {TypeSchemaKey.SPECIAL_TYPE.value: 'SUBNET'}

        assert special_type_license_error(entry, ipam_locked=False) is None

    @pytest.mark.parametrize(
        'entry',
        [{}, {TypeSchemaKey.SPECIAL_TYPE.value: ''}, {TypeSchemaKey.SPECIAL_TYPE.value: None}, 'not-a-dict'],
        ids=['absent', 'empty', 'null', 'non-dict'],
    )
    def test_ordinary_entry_is_never_blocked(self, entry: Any) -> None:
        """An entry carrying no special_type is unaffected by the licence state."""
        assert special_type_license_error(entry, ipam_locked=True) is None


class TestValidateCreateSpecialType:
    """The special_type rules that govern creating a CmdbType by import."""

    @pytest.mark.parametrize(
        'entry',
        [{}, {TypeSchemaKey.SPECIAL_TYPE.value: ''}, {TypeSchemaKey.SPECIAL_TYPE.value: None}, 'not-a-dict'],
        ids=['absent', 'empty', 'null', 'non-dict'],
    )
    def test_entry_without_a_special_type_passes(self, entry: Any) -> None:
        """An ordinary type is unaffected - an exported one carries special_type '' which means none."""
        assert validate_create_special_type(entry, StubTypesManager(), ipam_locked=False) is None

    def test_known_unclaimed_special_type_passes(self) -> None:
        """A valid, unclaimed marker on a licensed instance is allowed."""
        entry = {TypeSchemaKey.SPECIAL_TYPE.value: SpecialType.SUBNET.value}

        assert validate_create_special_type(entry, StubTypesManager(), ipam_locked=False) is None

    def test_unknown_value_is_rejected(self) -> None:
        """Only a SpecialType member may be assigned."""
        entry = {TypeSchemaKey.SPECIAL_TYPE.value: 'NOT_A_SPECIAL_TYPE'}

        result = validate_create_special_type(entry, StubTypesManager(), ipam_locked=False)

        assert result.startswith('"NOT_A_SPECIAL_TYPE" is not a valid special Type')
        assert SpecialType.SUBNET.value in result  # the message lists what is allowed

    def test_unknown_value_is_rejected_before_the_licence_check(self) -> None:
        """A garbage value reports itself rather than a misleading licence message."""
        entry = {TypeSchemaKey.SPECIAL_TYPE.value: 'NOT_A_SPECIAL_TYPE'}

        result = validate_create_special_type(entry, StubTypesManager(), ipam_locked=True)

        assert 'not a valid special Type' in result

    def test_locked_feature_is_rejected(self) -> None:
        """A valid marker still needs the IPAM feature."""
        entry = {TypeSchemaKey.SPECIAL_TYPE.value: SpecialType.VLAN.value}

        result = validate_create_special_type(entry, StubTypesManager(), ipam_locked=True)

        assert result == TypeImportError.SPECIAL_TYPE_NOT_LICENSED.format(special_type=SpecialType.VLAN.value)

    def test_already_claimed_marker_is_rejected(self) -> None:
        """A special type can exist only once."""
        entry = {TypeSchemaKey.SPECIAL_TYPE.value: SpecialType.SUPERNET.value}
        types_manager = StubTypesManager(special_type_claimed=True)

        result = validate_create_special_type(entry, types_manager, ipam_locked=False)

        assert result == TypeImportError.SPECIAL_TYPE_EXISTS.format(special_type=SpecialType.SUPERNET.value)

    def test_uniqueness_is_not_queried_for_an_ordinary_type(self) -> None:
        """The database is only consulted for entries that actually declare a marker."""
        types_manager = StubTypesManager(special_type_claimed=True)

        assert validate_create_special_type({}, types_manager, ipam_locked=False) is None


class TestNormalizeBooleanFlags:
    """The optional boolean flags: each defaults to its own value and accepts the import spellings."""

    @pytest.mark.parametrize('flag', ['active', 'selectable_as_parent'])
    @pytest.mark.parametrize('value', [None, ''], ids=['none', 'empty'])
    def test_absent_flag_defaults_to_true(self, flag: str, value: Any) -> None:
        """An omitted or empty flag becomes True, the value a new type starts with."""
        entry = {'name': 'server', flag: value}

        assert normalize_boolean_flags(entry) is None
        assert entry[flag] is True

    def test_missing_keys_are_added(self) -> None:
        """An entry bringing no flag at all ends up with every one of them at its own default."""
        entry: dict[str, Any] = {'name': 'server'}

        assert normalize_boolean_flags(entry) is None
        assert entry['active'] is True
        assert entry['selectable_as_parent'] is True
        assert entry['uses_ports'] is False

    @pytest.mark.parametrize('value', [None, ''], ids=['none', 'empty'])
    def test_uses_ports_defaults_to_false_not_true(self, value: Any) -> None:
        """
        uses_ports is the one flag whose default is False.

        The other two mean "a type is usable and can parent a location unless it says otherwise";
        opting a type into Port Connectivity is the opposite - a deliberate choice, and an
        IPAM-licensed one. A shared default of True would have silently declared every imported type
        port-bearing.
        """
        entry = {'name': 'server', 'uses_ports': value}

        assert normalize_boolean_flags(entry) is None
        assert entry['uses_ports'] is False

    @pytest.mark.parametrize(
        'value, expected',
        [(True, True), ('true', True), ('YES', True), (1, True),
         (False, False), ('no', False), (0, False)],
    )
    def test_uses_ports_accepts_the_lenient_spellings(self, value: Any, expected: bool) -> None:
        """The new flag is parsed like its siblings, not treated as a raw truthiness test."""
        entry = {'name': 'server', 'uses_ports': value}

        assert normalize_boolean_flags(entry) is None
        assert entry['uses_ports'] is expected

    @pytest.mark.parametrize(
        'value, expected',
        [(True, True), ('true', True), ('YES', True), (1, True),
         (False, False), ('false', False), ('no', False), (0, False)],
    )
    def test_provided_values_are_parsed(self, value: Any, expected: bool) -> None:
        """The lenient import spellings are accepted and stored as real booleans."""
        entry = {'name': 'server', 'active': value}

        assert normalize_boolean_flags(entry) is None
        assert entry['active'] is expected

    def test_unusable_value_is_reported(self) -> None:
        """A value that is not a boolean at all is reported instead of being stored."""
        entry = {'name': 'server', 'active': 'maybe'}

        assert normalize_boolean_flags(entry) == \
            TypeImportError.INVALID_BOOLEAN_VALUE.format(field='active', value="'maybe'")
        assert entry['active'] == 'maybe'  # left untouched for the report to quote

    def test_both_unusable_values_are_reported_together(self) -> None:
        """Like the structural rules, every finding is reported in one message."""
        entry = {'name': 'server', 'active': 'maybe', 'selectable_as_parent': 'perhaps'}

        assert normalize_boolean_flags(entry) == STRUCTURE_ERROR_SEPARATOR.join([
            TypeImportError.INVALID_BOOLEAN_VALUE.format(field='active', value="'maybe'"),
            TypeImportError.INVALID_BOOLEAN_VALUE.format(field='selectable_as_parent', value="'perhaps'"),
        ])

    @pytest.mark.parametrize('entry', ['a string', 42, None], ids=['str', 'int', 'none'])
    def test_non_dict_entry_is_ignored(self, entry: Any) -> None:
        """A malformed entry is left to the build step rather than crashing here."""
        assert normalize_boolean_flags(entry) is None


class TestUsesPortsLicenseError:
    """uses_ports_license_error blocks importing a port-bearing type onto an unlicensed instance."""

    def test_enabled_flag_is_refused_when_ipam_is_locked(self) -> None:
        """The import reports the entry instead of aborting, so the rest of the upload survives."""
        entry = {'name': 'switch', 'uses_ports': True}

        assert uses_ports_license_error(entry, ipam_locked=True) == \
            TypeImportError.USES_PORTS_NOT_LICENSED.format(name='switch')

    def test_enabled_flag_is_allowed_when_ipam_is_licensed(self) -> None:
        """With the license the flag imports like any other field."""
        assert uses_ports_license_error({'name': 'switch', 'uses_ports': True}, ipam_locked=False) is None

    @pytest.mark.parametrize('value', [False, None], ids=['false', 'absent'])
    def test_a_type_that_does_not_use_ports_imports_unlicensed(self, value: Any) -> None:
        """
        Only turning the flag ON is gated, matching the route guard.

        This is what lets a port-bearing type be exported from a licensed instance and imported into
        an unlicensed one with the flag off, rather than the whole entry being rejected.
        """
        entry: dict[str, Any] = {'name': 'switch'}

        if value is not None:
            entry['uses_ports'] = value

        assert uses_ports_license_error(entry, ipam_locked=True) is None

    @pytest.mark.parametrize('entry', ['a string', 42, None], ids=['str', 'int', 'none'])
    def test_non_dict_entry_is_ignored(self, entry: Any) -> None:
        """A malformed entry is left to the structural rules."""
        assert uses_ports_license_error(entry, ipam_locked=True) is None

    def test_create_rejects_an_unusable_flag_without_writing(self) -> None:
        """An unparsable flag fails the entry, like any other per-entry rule."""
        entry = make_type_doc(0, 'imported-type')
        entry['active'] = 'maybe'
        types_manager = StubTypesManager()

        assert create_type_from_entry(entry, types_manager, no_templates(), IMPORTER) == \
            TypeImportError.INVALID_BOOLEAN_VALUE.format(field='active', value="'maybe'")
        assert not types_manager.inserted

    def test_update_never_writes_the_version(self) -> None:
        """The stored version is a fact about this system, so an update leaves it alone."""
        entry = make_type_doc(EXISTING_PUBLIC_ID, 'imported-type')
        entry['version'] = '9.9.9'
        types_manager = StubTypesManager()

        assert update_type_from_entry(entry, types_manager, no_templates(), IMPORTER) is None

        _, payload = types_manager.updated[0]

        assert TypeSchemaKey.VERSION.value not in payload

    def test_update_rejects_an_unusable_flag_without_writing(self) -> None:
        """The update path applies the same flag rule as the create path."""
        entry = make_type_doc(EXISTING_PUBLIC_ID, 'imported-type')
        entry['selectable_as_parent'] = 'perhaps'
        types_manager = StubTypesManager()

        assert update_type_from_entry(entry, types_manager, no_templates(), IMPORTER) == \
            TypeImportError.INVALID_BOOLEAN_VALUE.format(field='selectable_as_parent', value="'perhaps'")
        assert not types_manager.updated


class TestStoredTypeUpdateBlocker:
    """The rules an update can only answer once the stored Type has been read."""

    @pytest.fixture(autouse=True)
    def _allow_the_location_rules(self, monkeypatch) -> None:
        """Neither location rule blocks by default; the tests that care patch them again."""
        monkeypatch.setattr(f'{RULES}.location_field_removal_blocker', lambda *_args: None)
        monkeypatch.setattr(f'{RULES}.selectable_as_parent_change_blocker', lambda *_args: None)

    def test_an_ordinary_update_passes(self) -> None:
        """Nothing about the stored type refuses a plain edit."""
        assert stored_type_update_blocker(IMPORTER, stored_type(), stored_type(), False) is None

    def test_a_stored_special_type_needs_the_licence(self) -> None:
        """The uploaded value is not consulted: what matters is that the STORED type is special."""
        old_type = stored_type(SpecialType.SUBNET.value)
        new_type = stored_type()  # the upload omits the marker entirely

        assert stored_type_update_blocker(IMPORTER, old_type, new_type, True) \
            == TypeImportError.SPECIAL_TYPE_NOT_LICENSED.format(special_type=SpecialType.SUBNET.value)

    def test_an_ordinary_stored_type_is_not_licence_gated(self) -> None:
        """A locked IPAM feature does not get in the way of ordinary types."""
        assert stored_type_update_blocker(IMPORTER, stored_type(), stored_type(), True) is None

    def test_a_different_uploaded_marker_is_refused(self) -> None:
        """The marker is immutable, so the entry is reported instead of silently keeping the stored one."""
        old_type = stored_type(SpecialType.SUBNET.value)
        new_type = stored_type(SpecialType.VLAN.value)

        assert stored_type_update_blocker(IMPORTER, old_type, new_type, False) \
            == TypeImportError.SPECIAL_TYPE_IMMUTABLE.format(
                stored=SpecialType.SUBNET.value, uploaded=SpecialType.VLAN.value)

    def test_clearing_the_marker_is_refused(self) -> None:
        """An upload without the marker would strip it, which an update may not do."""
        blocker = stored_type_update_blocker(
            IMPORTER, stored_type(SpecialType.SUBNET.value), stored_type(), False,
        )

        assert blocker == TypeImportError.SPECIAL_TYPE_IMMUTABLE.format(
            stored=SpecialType.SUBNET.value, uploaded=None)

    def test_the_same_marker_passes(self) -> None:
        """Re-importing an exported special type carries its own marker - that is not a change."""
        assert stored_type_update_blocker(
            IMPORTER, stored_type(SpecialType.SUBNET.value), stored_type(SpecialType.SUBNET.value), False,
        ) is None

    def test_an_ordinary_type_is_unchanged_whether_the_marker_is_empty_or_absent(self) -> None:
        """An exported ordinary type carries `special_type: ''` - that must not read as a change."""
        stored = stored_type()
        stored.special_type = None  # a stored type may carry None where the export carries ''

        assert stored_type_update_blocker(IMPORTER, stored, stored_type(), False) is None

    def test_the_location_field_rule_is_delegated(self, monkeypatch) -> None:
        """The blocker the normal update route aborts with is reported per entry instead."""
        monkeypatch.setattr(f'{RULES}.location_field_removal_blocker', lambda *_args: 'no location removal')

        assert stored_type_update_blocker(IMPORTER, stored_type(), stored_type(), False) \
            == 'no location removal'

    def test_the_selectable_as_parent_rule_is_delegated(self, monkeypatch) -> None:
        """Same for the selectable-as-parent guard."""
        monkeypatch.setattr(f'{RULES}.selectable_as_parent_change_blocker', lambda *_args: 'still placed')

        assert stored_type_update_blocker(IMPORTER, stored_type(), stored_type(), False) == 'still placed'

    def test_the_special_type_rules_win_over_the_location_rules(self, monkeypatch) -> None:
        """The cheap in-memory checks run first, so no object query happens for a refused marker."""
        monkeypatch.setattr(f'{RULES}.location_field_removal_blocker', unreachable)
        monkeypatch.setattr(f'{RULES}.selectable_as_parent_change_blocker', unreachable)

        assert stored_type_update_blocker(
            IMPORTER, stored_type(SpecialType.SUBNET.value), stored_type(SpecialType.VLAN.value), False,
        ) is not None


class TestFieldLabelRule:
    """Every field must carry a label - it is what the user sees on every form and table."""

    def test_labelled_fields_pass(self) -> None:
        """A field with a label is sound."""
        entry = type_structure([type_field('host')], [{'type': 'section', 'name': 'main', 'fields': ['host']}])

        assert validate_type_structure(entry) is None

    @pytest.mark.parametrize('label', ['', '   ', None, 42], ids=['empty', 'blank', 'none', 'number'])
    def test_unlabelled_field_is_reported_by_name(self, label: Any) -> None:
        """The offending field is named, since a field without a label still has an identifier."""
        entry = type_structure(
            [{'type': 'text', 'name': 'host', 'label': label}],
            [{'type': 'section', 'name': 'main', 'fields': ['host']}],
        )

        assert TypeImportError.MISSING_FIELD_LABELS.format(names=['host']) in validate_type_structure(entry)

    def test_a_missing_label_key_is_reported(self) -> None:
        """A field bringing no label key at all is as unusable as a blank one."""
        entry = type_structure(
            [{'type': 'text', 'name': 'host'}],
            [{'type': 'section', 'name': 'main', 'fields': ['host']}],
        )

        assert TypeImportError.MISSING_FIELD_LABELS.format(names=['host']) in validate_type_structure(entry)


class TestSectionLabelRule:
    """Every section must carry a label - it is the heading the section renders under."""

    def test_labelled_sections_pass(self) -> None:
        """A section with a label is sound."""
        entry = type_structure(
            [type_field('host')],
            [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': ['host']}],
        )

        assert validate_type_structure(entry) is None

    def test_unlabelled_section_is_reported_by_name(self) -> None:
        """The offending section is named."""
        entry = {
            'fields': [type_field('host')],
            'render_meta': {'sections': [{'type': 'section', 'name': 'main', 'fields': ['host']}]},
        }

        assert TypeImportError.MISSING_SECTION_LABELS.format(names=['main']) in validate_type_structure(entry)


class TestChoiceFieldOptionsRule:
    """A select / radio field is defined by its options - without one it can never hold a value."""

    @staticmethod
    def _choice_entry(field_type: str, options: Any) -> dict[str, Any]:
        """An uploaded type whose only field is a choice field with the given options."""
        field = {'type': field_type, 'name': 'choice', 'label': 'Choice'}

        if options is not None:
            field['options'] = options

        return type_structure([field], [{'type': 'section', 'name': 'main', 'fields': ['choice']}])

    @pytest.mark.parametrize('field_type', ['select', 'radio'])
    def test_usable_options_pass(self, field_type: str) -> None:
        """One well-formed option is enough."""
        entry = self._choice_entry(field_type, [{'name': 'a', 'label': 'A'}])

        assert validate_type_structure(entry) is None

    @pytest.mark.parametrize('field_type', ['select', 'radio'])
    @pytest.mark.parametrize(
        'options',
        [None, [], 'nonsense', [{'name': 'a'}], [{'label': 'A'}], [{'name': '', 'label': ''}], ['a']],
        ids=['absent', 'empty', 'not-a-list', 'no-label', 'no-name', 'blank', 'not-a-dict'],
    )
    def test_unusable_options_are_reported(self, field_type: str, options: Any) -> None:
        """Anything a user could not pick from is refused."""
        entry = self._choice_entry(field_type, options)

        assert validate_type_structure(entry) == \
            TypeImportError.MISSING_FIELD_OPTIONS.format(names=['choice'])

    def test_one_usable_option_among_broken_ones_passes(self) -> None:
        """The rule asks for a usable option, not for every option to be usable."""
        entry = self._choice_entry('select', [{'name': 'a'}, {'name': 'b', 'label': 'B'}])

        assert validate_type_structure(entry) is None

    def test_other_field_types_need_no_options(self) -> None:
        """Only select and radio are choice fields."""
        entry = type_structure([type_field('host')], [{'type': 'section', 'name': 'main', 'fields': ['host']}])

        assert validate_type_structure(entry) is None


class TestLocationFieldRule:
    """A Type has at most one location field, and it carries the reserved name."""

    @staticmethod
    def _entry(fields: list[dict[str, Any]]) -> dict[str, Any]:
        """An uploaded type whose single section holds the given fields."""
        return type_structure(
            fields,
            [{'type': 'section', 'name': 'main', 'fields': [field['name'] for field in fields]}],
        )

    def test_the_one_correctly_named_location_field_passes(self) -> None:
        """The reserved name on a location-typed field is exactly right."""
        entry = self._entry([type_field('host'), type_field(DG_LOCATION_FIELD_NAME, 'location')])

        assert validate_type_structure(entry) is None

    def test_a_type_without_a_location_field_passes(self) -> None:
        """The location field is optional."""
        assert validate_type_structure(self._entry([type_field('host')])) is None

    def test_two_location_fields_are_reported(self) -> None:
        """Only the first would ever be read, so the second is refused."""
        entry = self._entry([
            type_field(DG_LOCATION_FIELD_NAME, 'location'), type_field('where', 'location'),
        ])
        message = validate_type_structure(entry)

        assert TypeImportError.MULTIPLE_LOCATION_FIELDS.format(
            names=sorted([DG_LOCATION_FIELD_NAME, 'where'])) in message

    def test_a_differently_named_location_field_is_reported(self) -> None:
        """The value is resolved by the reserved name, so another name would never be read."""
        entry = self._entry([type_field('where', 'location')])

        assert TypeImportError.RESERVED_LOCATION_FIELD_NAME.format(
            reserved=DG_LOCATION_FIELD_NAME, names=['where']) in validate_type_structure(entry)

    def test_a_non_location_field_may_not_squat_on_the_reserved_name(self) -> None:
        """A text field called dg_location would be mistaken for the location field."""
        entry = self._entry([type_field(DG_LOCATION_FIELD_NAME)])

        assert TypeImportError.RESERVED_LOCATION_FIELD_NAME.format(
            reserved=DG_LOCATION_FIELD_NAME, names=[DG_LOCATION_FIELD_NAME]) in validate_type_structure(entry)


class TestAsPublicId:
    """An uploaded public_id may be a string; the comparisons have to coerce it."""

    @pytest.mark.parametrize(
        'value, expected',
        [(4712, 4712), ('4712', 4712), (' 4712 ', 4712), (4712.0, 4712)],
        ids=['int', 'string', 'padded', 'float'],
    )
    def test_a_readable_id_is_coerced(self, value: Any, expected: int) -> None:
        """Whatever it was serialized as, it comes back as the number."""
        assert as_public_id(value) == expected

    @pytest.mark.parametrize(
        'value', [None, '', 'abc', True, False, [], {}],
        ids=['none', 'empty', 'text', 'true', 'false', 'list', 'dict'],
    )
    def test_anything_else_is_not_an_id(self, value: Any) -> None:
        """Including booleans - `True` is an int in Python but never a public_id."""
        assert as_public_id(value) is None


class TestNameConflictCoercesThePublicId:
    """A string public_id must not make a Type collide with its own name."""

    def test_a_string_id_still_excludes_the_type_itself(self) -> None:
        """Without coercing, 4712 == '4712' is False and the Type reports its own name as taken."""
        types_manager = StubTypesManager(existing_named_type={'public_id': EXISTING_PUBLIC_ID})
        entry = {'name': 'stored-type', 'public_id': str(EXISTING_PUBLIC_ID)}

        assert type_name_conflict_error(entry, types_manager, entry['public_id']) is None

    def test_another_types_name_is_still_a_conflict(self) -> None:
        """Coercion must not swallow a real collision."""
        types_manager = StubTypesManager(existing_named_type={'public_id': 999})
        entry = {'name': 'stored-type', 'public_id': str(EXISTING_PUBLIC_ID)}

        assert type_name_conflict_error(entry, types_manager, entry['public_id']) \
            == TypeImportError.TYPE_NAME_EXISTS.format(name='stored-type')

    def test_a_create_still_conflicts_with_any_stored_name(self) -> None:
        """No id is excluded on the create path."""
        types_manager = StubTypesManager(existing_named_type={'public_id': EXISTING_PUBLIC_ID})

        assert type_name_conflict_error({'name': 'stored-type'}, types_manager) \
            == TypeImportError.TYPE_NAME_EXISTS.format(name='stored-type')
