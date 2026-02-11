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
import { Component, EventEmitter, OnDestroy, OnInit, Output } from '@angular/core';
import { UntypedFormControl, UntypedFormGroup } from '@angular/forms';

import { Subscription } from 'rxjs';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-import-config',
    templateUrl: './import-config.component.html',
    styleUrls: ['./import-config.component.scss'],
    standalone: false
})
export class ImportConfigComponent implements OnInit, OnDestroy {

    @Output() public configChange: EventEmitter<any>;
    private configChangeSubscription: Subscription;
    public configForm: UntypedFormGroup;

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */
    constructor() {
        this.configChange = new EventEmitter<any>();
        this.configChangeSubscription = new Subscription();

        this.configForm = new UntypedFormGroup({
            start_element: new UntypedFormControl(0),
            max_elements: new UntypedFormControl(0),
            overwrite_public: new UntypedFormControl(true)
        });
    }


    public ngOnInit(): void {
        // Push init values
        this.configChange.emit(this.configForm.getRawValue());
        this.configChangeSubscription = this.configForm.valueChanges.subscribe(() => {
            this.configChange.emit(this.configForm.getRawValue());
        });
    }


    public ngOnDestroy(): void {
        this.configChangeSubscription?.unsubscribe();
    }
}
