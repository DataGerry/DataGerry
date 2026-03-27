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
import { Component, Input, OnInit } from '@angular/core';
import { UntypedFormControl, UntypedFormGroup } from '@angular/forms';
import { NgbActiveModal, NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { DEFAULT_PAGE_MARGINS, PageMargins, parseMarginValue } from '../../../utils/page-margins.util';
import { DocTemplateCoverPage, DocTemplatePageSection } from '../../../models/cmdb-doctemplate';
import { DocapiEditorConfigService } from '../../../services/docapi-editor-config.service';
import { environment } from '../../../../../../environments/environment';
import { ExternalObjectSelectorModalComponent } from '../../external-object-selector-modal/external-object-selector-modal.component';
import { RelationTemplateSelectorModalComponent } from '../../relation-template-selector-modal/relation-template-selector-modal.component';
import { DEFAULT_COVER_PAGE, normalizeCoverPage } from '../../../utils/cover-page.util';
import {
    DEFAULT_FOOTER,
    DEFAULT_HEADER,
    MAX_PAGE_SECTION_HEIGHT_PT,
    normalizeFooter,
    normalizeHeader
} from '../../../utils/page-section.util';

type DocumentOptionsTab = 'margins' | 'cover' | 'header' | 'footer';

export interface DocumentOptionsModalResult {
    margins: PageMargins;
    coverPage: DocTemplateCoverPage;
    header: DocTemplatePageSection;
    footer: DocTemplatePageSection;
}

@Component({
    selector: 'cmdb-docapi-document-options-modal',
    templateUrl: './docapi-document-options-modal.component.html',
    styleUrls: ['./docapi-document-options-modal.component.scss'],
    standalone: false
})
export class DocapiDocumentOptionsModalComponent implements OnInit {
    @Input() public initialMargins: PageMargins = { ...DEFAULT_PAGE_MARGINS };
    @Input() public initialCoverPage: DocTemplateCoverPage = { ...DEFAULT_COVER_PAGE };
    @Input() public initialHeader: DocTemplatePageSection = { ...DEFAULT_HEADER };
    @Input() public initialFooter: DocTemplatePageSection = { ...DEFAULT_FOOTER };
    @Input() public templateType: string = 'OBJECT';
    @Input() public templateTypeId: number | null = null;
    @Input() public templateHelperData: any[] = [];

    public activeTab: DocumentOptionsTab = 'margins';
    public coverEditorConfig: Record<string, unknown> = {};
    public headerEditorConfig: Record<string, unknown> = {};
    public footerEditorConfig: Record<string, unknown> = {};

    public readonly form = new UntypedFormGroup({
        top: new UntypedFormControl(''),
        bottom: new UntypedFormControl(''),
        left: new UntypedFormControl(''),
        right: new UntypedFormControl(''),
        cover_activated: new UntypedFormControl(false),
        cover_content: new UntypedFormControl(''),
        header_activated: new UntypedFormControl(false),
        header_content: new UntypedFormControl(''),
        footer_activated: new UntypedFormControl(false),
        footer_content: new UntypedFormControl('')
    });
    public validationError = '';

    constructor(
        public readonly activeModal: NgbActiveModal,
        private editorConfigService: DocapiEditorConfigService,
        private modalService: NgbModal
    ) { }


    public ngOnInit(): void {
        const normalizedCoverPage = normalizeCoverPage(this.initialCoverPage);
        const normalizedHeader = normalizeHeader(this.initialHeader);
        const normalizedFooter = normalizeFooter(this.initialFooter);

        this.form.patchValue({
            top: this.initialMargins.top.toString(),
            bottom: this.initialMargins.bottom.toString(),
            left: this.initialMargins.left.toString(),
            right: this.initialMargins.right.toString(),
            cover_activated: normalizedCoverPage.activated,
            cover_content: normalizedCoverPage.content,
            header_activated: normalizedHeader.activated,
            header_content: normalizedHeader.content,
            footer_activated: normalizedFooter.activated,
            footer_content: normalizedFooter.content
        });

        this.initializeEditorConfig();
    }


    public cancel(): void {
        this.activeModal.dismiss();
    }

    
    public selectTab(tab: DocumentOptionsTab): void {
        this.activeTab = tab;
    }


    public apply(): void {
        const top = parseMarginValue(this.form.get('top')?.value);
        const bottom = parseMarginValue(this.form.get('bottom')?.value);
        const left = parseMarginValue(this.form.get('left')?.value);
        const right = parseMarginValue(this.form.get('right')?.value);

        if (top === null || bottom === null || left === null || right === null) {
            this.validationError = 'Please enter valid margin values (numbers >= 0).';
            return;
        }

        this.validationError = '';
        this.activeModal.close({
            margins: { top, bottom, left, right } as PageMargins,
            coverPage: {
                activated: !!this.form.get('cover_activated')?.value,
                content: this.form.get('cover_content')?.value ?? '',
                config: {}
            } as DocTemplateCoverPage,
            header: {
                activated: !!this.form.get('header_activated')?.value,
                content: this.form.get('header_content')?.value ?? '',
                config: {
                    height: MAX_PAGE_SECTION_HEIGHT_PT
                }
            } as DocTemplatePageSection,
            footer: {
                activated: !!this.form.get('footer_activated')?.value,
                content: this.form.get('footer_content')?.value ?? '',
                config: {
                    height: MAX_PAGE_SECTION_HEIGHT_PT
                }
            } as DocTemplatePageSection
        } as DocumentOptionsModalResult);
    }


    private initializeEditorConfig(): void {
        const baseConfig = this.editorConfigService.createConfig({
            isCloudMode: environment.cloudMode,
            getTemplateType: () => this.templateType,
            getTemplateHelperData: () => this.templateHelperData,
            onPreviewRequested: () => undefined,
            onPageMarginsRequested: () => undefined,
            onAiAssistantRequested: () => undefined,
            onExternalObjectsRequested: (editor: any) => this.openExternalObjectsModal(editor),
            onRelationTemplateRequested: (editor: any) => this.openRelationTemplateModal(editor)
        });

        const toolbar2 = 'cmdbdata placeholders';
        const toolbar1 =
            'undo redo | formatselect | bold italic underline forecolor backcolor removeformat | \
            alignleft aligncenter alignright alignjustify | \
            bullist numlist outdent indent | image table hr | code';
        const plugins = Array.isArray(baseConfig['plugins'])
            ? (baseConfig['plugins'] as string[]).filter((plugin: string) => plugin !== 'pagebreak')
            : baseConfig['plugins'];

        const sharedEditorConfig = {
            ...baseConfig,
            height: 420,
            toolbar1,
            toolbar2,
            plugins
        };

        this.coverEditorConfig = sharedEditorConfig;
        this.headerEditorConfig = this.createPageSectionEditorConfig(sharedEditorConfig, 'Header');
        this.footerEditorConfig = this.createPageSectionEditorConfig(sharedEditorConfig, 'Footer');
    }


    private createPageSectionEditorConfig(baseConfig: Record<string, unknown>, sectionLabel: string): Record<string, unknown> {
        const maxSectionHeightPx = this.pointsToPixels(MAX_PAGE_SECTION_HEIGHT_PT);
        const existingContentStyle = typeof baseConfig['content_style'] === 'string'
            ? baseConfig['content_style']
            : '';
        const baseSetup = typeof baseConfig['setup'] === 'function' ? baseConfig['setup'] as (editor: any) => void : null;

        return {
            ...baseConfig,
            content_style: `${existingContentStyle} body { max-height: ${MAX_PAGE_SECTION_HEIGHT_PT}pt; overflow: hidden; }`,
            setup: (editor: any) => {
                baseSetup?.(editor);
                this.setupPageSectionHeightGuard(editor, maxSectionHeightPx, sectionLabel);
            }
        };
    }


    private setupPageSectionHeightGuard(editor: any, maxPageSectionHeightPx: number, sectionLabel: string): void {
        let lastValidContent = '';
        let isReverting = false;
        let lastWarningAt = 0;

        const isOverflowing = (): boolean => {
            const body = editor?.getBody?.();
            return !!body && body.scrollHeight > maxPageSectionHeightPx;
        };

        const isAtOrOverLimit = (): boolean => {
            const body = editor?.getBody?.();
            return !!body && body.scrollHeight >= maxPageSectionHeightPx;
        };

        const showWarning = (): void => {
            const now = Date.now();
            if (now - lastWarningAt < 1200) {
                return;
            }

            lastWarningAt = now;
            editor.notificationManager?.open({
                text: `${sectionLabel} content is limited to ${MAX_PAGE_SECTION_HEIGHT_PT}pt.`,
                type: 'warning',
                timeout: 2200
            });
        };

        const enforceLimit = (): void => {
            if (isReverting || !editor?.getBody) {
                return;
            }

            if (!isOverflowing()) {
                lastValidContent = editor.getContent({ format: 'raw' });
                return;
            }

            const selectionBookmark = editor.selection?.getBookmark?.(2, true);

            isReverting = true;
            editor.setContent(lastValidContent || '', { format: 'raw' });
            if (selectionBookmark) {
                try {
                    editor.selection?.moveToBookmark?.(selectionBookmark);
                } catch {
                    editor.selection?.select?.(editor.getBody(), true);
                    editor.selection?.collapse?.(false);
                }
            }
            isReverting = false;
            showWarning();
        };

        editor.on('init', () => {
            lastValidContent = editor.getContent({ format: 'raw' });
            enforceLimit();
        });
        editor.on('input', enforceLimit);
        editor.on('keyup', enforceLimit);
        editor.on('change', enforceLimit);
        editor.on('SetContent', enforceLimit);
        editor.on('Undo', enforceLimit);
        editor.on('Redo', enforceLimit);
        editor.on('paste', () => setTimeout(enforceLimit, 0));
        editor.on('keydown', (event: KeyboardEvent) => {
            if (event.key !== 'Enter') {
                return;
            }

            if (!isAtOrOverLimit()) {
                return;
            }

            event.preventDefault();
            event.stopPropagation();
            showWarning();
        });
    }


    private pointsToPixels(points: number): number {
        return Math.floor((points * 96) / 72);
    }


    private openExternalObjectsModal(editor: any): void {
        const modalRef = this.modalService.open(ExternalObjectSelectorModalComponent, {
            size: 'xl',
            backdrop: 'static'
        });

        modalRef.result
            .then((template: string) => {
                if (!template) {
                    return;
                }

                editor.insertContent(template);
            })
            .catch(() => undefined);
    }

    private openRelationTemplateModal(editor: any): void {
        const modalRef = this.modalService.open(RelationTemplateSelectorModalComponent, {
            size: 'lg',
            backdrop: 'static'
        });

        modalRef.componentInstance.rootTypeId = this.templateTypeId;

        modalRef.result
            .then((template: string) => {
                if (!template) {
                    return;
                }

                editor.insertContent(template);
            })
            .catch(() => undefined);
    }
}
