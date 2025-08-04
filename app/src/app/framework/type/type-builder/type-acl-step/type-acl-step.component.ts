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
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { Component, EventEmitter, Input, OnDestroy, OnInit, Output } from '@angular/core';
import { UntypedFormControl, UntypedFormGroup } from '@angular/forms';

import { ReplaySubject, takeUntil } from 'rxjs';

import { Group } from '../../../../management/models/group';
import { AccessControlList } from 'src/app/modules/acl/acl.types';
import { TypeBuilderStepComponent } from '../type-builder-step.component';
import { CmdbType } from '../../../models/cmdb-type';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-type-acl-step',
    templateUrl: './type-acl-step.component.html',
    styleUrls: ['./type-acl-step.component.scss']
})
export class TypeAclStepComponent extends TypeBuilderStepComponent implements OnInit, OnDestroy {

    private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

    private wasEmpty: boolean = true;
    public form: UntypedFormGroup;

    @Output() public isEmpty: EventEmitter<boolean> = new EventEmitter<boolean>();

    @Input() public groups: Array<Group> = [];

/* -------------------------------------------------- GETTER/SETTER ------------------------------------------------- */

    @Input('typeInstance')
    public set TypeInstance(instance: CmdbType) {
        this.typeInstance = instance;

        if (this.typeInstance.acl) {
            this.form.patchValue(this.typeInstance.acl);
        }

    }


    public get activatedStatus(): boolean {
        return this.form.get('activated').value;
    }


    public get groupsControl(): UntypedFormGroup {
        return this.form.get('groups') as UntypedFormGroup;
    }

    public get includesControl(): UntypedFormGroup {
        return this.groupsControl.get('includes') as UntypedFormGroup;
    }

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor() {
        super();

        this.form = new UntypedFormGroup({
            activated: new UntypedFormControl(false),
            groups: new UntypedFormGroup({
                includes: new UntypedFormGroup({})
            })
        });
    }


    public ngOnInit(): void {
        this.form.statusChanges.pipe(takeUntil(this.subscriber)).subscribe(() => {
            if (!this.form.get('activated').value) {
                this.isEmpty.emit(true);
                this.validateChange.emit(true);
            } else {
                this.isEmpty.emit(this.wasEmpty);
                this.validateChange.emit(this.form.valid);
            }
        });

        this.form.valueChanges.pipe(takeUntil(this.subscriber)).subscribe(() => {
            this.typeInstance.acl = this.form.getRawValue() as AccessControlList;
        });
    }


    public ngOnDestroy(): void {
        this.subscriber?.next();
        this.subscriber?.complete();
    }

/* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */

    public onAddChange(event) {
        this.wasEmpty = (!event[0] || event[0].length === 0) && !event[1];
        this.isEmpty.emit(this.wasEmpty);
    }
}