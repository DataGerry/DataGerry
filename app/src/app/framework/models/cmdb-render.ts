/*
* dataGerry - OpenSource Enterprise CMDB
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
*
* You should have received a copy of the GNU Affero General Public License
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { AccessControlList } from "src/app/modules/acl/acl.types";
import { SpecialType } from "./special-type";
/* ------------------------------------------------------------------------------------------------------------------ */

export class RenderResult {

    public current_render_time: {
        $date: string
    };

    public object_information: {
        object_id: number;
        creation_time: {
            $date: string
        },
        last_edit_time: {
            $date: string
        },
        author_id: number;
        author_name: string;
        editor_id?: number;
        editor_name?: string;
        active: boolean;
        version: string;
        special_type?: SpecialType;
    };

    public type_information: {
        type_id: number;
        type_name: string;
        type_label: string;
        creation_time: {
            $date: string
        },
        author_id: number;
        author_name: string;
        active: boolean;
        version: string;
        icon: string;
        acl: AccessControlList;
    };

    public fields: any[];
    public sections: any[];
    public summaries: any[];
    public summary_line: string;
    public externals: any[];
    public multi_data_sections: any[];
}