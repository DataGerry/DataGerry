/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2025 becon GmbH
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
import {
    Component,
    OnInit,
    OnDestroy,
    forwardRef,
    AfterViewInit
} from '@angular/core';
import { UntypedFormControl, UntypedFormGroup } from '@angular/forms';

import { Subscription } from 'rxjs';

import { TypeMappingBaseComponent } from '../type-mapping/type-mapping-base.component';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-csv-mapping',
    templateUrl: './csv-mapping.component.html',
    styleUrls: ['./csv-mapping.component.scss'],
    providers: [{ provide: TypeMappingBaseComponent, useExisting: forwardRef(() => CsvMappingComponent) }],
    standalone: false
})
export class CsvMappingComponent extends TypeMappingBaseComponent implements OnInit, AfterViewInit, OnDestroy {
    public previewIndex: number = 0;
    public previewIndexSelectionForm: UntypedFormGroup;
    private previewSelectionSubscription: Subscription;

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */
    constructor() {
        super();

        this.previewIndexSelectionForm = new UntypedFormGroup({
            indexSelection: new UntypedFormControl(0)
        });

        this.previewSelectionSubscription = this.previewIndexSelectionForm.get('indexSelection').valueChanges
        .subscribe((change) => {
            this.previewIndex = +change;
        });
    }


    public ngOnInit(): void {
        for (let i = 0; i < this.parsedData.entry_length; i++) {
            this.currentMapping.push({});
        }
    }


    public ngAfterViewInit(): void {
        const moveList: any[] = [];

        if (this.parserConfig.header && this.parsedData) {
            for (const control of this.mappingControls) {
                if (control.type === 'ref') {
                    continue;
                }

                if (this.parsedData.header.indexOf(control.name) > -1) {
                    moveList.push({
                        index: this.parsedData.header.indexOf(control.name),
                        item: control
                    });
                }
            }

            for (const moveControl of moveList) {
                this.moveControl(moveControl.item, this.mappingControls, moveControl.index, this.currentMapping);
            }

            this.mappingChange.emit(this.currentMapping);
        }
    }


    public ngOnDestroy(): void {
        this.previewSelectionSubscription?.unsubscribe();
    }
}
