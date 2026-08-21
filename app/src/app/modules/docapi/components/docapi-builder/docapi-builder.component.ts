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
import { Component, inject, AfterViewInit, EventEmitter, Input, OnDestroy, Output, ViewChild } from '@angular/core';
import { Router } from '@angular/router';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { WizardComponent } from '@rg-software/angular-archwizard';
import { FileSaverService } from 'ngx-filesaver';

import { DocapiService } from '../../services/docapi.service';
import { ToastService } from '../../../../layout/toast/toast.service';

import { CmdbMode } from '../../../../framework/modes.enum';
import { DocapiBuilderSettingsStepComponent } from '../docapi-builder-settings-step/docapi-builder-settings-step.component';
import { DocapiBuilderTypeStepComponent } from '../docapi-builder-type-step/docapi-builder-type-step.component';
import { DocapiBuilderStyleStepComponent } from '../docapi-builder-style-step/docapi-builder-style-step.component';
import { DocapiBuilderContentStepComponent } from '../docapi-builder-content-step/docapi-builder-content-step.component';
import { DocTemplate, DocTemplateUpdateResponse } from '../../models/cmdb-doctemplate';
import { finalize, firstValueFrom, startWith, Subscription } from 'rxjs';
import { CoreWarningModalComponent } from 'src/app/core/components/dialog/core-warning-modal/core-warning-modal.component';
import { DocapiPreviewObjectModalComponent } from '../docapi-preview-object-modal/docapi-preview-object-modal.component';
import { normalizeCoverPage } from '../../utils/cover-page.util';
import { normalizeFooter, normalizeHeader } from '../../utils/page-section.util';
import { normalizeTableOfContents } from '../../utils/table-of-contents.util';
import { LoaderService } from 'src/app/core/services/loader.service';

@Component({
    selector: 'cmdb-docapi-builder',
    templateUrl: './docapi-builder.component.html',
    styleUrls: ['./docapi-builder.component.scss'],
    standalone: false
})
export class DocapiBuilderComponent implements AfterViewInit, OnDestroy {
    private readonly docapiService = inject(DocapiService);
    private readonly router = inject(Router);
    private readonly toast = inject(ToastService);
    private readonly modalService = inject(NgbModal);
    private readonly fileSaverService = inject(FileSaverService);
    private readonly loaderService = inject(LoaderService);

    @Input() public mode: number = CmdbMode.Create;
    @Input() public docInstance?: DocTemplate;
    @Output() public labelChanged = new EventEmitter<string>();
    @ViewChild('wizard', { static: false })
    public wizard: WizardComponent;

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
    private labelSubscription?: Subscription;
    private suppressTypeChange = false;
    private warningModalOpen = false;
    private previousTypeState: { templateType: string; parameters: any } | null = null;
    public previewInProgress = false;
    public isSaving = false;
    public isLoading$ = this.loaderService.isLoading$;

    /** Right required to persist the template in the current wizard mode */
    public get saveRight(): string {
        return this.mode === CmdbMode.Edit ? 'base.docapi.template.edit' : 'base.docapi.template.add';
    }

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    public ngAfterViewInit(): void {
        this.registerTypeChangeHandlers();
        this.registerLabelChangeHandler();
    }

    public ngOnDestroy(): void {
        this.typeParamSubscription?.unsubscribe();
        this.labelSubscription?.unsubscribe();
    }

/* ------------------------------------------------ HELPER FUNCTIONS ------------------------------------------------ */

    /**
     * Saves the document based on the current mode (Create or Edit).
     * Initializes the document instance if in Create mode.
     * Updates the document instance with form values.
     * Handles the API call for creating or editing the document.
     */
    public saveDoc(): void {
        if (this.isSaving) {
            return;
        }

        if (!this.docInstance && this.mode === CmdbMode.Create) {
            this.docInstance = new DocTemplate();
        }

        this.updateDocInstance();

        if (this.mode === CmdbMode.Create) {
            this.isSaving = true;
            this.handleCreateMode();
        } else if (this.mode === CmdbMode.Edit) {
            this.isSaving = true;
            this.handleEditMode();
        }
    }

    public cancel(): void {
        this.router.navigate(['/docapi']);
    }

    public nextStep(): void {
        if (!this.wizard) {
            return;
        }

        const nextIndex = this.wizard.currentStepIndex + 1;
        this.wizard.goToStep(nextIndex);
    }

