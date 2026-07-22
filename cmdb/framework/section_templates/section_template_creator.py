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
Builders for the predefined ("global") section templates DataGerry ships with

A predefined section template is a reusable, system-owned section (flagged is_global + predefined)
that the bootstrap seeds into every tenant database and that the start assistant attaches to the
types it creates. This module is the single source of their definitions; CollectionValidator seeds
whatever get_predefined_templates returns, so adding or removing a template here is the only change
needed for it to appear on fresh installs.
"""
from logging import Logger, getLogger
from typing import Any
from cmdb.models.type_model import FieldType, SectionType
from cmdb.models.special_type_model.schemas.cidr_regex import IP_ADDRESS_REGEX
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                            SectionTemplateCreator - CLASS                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class SectionTemplateCreator:
    """
    Factory for the predefined section templates DataGerry ships with

    Exposes a single entry point, get_predefined_templates, which returns freshly built dict
    representations of every predefined template (Rack mounting, Model specifications and the IPAM
    interface MDS section). The private helpers assemble the shared section/field skeletons so each
    template definition only declares what is specific to it. The creator is stateless: every call
    returns new dicts and performs no database access.
    """

    def get_predefined_templates(self) -> list[dict[str, Any]]:
        """
        Retrieves all predefined section templates

        Returns:
            list[dict[str, Any]]: Dict representations of every predefined section template, ready
                                  to be inserted into the section-template collection
        """
        predefined_templates: list[dict[str, Any]] = []

        predefined_templates.append(self.__get_rack_mounting_template())
        predefined_templates.append(self.__get_model_spec_template())
        predefined_templates.append(self.__get_ipam_interface_template())

        return predefined_templates

# -------------------------------------------------- HELPER SECTION -------------------------------------------------- #

    def __get_template_section(self, name: str, label: str) -> dict[str, Any]:
        """
        Retrieves the base section template model

        Produces the shared skeleton every predefined template starts from: a global, predefined,
        plain section with an empty field list the caller then fills in.

        Args:
            name (str): name for section template
            label (str): label for section template

        Returns:
            dict[str, Any]: Base section template construct (is_global and predefined, no fields yet)
        """
        return {
            'is_global': True,
            'predefined': True,
            'name': name,
            'label': label,
            'type': "section",
            'fields': []
        }


    def __get_template_section_field(
        self,
        field_type: str,
        name: str,
        label: str,
        options: list[dict[str, Any]] | None = None,
        regex: str | None = None,
        helper_text: str | None = None
    ) -> dict[str, Any]:
        """
        Retrieves a field model for a section template

        The optional properties are only written onto the field when supplied, so an unset option
        is absent from the returned dict rather than present with a None value.

        Args:
            field_type (str): Type of the field like 'text', 'select' etc.
            name (str): Unique identifier for the field
            label (str): label of the field
            options (list[dict[str, Any]], optional): Options for a field of type 'select'.
                                                      Defaults to None.
            regex (str | None, optional): The regex which should be applied for the input.
                                          Defaults to None.
            helper_text (str | None, optional): Help text shown for the field. Defaults to None.

        Returns:
            dict[str, Any]: The configured field for the section
        """
        field_values: dict[str, str] = {
            'type': field_type,
            'name': name,
            'label': label
        }

        if options:
            field_values['options'] = options

        if regex:
            field_values['regex'] = regex

        if helper_text:
            field_values['helperText'] = helper_text

        return field_values

# --------------------------------------------------- DATA SECTION --------------------------------------------------- #

<<<<<<< HEAD
    def __get_network_template(self) -> dict[str, Any]:
        """Retrieves the 'Network' predefined section template"""
        network_section = self.__get_template_section("dg-network", "Network")

        network_fields: list[dict[str, Any]] = []

        ipv4_regex: str = ("(\\b25[0-5]|\\b2[0-4][0-9]|\\b[01]?[0-9][0-9]?)"
                           "(\\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)){3}")

        ipv4_submask_regex : str =("^(([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\\.){3}"
                                   "([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\\/(3[0-2]|[1-2]?\\d)$")

        network_fields.append(self.__get_template_section_field("text",
                                                                "dg-network-ipaddress",
                                                                "IP address",
                                                                None,
                                                                ipv4_regex))
        network_fields.append(self.__get_template_section_field("text", "dg-network-hostname", "Hostname"))
        network_fields.append(self.__get_template_section_field("text", "dg-network-dns", "DNS"))
        network_fields.append(self.__get_template_section_field("text",
                                                                "dg-network-layer3",
                                                                "Layer3-Net",
                                                                None,
                                                                ipv4_submask_regex,
                                                                "IP/Subnet mask"))

        network_section['fields'] = network_fields

        return network_section
=======
    def __get_rack_mounting_template(self) -> dict[str, Any]:
        """
        Retrieves the 'Rack mounting' predefined section template
>>>>>>> origin/version-3.2

        A plain section with two positive-integer text fields (rack units, mounting position) and a
        horizontal/vertical orientation select.

<<<<<<< HEAD
    def __get_rack_mounting_template(self) -> dict[str, Any]:
        """Retrieves the 'Rack mounting' predefined section template"""
        rack_section = self.__get_template_section("dg-rackmounting", "Rack mounting")
