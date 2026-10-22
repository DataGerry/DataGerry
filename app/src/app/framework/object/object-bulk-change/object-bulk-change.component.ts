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
import { Component, OnDestroy, ViewChild } from '@angular/core';
import { UntypedFormGroup } from '@angular/forms';
import { Router } from '@angular/router';

import { finalize, ReplaySubject, takeUntil } from 'rxjs';

import { ObjectService } from '../../services/object.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from '../../../layout/toast/toast.service';

import { WizardComponent } from '@rg-software/angular-archwizard';

import { RenderResult } from '../../models/cmdb-render';
import { CmdbType } from '../../models/cmdb-type';
import { ObjectBulkPatchPayload } from '../../models/cmdb-object';
import { APIUpdateMultiResponse } from '../../../services/models/api-response';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-object-bulk-change',
    templateUrl: './object-bulk-change.component.html',
    styleUrls: ['./object-bulk-change.component.scss'],
    standalone: false
})
export class ObjectBulkChangeComponent implements OnDestroy {

    // The aw-wizard component defines the root component of a wizard.
    @ViewChild('wizard', { static: false }) public wizard: WizardComponent;

    private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

    // Type of objects to bulk change.
    public type: CmdbType;

    // Form for bulk change editor.
    public changeForm: UntypedFormGroup = new UntypedFormGroup({});
    public renderForm: UntypedFormGroup = new UntypedFormGroup({});

    public activeState: boolean | undefined = undefined;

    // List of to change selected items.
    public renderResults: Array<RenderResult> = [];

    public apiResponse: APIUpdateMultiResponse;

    public isLoading$ = this.loaderService.isLoading$;

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor(
        private objectService: ObjectService,
        private loaderService: LoaderService,
        private toastService: ToastService,
        private router: Router
    ) {
        if (this.router.getCurrentNavigation().extras.state) {
            this.type = this.router.getCurrentNavigation().extras.state.type;
            this.renderResults = this.router.getCurrentNavigation().extras.state.objects;
        }
    }


    public ngOnDestroy(): void {
        this.subscriber?.next();
        this.subscriber?.complete();
    }

/* ------------------------------------------------ HELPER FUNCTIONS ------------------------------------------------ */

    // Was the form touched
    public get hasChanges(): boolean {
        return this.renderForm.dirty;
    }


    // Apply the ticked field changes to all selected objects.
    public saveObject() {
        const changes = this.changeForm.getRawValue();
        const objectIDs = this.renderResults.map(result => result.object_information.object_id);

        const payload: ObjectBulkPatchPayload = {
            fields: Object.keys(changes).map((key: string) => ({ name: key, value: changes[key] }))
        };

        if (this.activeState !== undefined) {
            payload.active = this.activeState;
        }

        this.loaderService.show();
        this.objectService.patchObjects(objectIDs, payload)
            .pipe(
                finalize(() => this.loaderService.hide()),
                takeUntil(this.subscriber)
            )
            .subscribe({
                next: (response: APIUpdateMultiResponse) => {
                    this.apiResponse = response;
                    this.goToNextStepIndex(2);
                },
                error: e => this.toastService.error(e?.error?.message)
            });
    }


    private goToNextStepIndex(index: number) {
        if (this.wizard ) {
            this.wizard.goToStep(index);
        }
    }
}