    public previousStep(): void {
        if (!this.wizard) {
            return;
        }

        const previousIndex = this.wizard.currentStepIndex - 1;
        if (previousIndex >= 0) {
            this.wizard.goToStep(previousIndex);
        }
    }

    public openPreviewObjectModal(): void {
        const modalRef = this.modalService.open(DocapiPreviewObjectModalComponent, {
            size: 'lg',
            backdrop: 'static',
            windowClass: 'dg-modal-window',
            backdropClass: 'dg-modal-window-backdrop'
        });

        modalRef.componentInstance.templateType = this.typeStep?.typeForm?.get('template_type')?.value ?? 'DEFAULT';
        modalRef.componentInstance.templateTypeId = this.getSelectedObjectTypePublicId();

        modalRef.result
            .then((objectId: number) => {
                if (!objectId) {
                    return;
                }
                this.confirmSaveBeforePreview(objectId);
            })
            .catch(() => {
                return;
            });
    }

    private getSelectedObjectTypePublicId(): number | null {
        const selectedTypePublicId = Number(this.typeStep?.typeParamComponent?.typeParamForm?.get('type')?.value);
        if (Number.isFinite(selectedTypePublicId) && selectedTypePublicId > 0) {
            return selectedTypePublicId;
        }

        return null;
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
        this.docInstance.cover_page = normalizeCoverPage(contentForm?.get('cover_page')?.value);
        this.docInstance.header = normalizeHeader(contentForm?.get('header')?.value);
        this.docInstance.footer = normalizeFooter(contentForm?.get('footer')?.value);
        this.docInstance.table_of_contents = normalizeTableOfContents(contentForm?.get('table_of_contents')?.value);
        this.docInstance.page_config = contentForm?.get('page_config')?.value;
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

    private registerLabelChangeHandler(): void {
        const labelControl = this.settingsStep?.settingsForm?.get('label');
        if (!labelControl) {
            return;
        }
 
        this.labelSubscription?.unsubscribe();
        this.labelSubscription = labelControl.valueChanges
            .pipe(startWith(labelControl.value))
            .subscribe((value: string) => this.labelChanged.emit(value ?? ''));
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
        const coverContentControl = this.contentStep?.contentForm?.get('cover_page.content');
        const headerContentControl = this.contentStep?.contentForm?.get('header.content');
        const footerContentControl = this.contentStep?.contentForm?.get('footer.content');
        const contentValue = contentControl?.value ?? this.docInstance?.template_data;
        const coverContentValue = coverContentControl?.value ?? this.docInstance?.cover_page?.content;
        const headerContentValue = headerContentControl?.value ?? this.docInstance?.header?.content;
        const footerContentValue = footerContentControl?.value ?? this.docInstance?.footer?.content;
        const hasContent =
            this.hasMeaningfulContent(contentValue)
            || this.hasMeaningfulContent(coverContentValue)
            || this.hasMeaningfulContent(headerContentValue)
            || this.hasMeaningfulContent(footerContentValue);
        if (!hasContent) {
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
            backdrop: 'static',
            windowClass: 'dg-modal-window',
            backdropClass: 'dg-modal-window-backdrop'
        });

        modalRef.componentInstance.title = 'Confirm change';
        modalRef.componentInstance.message =
            'Changing the template or object type will clear the current document, cover, header, and footer content. Do you want to continue?';
        modalRef.componentInstance.confirmLabel = 'Yes, clear content';
        modalRef.componentInstance.cancelLabel = 'Cancel';
        modalRef.componentInstance.warningTitle = 'Warning:';
        modalRef.componentInstance.warningIconClass = 'fas fa-exclamation-triangle';

        modalRef.result
            .then((result: string) => {
                if (result === 'confirmed') {
                    this.contentStep?.contentForm?.get('template_data')?.setValue('');
                    this.contentStep?.contentForm?.get('cover_page.content')?.setValue('');
                    this.contentStep?.contentForm?.get('header.content')?.setValue('');
                    this.contentStep?.contentForm?.get('footer.content')?.setValue('');
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
        const container = document.createElement('div');
        container.innerHTML = raw;
        const text = (container.textContent || container.innerText || '')
            .replace(/\s+/g, ' ')
            .trim();
        return text.length > 0;
    }

    private confirmSaveBeforePreview(objectId: number): void {
        const modalRef = this.modalService.open(CoreWarningModalComponent, {
            size: 'md',
            backdrop: 'static',
            windowClass: 'dg-modal-window',
            backdropClass: 'dg-modal-window-backdrop'
        });

        modalRef.componentInstance.title = 'Save template for preview';
        modalRef.componentInstance.message =
            'To generate a preview document, your template must be saved first. Continue and save now?';
        modalRef.componentInstance.confirmLabel = 'Save and Preview';
        modalRef.componentInstance.cancelLabel = 'Cancel';
        modalRef.componentInstance.warningTitle = 'Information:';
        modalRef.componentInstance.warningIconClass = 'fas fa-info-circle';

        modalRef.result
            .then((result: string) => {
                if (result === 'confirmed') {
                    void this.saveAndPreviewDocument(objectId);
                }
            })
            .catch(() => {
                return;
            });
    }


    private async saveAndPreviewDocument(objectId: number): Promise<void> {
        if (this.previewInProgress) {
            return;
        }

        this.previewInProgress = true;

        try {
            const templateId = await this.saveTemplateForPreview();
            const response = await firstValueFrom(this.docapiService.getRenderedObjectDoc(templateId, objectId));
            const filename = this.getPreviewFilename();
            this.fileSaverService.save(response.body, filename);
            this.toast.success('Preview document downloaded successfully.');
        } catch {
            this.toast.error('Unable to generate preview. Please review your template and try again.');
        } finally {
            this.previewInProgress = false;
        }
    }


    private async saveTemplateForPreview(): Promise<number> {
        if (!this.docInstance && this.mode === CmdbMode.Create) {
            this.docInstance = new DocTemplate();
        }

        this.updateDocInstance();

        if (this.mode === CmdbMode.Create) {
            const createdResponse = await firstValueFrom(this.docapiService.postDocTemplate(this.docInstance));
            const createdTemplateId = this.extractTemplateId(createdResponse);
            if (!createdTemplateId) {
                throw new Error('Template creation did not return a valid template ID');
            }

            this.docInstance.public_id = createdTemplateId;
            this.mode = CmdbMode.Edit;
            this.toast.success('Template saved successfully.');
            return createdTemplateId;
        }

        const updateResponse = await firstValueFrom(this.docapiService.putDocTemplate(this.docInstance));
        const updatedTemplateId = updateResponse?.body?.public_id ?? this.docInstance?.public_id;
        if (!updatedTemplateId) {
            throw new Error('Template update did not return a valid template ID');
        }

        this.docInstance.public_id = updatedTemplateId;
        this.toast.success('Template saved successfully.');
        return updatedTemplateId;
    }


    private getPreviewFilename(): string {
        const templateName = this.docInstance?.name?.trim() || this.docInstance?.label?.trim() || 'template-preview';
        return `${templateName}.pdf`;
    }


    private extractTemplateId(response: any): number | null {
        const templateIdCandidates = [
            response?.body?.public_id,
            response?.public_id,
            response?.body,
            response
        ];

        for (const candidate of templateIdCandidates) {
            const parsedId = Number(candidate);
            if (Number.isFinite(parsedId) && parsedId > 0) {
                return parsedId;
            }
        }

        return null;
    }

    /**
     * Handles the creation of a new document by making an API call.
     * On success, navigates to the document list with a success query parameter.
     */
    private handleCreateMode(): void {
        this.loaderService.show();

        this.docapiService.postDocTemplate(this.docInstance).pipe(
            finalize(() => {
                this.isSaving = false;
                this.loaderService.hide();
            })
        ).subscribe({
            next: (publicIdResp: string) => {
                this.toast.success("Template successfully created!");
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
        this.loaderService.show();

        this.docapiService.putDocTemplate(this.docInstance).pipe(
            finalize(() => {
                this.isSaving = false;
                this.loaderService.hide();
            })
        ).subscribe({
            next: (updateResp: DocTemplateUpdateResponse) => {
                const publicId = updateResp.body?.public_id;
                const name = updateResp.body?.name;
                this.toast.success(`Template successfully edited: ${name}`);
                this.router.navigate(['/docapi/'], { queryParams: { docEditSuccess: publicId } });
            },
            error: (error: any) => {
                // console.error(error);
            }
        });
    }
}
