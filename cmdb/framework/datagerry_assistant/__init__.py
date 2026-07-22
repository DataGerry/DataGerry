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
This package contains all classes and data for the DataGerry assistant

The assistant seeds an empty database with a starter set of CmdbTypes and CmdbCategories based on the
profiles the user selects on first start.

Modules:
  - profile_assistant: ProfileAssistant, the orchestrator that turns the selected profile names into
      CmdbTypes and CmdbCategories
  - profile_base: ProfileBase, the shared managers, ProfileTypeConstructor and helpers every profile uses
  - profile_name: ProfileName, the valid profile tokens accepted by the assistant
  - profile_type_constructor: ProfileTypeConstructor, builds insertable CmdbType dicts from the
      section/field definitions and from SpecialType blueprints
  - predefined_template_provider: PredefinedTemplateProvider, loads the predefined section templates
      once and serves independent copies to the builder
  - profile_<feature>: one module per profile (user_management, location, ipam, client_management,
      server_management, network_infrastructure) defining that profile's types
  - datagerry_assistant_constants: key / icon / category / type-slot constants plus the category and
      IPAM SpecialType definition tables
"""
