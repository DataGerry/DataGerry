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
import { Component, Input, OnInit } from '@angular/core';
import { UntypedFormGroup } from '@angular/forms';

import { CmdbType } from '../models/cmdb-type';
import { CmdbMode } from '../modes.enum';
import { CmdbObject } from '../models/cmdb-object';
import { RenderResult } from '../models/cmdb-render';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-render',
    templateUrl: './render.component.html',
    styleUrls: ['./render.component.scss'],
    standalone: false
})
export class RenderComponent implements OnInit {
    private typeInstanceBack: CmdbType;
    private objectInstanceBack: CmdbObject;
    private renderResultBack: RenderResult = undefined;

    @Input() public renderForm: UntypedFormGroup;
    @Input() public changeForm: UntypedFormGroup;
    @Input() public mode: CmdbMode;

    public objectID: number;
    private field: any;

/* -------------------------------------------------- GETTER/SETTER ------------------------------------------------- */

    @Input('typeInstance')
    public set typeInstance(type: CmdbType) {
        if (type !== undefined) {
            this.typeInstanceBack = type;
        }
    }


    @Input('renderResult')
    public set renderResult(data: RenderResult) {
        this.renderResultBack = data;
    }


    @Input('objectInstance')
    public set objectInstance(data: CmdbObject) {
        if (data !== undefined) {
            this.objectInstanceBack = data;
        }
    }


    @Input('currentField')
    public get currentField() {
        return this.field;
    }


    public set currentField(value) {
        this.field = value;
    }


    public get typeInstance(): CmdbType {
        return this.typeInstanceBack;
    }


    public get objectInstance(): CmdbObject {
        return this.objectInstanceBack;
    }


    public get renderResult(): RenderResult {
        return this.renderResultBack;
    }


    public get fields() {
        return this.renderForm.get('fields');
    }

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    public constructor() {
        if (this.mode === CmdbMode.View) {
            this.renderForm.disable();
        }
    }


    public ngOnInit(): void {
        if(this.renderResult){
            this.objectID = this.renderResult.object_information.object_id;
        }
    }

/* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */

    public getFieldByName(name: string) {
        if (this.renderResult !== undefined) {
            return this.renderResult?.fields?.find(field => field?.name === name);
        } else {
            const field: any = this.typeInstance?.fields?.find(f => f?.name === name);

            switch (field.type) {
                case 'ref': {
                    field.default = parseInt(field?.default, 10);
                    break;
                }
                default: {
                    field.default = field?.value;
                    break;
                }
            }

            return field;
        }
    }


    public getValueByName(name: string) {
        if (this.renderResult !== undefined) {
            const fieldFound = this.renderResult.fields.find(field => field.name === name);

            if (fieldFound === undefined) {
                return {};
            }

            return fieldFound.value;

        } else if (this.objectInstance !== undefined) {
            const fieldFound = this.objectInstance.fields.find(field => field.name === name);

            if (fieldFound === undefined) {
                return {};
            }

            return fieldFound.value;
        }
    }
}
