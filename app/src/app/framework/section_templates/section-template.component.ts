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
import { Component, inject, OnDestroy, OnInit } from '@angular/core';

import { finalize, takeUntil } from 'rxjs/operators';
import { ReplaySubject } from 'rxjs';

import { v4 as uuidv4 } from 'uuid';
import { NgbModal, NgbModalRef } from '@ng-bootstrap/ng-bootstrap';

import { SectionTemplateService } from './services/section-template.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

import { APIGetMultiResponse, APIUpdateSingleResponse } from 'src/app/services/models/api-response';
import { SectionTemplateDeleteModalComponent } from './layout/modals/section-template-delete/section-template-delete-modal.component';
import { CmdbSectionTemplate, Field } from '../models/cmdb-section-template';
import { SectionTemplateTransformModalComponent } from './layout/modals/section-template-transform/section-template-transform-modal.component';
import { SectionTemplateCloneModalComponent } from './layout/modals/section-template-clone/section-template-clone-modal.component';
import { PreviewModalComponent } from '../type/builder/modals/preview-modal/preview-modal.component';
import { LoaderService } from 'src/app/core/services/loader.service';
/* ------------------------------------------------------------------------------------------------------------------ */

export interface GlobalTemplateCounts {
    'types': number,
    'objects': number
}

@Component({
    selector: 'cmdb-section-template',
    templateUrl: './section-template.component.html',
    styleUrls: ['./section-template.component.scss'],
    standalone: false
})
export class SectionTemplateComponent implements OnInit, OnDestroy {
    private readonly sectionTemplateService = inject(SectionTemplateService);
    private readonly modalService = inject(NgbModal);
    private readonly toastService = inject(ToastService);
    private readonly loaderService = inject(LoaderService);

    public sectionTemplates: any = [];
    private unsubscribe: ReplaySubject<void> = new ReplaySubject<void>();

    private modalRef: NgbModalRef;
    public isLoading$ = this.loaderService.isLoading$;

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    ngOnInit(): void {
        this.getAllSectionTemplates();
    }


    ngOnDestroy(): void {
        if (this.modalRef) {
            this.modalRef.close();
        }
    }

    /* -------------------------------------------------- API FUNCTIONS ------------------------------------------------- */

    /**
     * Retrieves all section templates from database
     */
    getAllSectionTemplates() {
        this.loaderService.show();
        this.sectionTemplateService.getSectionTemplates().pipe(takeUntil(this.unsubscribe), finalize(() => this.loaderService.hide()))
        .subscribe({
            next: (apiResponse: APIGetMultiResponse<CmdbSectionTemplate>) => {
                        this.sectionTemplates = apiResponse.results;
            },
            error: (error) => this.toastService.error(error?.error?.message)}
        );
    }

    /* ------------------------------------------------- MODAL HANDLING ------------------------------------------------- */

    /**
     * Displays a modal view for user to confirm deletion of section template
     * @param sectionTemplate instance of section template which should be deleted
     */
    showDeleteModal(sectionTemplate: CmdbSectionTemplate) {
        this.loaderService.show();

        this.sectionTemplateService.getGlobalSectionTemplateCount(sectionTemplate.public_id).pipe(finalize(() => this.loaderService.hide()))
            .subscribe({
                next: (response: GlobalTemplateCounts) => {
                    let counts: GlobalTemplateCounts = response

                    this.modalRef = this.modalService.open(SectionTemplateDeleteModalComponent, {
                        size: 'lg',
                        windowClass: 'dg-modal-window',
                        backdropClass: 'dg-modal-window-backdrop'
                    });
                    this.modalRef.componentInstance.sectionTemplate = sectionTemplate;
                    this.modalRef.componentInstance.templateCounts = counts;

                    this.modalRef.result.then((sectionTemplateID: number) => {
                        //Delete the section template
                        if (sectionTemplateID > 0) {
                            this.loaderService.show();
                            this.sectionTemplateService.deleteSectionTemplate(sectionTemplateID).pipe(finalize(() => this.loaderService.hide()))
                                .subscribe({
                                    next: (res: any) => {
                                        this.toastService.success("Section Template with ID " + sectionTemplateID + " deleted!");
                                        this.getAllSectionTemplates();
                                    },
                                    error: (error) => this.toastService.error(error?.error?.message)
                                });
                        }
                    });
                }
            });
    }


