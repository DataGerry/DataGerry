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
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { Component, OnInit } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'section-template-add',
    templateUrl: './section-template-add.component.html',
    styleUrls: ['./section-template-add.component.scss'],
    standalone: false
})
export class SectionTemplateAddComponent implements OnInit {

    public sectionTemplateID: number = 0;

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor(private activeRoute: ActivatedRoute){

    }


    ngOnInit(): void {
        //only editing has a sectionTemplateID 
        if(this.activeRoute?.snapshot?.params?.sectionTemplateID){
            this.sectionTemplateID = this.activeRoute?.snapshot?.params?.sectionTemplateID;
        }
    }
}