=======
        Returns:
            dict[str, Any]: The 'Rack mounting' section template
        """
        rack_section: dict[str, Any] = self.__get_template_section("dg-rackmounting", "Rack mounting")
>>>>>>> origin/version-3.2

        rack_fields: list[dict[str, Any]] = []

        positive_integer_regex: str = "^\\d+$"

        rack_fields.append(self.__get_template_section_field("text",
                                                             "dg-rackmounting-ru",
                                                             "Rack units",
                                                             None,
                                                             positive_integer_regex))
        rack_fields.append(self.__get_template_section_field("text",
                                                             "dg-rackmounting-position",
                                                             "Mounting position",
                                                             None,
                                                             positive_integer_regex))

        rack_field_options: list[dict[str, str]] = [
            {
                'name': 'horizontal',
                'label': 'Horizontal'
            },
            {
                'name': 'vertical',
                'label': 'Vertical'
            }
        ]

        rack_fields.append(self.__get_template_section_field("select",
                                                             "dg-rackmounting-orientation",
                                                             "Mounting orientation",
                                                             rack_field_options))

        rack_section['fields'] = rack_fields

        return rack_section


    def __get_model_spec_template(self) -> dict[str, Any]:
<<<<<<< HEAD
        """Retrieves the 'Model specifications' predefined section template"""
        model_spec_section = self.__get_template_section("dg-modelspec", "Model specifications")
=======
        """
        Retrieves the 'Model specifications' predefined section template

        A plain section with three bare text fields: manufacturer, model name and serial number.

        Returns:
            dict[str, Any]: The 'Model specifications' section template
        """
        model_spec_section: dict[str, Any] = self.__get_template_section("dg-modelspec", "Model specifications")
>>>>>>> origin/version-3.2

        model_spec_fields: list[dict[str, Any]] = []

        model_spec_fields.append(self.__get_template_section_field("text", "dg-modelspec-manufacturer", "Manufacturer"))
        model_spec_fields.append(self.__get_template_section_field("text", "dg-modelspec-model", "Model name"))
        model_spec_fields.append(self.__get_template_section_field("text", "dg-modelspec-serial", "Serial number"))

        model_spec_section['fields'] = model_spec_fields

        return model_spec_section


<<<<<<< HEAD
    def get_ipam_interface_template(self, subnet_id: int) -> dict[str, Any]:
        """TODO: document"""
        if not subnet_id:
            raise ValueError("No Subnet-ID provided to IPAM Interface SectionTemplate")

=======
    def __get_ipam_interface_template(self) -> dict[str, Any]:
        """
        Retrieves the 'Interfaces' (dg-ipam-interface) predefined section template

        Unlike the other predefined templates this is a multi-data-section, so a single object can
        hold several interface rows. Each row carries an active flag, an IPv4/IPv6 type select, a
        Subnet reference (its ref_types are wired to the created Subnet type by the assistant /
        special-type wiring, hence empty here), and IP / hostname / domain / MAC text fields.

        Returns:
            dict[str, Any]: The 'Interfaces' MDS section template
        """
>>>>>>> origin/version-3.2
        interface: dict[str, Any] = {
            "is_global": True,
            "predefined": True,
            "name": "dg-ipam-interface",
            "label": "Interfaces",
<<<<<<< HEAD
            "type": "multi-data-section",
            "fields": [
                {
                    "type": "checkbox",
=======
            "type": SectionType.MDS_SECTION,
            "fields": [
                {
                    "type": FieldType.CHECKBOX,
>>>>>>> origin/version-3.2
                    "name": "dg-interface-active",
                    "label": "Active",
                    "options": [
                        {
                            "name": "option-1",
                            "label": "Option 1",
                        }
                    ],
                    "value": True
                },
                {
<<<<<<< HEAD
                    "type": "select",
                    "name": "dg-interface-type",
                    "label": "Type",
=======
                    "type": FieldType.SELECT,
                    "name": "dg-interface-type",
                    "label": "Type",
                    "required": True,
                    "value": "ipv4",
>>>>>>> origin/version-3.2
                    "options": [
                        {
                            "name": "ipv4",
                            "label": "IPv4",
                        },
                        {
                            "name": "ipv6",
                            "label": "IPv6",
                        }
                    ],
                },
                {
<<<<<<< HEAD
                    "type": "ref",
                    "name": "dg-interface-subnet",
                    "label": "Network",
                    "ref_types": [subnet_id]
                },
                {
                    "type": "text",
                    "name": "dg-interface-ip-address",
                    "label": "IP-Address",
                },
                {
                    "type": "text",
=======
                    'type': FieldType.REFERENCE,
                    'name': "dg-interface-subnet",
                    'label': "Network",
                    'description': "Reference to Subnet SpecialType",
                    'ref_types': []
                },
                {
                    "type": FieldType.TEXT,
                    "name": "dg-interface-ip-address",
                    "label": "IP-Address",
                    "regex": IP_ADDRESS_REGEX,
                },
                {
                    "type": FieldType.TEXT,
>>>>>>> origin/version-3.2
                    "name": "dg-interface-host",
                    "label": "Hostname",
                },
                {
<<<<<<< HEAD
                    "type": "text",
=======
                    "type": FieldType.TEXT,
>>>>>>> origin/version-3.2
                    "name": "dg-interface-domain",
                    "label": "Domain",
                },
                {
<<<<<<< HEAD
                    "type": "text",
=======
                    "type": FieldType.TEXT,
>>>>>>> origin/version-3.2
                    "name": "dg-interface-mac-address",
                    "label": "Mac-Address",
                    "regex": r'^(([0-9A-Fa-f]{2}([:-])){5}[0-9A-Fa-f]{2})$|^(([0-9A-Fa-f]{4}\.){2}[0-9A-Fa-f]{4})$',
                }
            ]
        }

        return interface
