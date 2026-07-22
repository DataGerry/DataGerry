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
Collection of the validation schemas for the DataGerry classes

Each schema lives in a subpackage mirroring its class' package under cmdb.models
(e.g. cmdb.class_schema.ci_explorer_model holds the schemas of cmdb.models.ci_explorer_model).
A schema is exposed via a get_<class>_schema() function and consumed by the model class as its SCHEMA
"""
