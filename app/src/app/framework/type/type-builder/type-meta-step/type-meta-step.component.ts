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
import {
    ChangeDetectionStrategy,
    Component,
    DoCheck,
    Input,
    IterableDiffer,
    IterableDiffers,
    OnDestroy,
    OnInit
} from '@angular/core';
import { AbstractControl, UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';

import { ReplaySubject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';

import { TypeBuilderStepComponent } from '../type-builder-step.component';
import { CmdbType } from '../../../models/cmdb-type';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-type-meta-step',
    templateUrl: './type-meta-step.component.html',
    styleUrls: ['./type-meta-step.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class TypeMetaStepComponent extends TypeBuilderStepComponent implements DoCheck, OnInit, OnDestroy {

    private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

    public summaryForm: UntypedFormGroup;
    public get ciExplorerLabel(): UntypedFormControl {
        return this.summaryForm.get('ci_explorer_label') as UntypedFormControl;
    }
    public externalsForm: UntypedFormGroup;

    public hasInter: boolean = false;

    public fields: Array<any> = [];
    public summaries: Array<any> = [];
    private iterableDiffer: IterableDiffer<any>;
    public filteredFields: Array<any> = [];

    @Input('typeInstance')
    public set TypeInstance(instance: CmdbType) {
        if (instance) {
            this.typeInstance = instance;
            this.summaries = [...this.typeInstance.fields];
            this.fields = [{ label: 'Object ID', name: 'object_id' }, ...this.typeInstance.fields];
            this.summaryForm.patchValue({
                fields: instance.render_meta.summary?.fields ?? [],
                ci_explorer_label: instance.ci_explorer_label ?? ''
            });
            this.externalsForm.get('name').setValidators(this.listNameValidator());
        }
    }

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor(private iterableDiffers: IterableDiffers) {
        super();
        this.iterableDiffer = iterableDiffers.find([]).create(null);

        this.summaryForm = new UntypedFormGroup({
            fields: new UntypedFormControl('', Validators.required),
            ci_explorer_label: new UntypedFormControl('', Validators.required)
        });

        this.externalsForm = new UntypedFormGroup({
            name: new UntypedFormControl('', [Validators.required]),
            label: new UntypedFormControl('', Validators.required),
            icon: new UntypedFormControl(''),
            href: new UntypedFormControl('', [Validators.required]),
            fields: new UntypedFormControl('')
        });
    }


    public ngOnInit(): void {
        this.externalsForm.get('name').valueChanges.pipe(takeUntil(this.subscriber)).subscribe(val => {
            if (this.externalsForm.get('name').value !== null) {
                this.externalsForm.get('label').setValue(val.charAt(0).toUpperCase() + val.toString().slice(1));
                this.externalsForm.get('label').markAsDirty({ onlySelf: true });
                this.externalsForm.get('label').markAsTouched({ onlySelf: true });
            }
        });

        this.externalsForm.get('href').valueChanges.pipe(takeUntil(this.subscriber)).subscribe((href: string) => {
            this.hasInter = this.occurrences(href, '{}') > 0;
        });
    }


    public ngOnDestroy(): void {
        this.subscriber?.next();
        this.subscriber?.complete();
    }

    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public get external_name() {
        return this.externalsForm.get('name');
    }


    public get external_label() {
        return this.externalsForm.get('label');
    }


    public get summaryFields(): UntypedFormControl {
        return this.summaryForm.get('fields') as UntypedFormControl;
    }


    public listNameValidator() {
        return (control: AbstractControl): { [key: string]: any } | null => {
            const nameInList = this.typeInstance.render_meta.externals.find(el => el.name === control.value);
            return nameInList ? { nameAlreadyTaken: { value: control.value } } : null;
        };
    }


    public addExternal() {
        this.typeInstance.render_meta.externals.push(this.externalsForm.value);
        this.externalsForm.reset();
        this.externalsForm.get('icon').setValue('fas fa-external-link-alt');
    }


    public editExternal(data) {
        const rawExternalData = this.typeInstance.render_meta.externals[this.typeInstance.render_meta.externals.indexOf(data)];
        this.externalsForm.reset();
        this.deleteExternal(data);
        this.externalsForm.patchValue(rawExternalData);
    }

    public deleteExternal(data) {
        const index: number = this.typeInstance.render_meta.externals.indexOf(data);
        if (index !== -1) {
            this.typeInstance.render_meta.externals.splice(index, 1);
        }
    }


    public ngDoCheck(): void {
        const changes = this.iterableDiffer.diff(this.typeInstance.fields);
        if (changes) {

            let filteredFieldNames = [...this.typeInstance.render_meta.sections]
                .filter(section => section.type !== "multi-data-section")
                .flatMap(mp => mp.fields);

            if (Array.isArray(filteredFieldNames) && filteredFieldNames.length > 0 && typeof filteredFieldNames[0] === 'object') {
                filteredFieldNames = filteredFieldNames.map(field => field.name);
            }

            this.filteredFields = this.typeInstance.fields.filter(field =>
                filteredFieldNames.includes(field.name)
            );

            const currentLabel = this.ciExplorerLabel.value;
            if (currentLabel && !this.filteredFields.find(f => f.name === currentLabel)) {
                this.ciExplorerLabel.patchValue(null);
                this.typeInstance.ci_explorer_label = '';
            }

            let summaries = this.summaryFields.value;
            changes.forEachRemovedItem(record => {
                summaries = summaries?.filter(f => f !== record.item.name);
            });

            this.summaries = [...this.filteredFields];
            this.fields = [{ label: 'Object ID', name: 'object_id' }, ...this.typeInstance.fields];
            this.typeInstance.render_meta.summary.fields = summaries;
            this.summaryFields.patchValue(summaries);
        }
    }


    public onSummaryChange(fields: Array<any>) {
        this.typeInstance.render_meta.summary.fields = fields.map(f => f.name);
    }


    /**
     * Updates the CI Explorer label in the type instance
     * based on the selected field. Clears it if no field is selected.
     */
    public onCiExplorerChange(field: any): void {
        this.typeInstance.ci_explorer_label = field ? field.name : null;
    }


    public occurrences(s, subString): number {
        s += '';
        subString += '';

        if (subString.length <= 0) {
            return (s.length + 1);
        }

        let n = 0;
        let pos = 0;
        while (true) {
            pos = s.indexOf(subString, pos);

            if (pos >= 0) {
                ++n;
                pos += 1;
            } else {
                break;
            }
        }

        return n;
    }
}
