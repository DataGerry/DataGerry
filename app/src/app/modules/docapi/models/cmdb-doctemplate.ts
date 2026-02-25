/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2026 becon GmbH
*
* This program is free software: you can redistribute it and/or modify
* it under the terms of the GNU Affero General Public License as
* published by the Free Software Foundation, either version 3 of the
* License, or (at your option) any later version.
*
* This program is distributed in the hope that it will be useful,
* but WITHOUT ANY WARRANTY; without even the implied warranty of
* MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
* GNU Affero General Public License for more details.
* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
export class DocTemplate {
    public public_id: number;
    public name: string;
    public label: string;
    public author_id: number;
    public active: boolean;
    public description: string;
    public template_data: string;
    public template_style: string;
    public template_type: string;
    public template_parameters: object;
}

export interface DocTemplateUpdateResponse {
    body: DocTemplate;
    status: number;
    statusText: string;
    url: string;
    ok: boolean;
}