    /**
     * Displays a modal view for user to confirm transformation of 
     * section template to a global section template
     * 
     * @param sectionTemplate instance of section template which should be transformed
     */
    showTransformModal(sectionTemplate: CmdbSectionTemplate) {
        this.modalRef = this.modalService.open(SectionTemplateTransformModalComponent, {
            size: 'lg',
            windowClass: 'dg-modal-window',
            backdropClass: 'dg-modal-window-backdrop'
        });
        this.modalRef.componentInstance.sectionTemplate = sectionTemplate;

        this.modalRef.result.then((sectionTemplateID: number) => {
            //Delete the section template
            if (sectionTemplateID > 0) {
                let params = {
                    'name': sectionTemplate.name,
                    'label': sectionTemplate.label,
                    'type': 'section',
                    'is_global': true,
                    'predefined': false,
                    'fields': JSON.stringify(sectionTemplate.fields),
                    'public_id': sectionTemplate.public_id
                }

                this.loaderService.show();

                this.sectionTemplateService.updateSectionTemplate(params).pipe(finalize(() => this.loaderService.hide()))
                    .subscribe({
                        next: (res: APIUpdateSingleResponse) => {
                            this.toastService.success(`Section Template with ID: ${sectionTemplate.public_id} transformed 
                                            to a Global Section Template!`);
                            this.getAllSectionTemplates();
                        },
                        error: (error) => this.toastService.error(error?.error?.message)
                    }
                    );
            }
        });
    }


    /**
     * Displays a modal view for user to clone a section template
     * 
     * @param sectionTemplate instance of section template which should be cloned
     */
    public showCloneModal(sectionTemplate: CmdbSectionTemplate) {
        this.modalRef = this.modalService.open(SectionTemplateCloneModalComponent, {
            size: 'lg',
            windowClass: 'dg-modal-window',
            backdropClass: 'dg-modal-window-backdrop'
        });
        this.modalRef.componentInstance.sectionTemplate = sectionTemplate;

        this.modalRef.result.then((values: any) => {
            if (values) {

                const updatedFields: Field[] = this.setNewFieldIDs(sectionTemplate.fields);

                let params = {
                    'name': sectionTemplate.name,
                    'label': values.templateLabel,
                    'type': 'section',
                    'is_global': values.isGlobal,
                    'predefined': false,
                    'fields': JSON.stringify(updatedFields)
                }

                params.name = this.generateSectionTemplateName(values.isGlobal);

                this.loaderService.show();

                this.sectionTemplateService.postSectionTemplate(params).pipe(finalize(() => this.loaderService.hide())).subscribe({
                    next: (res: any) => {
                        this.toastService.success("Section Template cloned!");
                        this.getAllSectionTemplates();
                    },
                    error: error => {
                        this.toastService.error(error?.error?.message);
                    }
                });
            }
        });
    }


    /**
     * Displays a preview of a section template with all fields
     * 
     * @param sectionTemplate The section template which should be previewed
     */
    public showTemplatePreview(sectionTemplate: CmdbSectionTemplate) {
        const previewModal = this.modalService.open(PreviewModalComponent, {
            scrollable: true,
            windowClass: 'dg-modal-window',
            backdropClass: 'dg-modal-window-backdrop'
        });
        previewModal.componentInstance.sections = [sectionTemplate];
    }

    /* ------------------------------------------------ HELPER FUNCTIONS ------------------------------------------------ */

    /**
     * Creates new IDs for fields
     * 
     * @param fields Fields which require new IDs
     * @returns The given fields with new IDs
     */
    private setNewFieldIDs(fields: Field[]) {
        for (let field of fields) {
            field.name = this.generateFieldName(field.type);
        }

        return fields;
    }


    /**
     * Retrives the label for the "Type" column of the table
     * @param sectionTemplate The template for which the label should be calculated
     * @returns (string): Type name for the given section template
     */
    public getTemplateTypeLabel(sectionTemplate: CmdbSectionTemplate): string {
        if (sectionTemplate.predefined) {
            return "Predefined";
        }

        if (sectionTemplate.is_global) {
            return "Global";
        }

        return "Standard";
    }


    /**
     * Generates a new name for a field
     * @param fieldType Type of the field
     */
    private generateFieldName(fieldType: string) {
        return `${fieldType}-${uuidv4()}`
    }


    /**
     * Generates a unique name for section templates
     * 
     * @returns unique name for section templates
     */
    public generateSectionTemplateName(isGlobal: boolean = false) {
        if (isGlobal) {
            return `dg_gst-${uuidv4()}`;
        }

        return `section_template-${uuidv4()}`;
    }
}
