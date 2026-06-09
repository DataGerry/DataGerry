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
REST API routes for the CmdbSectionTemplate domain

Gathers everything backing the ``/rest/section_templates`` endpoints in one place, mirroring
the ``cmdb_objects`` and ``cmdb_types`` route packages:

    section_template_routes.py   ``section_template_blueprint`` - the CmdbSectionTemplate CRUD endpoints
    section_template_helper.py   request-payload validation / coercion helpers used by those routes

The shared domain constants (``SectionTemplateKey`` / ``SectionTemplateRight``) live with the
model in ``cmdb.models.section_template_model.section_template_constants`` - they are consumed by
the manager too, so they are not duplicated into a route-level constants module here.
"""
