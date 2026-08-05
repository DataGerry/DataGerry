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
*
* You should have received a copy of the GNU Affero General Public License
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { v4 as uuidv4 } from 'uuid';

import { Component } from '@angular/core';
import { ActivatedRoute } from '@angular/router';

import { TypeService } from '../../services/type.service';
import { UserService } from '../../../management/services/user.service';

import { CmdbType } from '../../models/cmdb-type';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-type-add',
    templateUrl: './type-add.component.html',
    styleUrls: ['./type-add.component.scss'],
    standalone: false
})
export class TypeAddComponent {
  public typeInstance: CmdbType;

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor(private route: ActivatedRoute, private typeService: TypeService, private userService: UserService) {
        this.typeInstance = new CmdbType();
        this.route.queryParams.subscribe((query) => {
            if (query.copy !== undefined) {
                this.typeService.getType(query.copy).subscribe((copyType: CmdbType) => {
                    // @ts-ignore
                    delete copyType.public_id;
                    // @ts-ignore
                    delete copyType._id;
                    delete copyType.author_id;
                    this.typeInstance = copyType;
                    this.typeInstance = this.setNewIDs(this.typeInstance);
                    this.typeInstance.author_id = this.userService.getCurrentUser().public_id;
                });
            }
        });
    }

/* ------------------------------------------------ HELPER FUNCTIONS ------------------------------------------------ */

    /**
     * When a type is copied then new IDs need to be set for all sections with their fields which are not either
     * a global section template or a predefined section template (or a dg_location)
     * 
     * @param type(CmdbType) CmdbType which needs a net set of IDs
     * @returns (CmdbType) CmdbType with new IDs
     */
    private setNewIDs(type: CmdbType): CmdbType {
        for (let sectionIndex in type.render_meta.sections){
            let aSection = type.render_meta.sections[sectionIndex];

            //check each section if it is a global or predefined
            if(!this.isGlobalSection(aSection.name)){
                //first give the section a new id
                type.render_meta.sections[sectionIndex].name = this.generateNewID(aSection.name);
                
                
                for (let fieldNameIndex in aSection.fields){
                    // get the field name from the section
                    let aFieldName = aSection.fields[fieldNameIndex];

                    for (let aFieldIndex in type.fields) {
                        //get the field from the type
                        let aField = type.fields[aFieldIndex];

                        //set the new id for the type and the section
                        if (aField.name == aFieldName) {
                            const newFieldID = this.generateNewID(aField.type);
                            aField.name = newFieldID;
                            aSection.fields[fieldNameIndex] = newFieldID;
                        }
                    }
                }
            }
        }

        return type;
    }


    /**
     * Checks if the section is a global or predefined one
     * @param name name of the section
     * @returns True if gobal or predefined section
     */
    private isGlobalSection(name: string): boolean {
        return name.startsWith('dg-') || name.startsWith('dg_gst');
    }


    /**
     * Generates a new id for a field or a section
     * 
     * @param fieldType Type of the field or section
     */
    private generateNewID(typeName: string){
        if(typeName.startsWith('section_template-')){
            typeName = 'section_template';
        }

        if(typeName.startsWith('section-')){
            typeName = 'section';
        }

        //'dg_location' is only once possible per type and has always the same ID
        if(typeName == 'location'){
            return 'dg_location';
        }

        return `${typeName}-${uuidv4()}`
    }
}
