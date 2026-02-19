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
import { AfterViewInit, Component, Input, OnDestroy, ViewChild } from '@angular/core';
import { Router } from '@angular/router';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { DocapiService } from '../../services/docapi.service';
import { ToastService } from '../../../../layout/toast/toast.service';

import { CmdbMode } from '../../../../framework/modes.enum';
import { DocapiBuilderSettingsStepComponent } from '../docapi-builder-settings-step/docapi-builder-settings-step.component';
import { DocapiBuilderTypeStepComponent } from '../docapi-builder-type-step/docapi-builder-type-step.component';
import { DocapiBuilderStyleStepComponent } from '../docapi-builder-style-step/docapi-builder-style-step.component';
import { DocapiBuilderContentStepComponent } from '../docapi-builder-content-step/docapi-builder-content-step.component';
import { DocTemplate } from '../../models/cmdb-doctemplate';
import { Subscription } from 'rxjs';
import { CoreWarningModalComponent } from 'src/app/core/components/dialog/core-warning-modal/core-warning-modal.component';
/* ------------------------------------------------------------------------------------------------------------------ */
@Component({
    selector: 'cmdb-docapi-builder',
    templateUrl: './docapi-builder.component.html',
    styleUrls: ['./docapi-builder.component.scss'],
    standalone: false
})
export class DocapiBuilderComponent implements AfterViewInit, OnDestroy {

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

    private typeParamSubscription?: Subscription;
    private suppressTypeChange = false;
    private warningModalOpen = false;
    private previousTypeState: { templateType: string; parameters: any } | null = null;

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    constructor(
        private docapiService: DocapiService,
        private router: Router,
        private toast: ToastService,
        private modalService: NgbModal
    ) {

    }

    public ngAfterViewInit(): void {
        // this.registerTypeChangeHandlers();
    }

    public ngOnDestroy(): void {
        this.typeParamSubscription?.unsubscribe();
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

    private registerTypeChangeHandlers(): void {
        if (!this.typeStep?.typeForm) {
            return;
        }

        this.previousTypeState = this.getCurrentTypeState();

        this.typeStep.typeForm.valueChanges.subscribe(() => {
            this.handleTypeChange();
            this.registerTypeParamWatcher();
        });

        this.registerTypeParamWatcher();
    }

    public onTypeParamReady(): void {
        this.registerTypeParamWatcher();
    }

    private registerTypeParamWatcher(): void {
        this.typeParamSubscription?.unsubscribe();
        const paramForm = this.typeStep?.typeParamComponent?.typeParamForm;
        if (!paramForm) {
            return;
        }

        this.typeParamSubscription = paramForm.valueChanges.subscribe(() => {
            this.handleTypeChange();
        });
    }

    private handleTypeChange(): void {
        if (this.suppressTypeChange) {
            return;
        }

        const currentState = this.getCurrentTypeState();
        if (!this.previousTypeState || this.isSameTypeState(currentState, this.previousTypeState)) {
            this.previousTypeState = currentState;
            return;
        }

        const contentControl = this.contentStep?.contentForm?.get('template_data');
        const contentValue = contentControl?.value ?? this.docInstance?.template_data;
        const hasContent = this.hasMeaningfulContent(contentValue);
        const hasEdits = !!contentControl?.dirty;
        if (!hasContent && !hasEdits) {
            this.previousTypeState = currentState;
            return;
        }

        this.openTypeChangeWarning(currentState);
    }

    private openTypeChangeWarning(nextState: { templateType: string; parameters: any }): void {
        if (this.warningModalOpen) {
            return;
        }

        this.warningModalOpen = true;
        const modalRef = this.modalService.open(CoreWarningModalComponent, {
            size: 'md',
            backdrop: 'static'
        });

        modalRef.componentInstance.title = 'Confirm change';
        modalRef.componentInstance.message =
            'Changing the template or object type will clear the current document content. Do you want to continue?';
        modalRef.componentInstance.confirmLabel = 'Yes, clear content';
        modalRef.componentInstance.cancelLabel = 'Cancel';
        modalRef.componentInstance.warningTitle = 'Warning:';
        modalRef.componentInstance.warningIconClass = 'fas fa-exclamation-triangle';

        modalRef.result
            .then((result: string) => {
                if (result === 'confirmed') {
                    this.contentStep?.contentForm?.get('template_data')?.setValue('');
                    this.previousTypeState = nextState;
                } else {
                    this.revertTypeChange();
                }
            })
            .catch(() => {
                this.revertTypeChange();
            })
            .finally(() => {
                this.warningModalOpen = false;
            });
    }

    private revertTypeChange(): void {
        this.suppressTypeChange = true;
        this.restorePreviousTypeState();
        this.suppressTypeChange = false;
    }

    private getCurrentTypeState(): { templateType: string; parameters: any } {
        return {
            templateType: this.typeStep?.typeForm?.get('template_type')?.value,
            parameters: this.typeStep?.typeParamComponent?.typeParamForm?.value
        };
    }

    private restorePreviousTypeState(): void {
        if (!this.previousTypeState) {
            return;
        }
        this.typeStep?.typeForm?.patchValue(
            { template_type: this.previousTypeState.templateType },
            { emitEvent: false }
        );
        this.typeStep?.typeParamComponent?.typeParamForm?.patchValue(
            this.previousTypeState.parameters,
            { emitEvent: false }
        );
    }

    private isSameTypeState(
        nextState: { templateType: string; parameters: any },
        prevState: { templateType: string; parameters: any }
    ): boolean {
        if (nextState.templateType !== prevState.templateType) {
            return false;
        }
        return JSON.stringify(nextState.parameters || {}) === JSON.stringify(prevState.parameters || {});
    }

    private hasMeaningfulContent(value: any): boolean {
        if (value === null || value === undefined) {
            return false;
        }
        const raw = value.toString();
        if (!raw.trim()) {
            return false;
        }
        const stripped = raw
            .replace(/<[^>]*>/g, '')
            .replace(/&nbsp;/gi, ' ')
            .replace(/\s+/g, ' ')
            .trim();
        return stripped.length > 0;
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
                // console.error(error);
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
                // console.error(error);
            }
        });
    }
}
