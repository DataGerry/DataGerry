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
import { Component, Input, ViewChild } from '@angular/core';
import { Router } from '@angular/router';

import { DocapiService } from '../../services/docapi.service';
import { ToastService } from '../../../../layout/toast/toast.service';

import { CmdbMode } from '../../../../framework/modes.enum';
import { DocapiBuilderSettingsStepComponent } from '../docapi-builder-settings-step/docapi-builder-settings-step.component';
import { DocapiBuilderTypeStepComponent } from '../docapi-builder-type-step/docapi-builder-type-step.component';
import { DocapiBuilderStyleStepComponent } from '../docapi-builder-style-step/docapi-builder-style-step.component';
import { DocapiBuilderContentStepComponent } from '../docapi-builder-content-step/docapi-builder-content-step.component';
import { DocTemplate } from '../../models/cmdb-doctemplate';
/* ------------------------------------------------------------------------------------------------------------------ */
@Component({
    selector: 'cmdb-docapi-builder',
    templateUrl: './docapi-builder.component.html',
    styleUrls: ['./docapi-builder.component.scss'],
    standalone: false
})
export class DocapiBuilderComponent {

    @Input() public mode: number = CmdbMode.Create;
    @Input() public docInstance?: DocTemplate;

    @ViewChild(DocapiBuilderSettingsStepComponent, { static: true })
    public settingsStep: DocapiBuilderSettingsStepComponent;

    @ViewChild(DocapiBuilderTypeStepComponent, { static: true })
    public typeStep: DocapiBuilderTypeStepComponent;
    public typeStepFormValid: boolean = false;
    public typeParam: any = undefined;

    @ViewChild(DocapiBuilderContentStepComponent, { static: true })
    public contentStep: DocapiBuilderContentStepComponent;

    @ViewChild(DocapiBuilderStyleStepComponent, { static: true })
    public styleStep: DocapiBuilderStyleStepComponent;

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    constructor(
        private docapiService: DocapiService,
        private router: Router,
        private toast: ToastService
    ) {

    }

/* ------------------------------------------------ HELPER FUNCTIONS ------------------------------------------------ */

    /**
     * Saves the document based on the current mode (Create or Edit).
     * Initializes the document instance if in Create mode.
     * Updates the document instance with form values.
     * Handles the API call for creating or editing the document.
     */
    public saveDoc(): void {
        if (!this.docInstance && this.mode === CmdbMode.Create) {
            this.docInstance = new DocTemplate();
        }

        this.updateDocInstance();

        if (this.mode === CmdbMode.Create) {
            this.handleCreateMode();
        } else if (this.mode === CmdbMode.Edit) {
            this.handleEditMode();
        }
    }


    /**
     * Updates the document instance properties with values from the form.
     */
    private updateDocInstance(): void {
        const { settingsForm } = this.settingsStep;
        const { typeForm, typeParamComponent } = this.typeStep;
        const { contentForm } = this.contentStep;
        const { styleForm } = this.styleStep;
    
        this.docInstance.name = settingsForm?.get('name')?.value;
        this.docInstance.label = settingsForm?.get('label')?.value;
        this.docInstance.active = settingsForm?.get('active')?.value;
        this.docInstance.description = settingsForm?.get('description')?.value;
        this.docInstance.template_type = typeForm?.get('template_type')?.value;
        this.docInstance.template_parameters = typeParamComponent?.typeParamForm?.value;
        this.docInstance.template_data = contentForm?.get('template_data')?.value;
        this.docInstance.template_style = styleForm?.get('template_style')?.value;
    }


    /**
     * Handles the creation of a new document by making an API call.
     * On success, navigates to the document list with a success query parameter.
     */
    private handleCreateMode(): void {
        this.docapiService.postDocTemplate(this.docInstance).subscribe({
            next: (publicIdResp: string) => {
                this.toast.success("DocAPI document successfully created!");
                this.router.navigate(['/docapi/'], { queryParams: { docAddSuccess: publicIdResp } });
            },
            error: (error: any) => {
                console.error(error);
            }
        });
    }


    /**
     * Handles the editing of an existing document by making an API call.
     * On success, shows a success toast and navigates to the document list with a success query parameter.
     */
    private handleEditMode(): void {
        this.docapiService.putDocTemplate(this.docInstance).subscribe({
            next: (updateResp: DocTemplate) => {
                this.toast.success(`DocAPI document successfully edited: ${updateResp.public_id}`);
                this.router.navigate(['/docapi/'], { queryParams: { docEditSuccess: updateResp.public_id } });
            },
            error: (error: any) => {
                console.error(error);
            }
        });
    }
}
