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
import { Component, inject, Input, OnInit } from '@angular/core';
import { UntypedFormControl, UntypedFormGroup } from '@angular/forms';
import { NgbActiveModal, NgbModal } from '@ng-bootstrap/ng-bootstrap';
import type { Editor as TinyMceEditor } from 'tinymce';

import { DEFAULT_PAGE_MARGINS, PageMargins, parseMarginValue } from '../../../utils/page-margins.util';
import {
    DocTemplateCoverPage,
    DocTemplatePageSection,
    DocTemplateTableOfContents,
    DocTemplateTocBaseStyle
} from '../../../models/cmdb-doctemplate';
import { DocapiEditorConfigService } from '../../../services/docapi-editor-config.service';
import { ExternalObjectSelectorModalComponent } from '../../external-object-selector-modal/external-object-selector-modal.component';
import { RelationTemplateSelectorModalComponent } from '../../relation-template-selector-modal/relation-template-selector-modal.component';
import { DEFAULT_COVER_PAGE, normalizeCoverPage } from '../../../utils/cover-page.util';
import {
    DEFAULT_FOOTER,
    DEFAULT_HEADER,
    MIN_PAGE_SECTION_HEIGHT_PT,
    MAX_PAGE_SECTION_HEIGHT_PT,
    normalizeFooter,
    normalizeHeader
} from '../../../utils/page-section.util';
import {
    DEFAULT_TABLE_OF_CONTENTS,
    DEFAULT_TABLE_OF_CONTENTS_CONFIG,
    normalizeTableOfContents,
    normalizeTableOfContentsConfig
} from '../../../utils/table-of-contents.util';

type DocumentOptionsTab = 'margins' | 'cover' | 'header' | 'footer' | 'toc';

export interface DocumentOptionsModalResult {
    margins: PageMargins;
    coverPage: DocTemplateCoverPage;
    header: DocTemplatePageSection;
    footer: DocTemplatePageSection;
    tableOfContents: DocTemplateTableOfContents;
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
    @Input() public initialTableOfContents: DocTemplateTableOfContents = normalizeTableOfContents(DEFAULT_TABLE_OF_CONTENTS);
    @Input() public templateType: string = 'DEFAULT';
    @Input() public templateTypeId: number | null = null;
    @Input() public templateHelperData: unknown[] = [];

    public activeTab: DocumentOptionsTab = 'margins';
    public coverEditorConfig: Record<string, unknown> = {};
    public headerEditorConfig: Record<string, unknown> = {};
    public footerEditorConfig: Record<string, unknown> = {};
    public readonly pageSectionHeightConstraintHint =
        `Design the content that appears in this section. Allowed content height: ${MIN_PAGE_SECTION_HEIGHT_PT}pt to ${MAX_PAGE_SECTION_HEIGHT_PT}pt.`;
    private sectionHeights: Record<'header' | 'footer', number> = {
        header: MIN_PAGE_SECTION_HEIGHT_PT,
        footer: MIN_PAGE_SECTION_HEIGHT_PT
    };

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
        footer_content: new UntypedFormControl(''),
        table_of_contents_activated: new UntypedFormControl(DEFAULT_TABLE_OF_CONTENTS.activated),
        table_of_contents_config: new UntypedFormGroup({
            pdftoc: new UntypedFormGroup({
                'line-height': new UntypedFormControl(DEFAULT_TABLE_OF_CONTENTS_CONFIG.pdftoc['line-height'])
            }),
            level0: this.createTocLevelGroup(DEFAULT_TABLE_OF_CONTENTS_CONFIG.level0),
            level1: this.createTocLevelGroup(DEFAULT_TABLE_OF_CONTENTS_CONFIG.level1),
            level2: this.createTocLevelGroup(DEFAULT_TABLE_OF_CONTENTS_CONFIG.level2),
            level3: this.createTocLevelGroup(DEFAULT_TABLE_OF_CONTENTS_CONFIG.level3),
            level4: this.createTocLevelGroup(DEFAULT_TABLE_OF_CONTENTS_CONFIG.level4),
            level5: this.createTocLevelGroup(DEFAULT_TABLE_OF_CONTENTS_CONFIG.level5)
        })
    });
    public validationError = '';

    public readonly activeModal = inject(NgbActiveModal);
    private readonly editorConfigService = inject(DocapiEditorConfigService);
    private readonly modalService = inject(NgbModal);


    public ngOnInit(): void {
        const normalizedCoverPage = normalizeCoverPage(this.initialCoverPage);
        const normalizedHeader = normalizeHeader(this.initialHeader);
        const normalizedFooter = normalizeFooter(this.initialFooter);
        const normalizedTableOfContents = normalizeTableOfContents(this.initialTableOfContents);
        this.sectionHeights.header = this.normalizePageSectionHeight(normalizedHeader?.config?.height);
        this.sectionHeights.footer = this.normalizePageSectionHeight(normalizedFooter?.config?.height);

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
            footer_content: normalizedFooter.content,
            table_of_contents_activated: normalizedTableOfContents.activated,
            table_of_contents_config: normalizeTableOfContentsConfig(normalizedTableOfContents.config)
        });

        this.initializeEditorConfig();
    }


    public cancel(): void {
        this.activeModal.dismiss();
    }


    public selectTab(tab: DocumentOptionsTab): void {
        this.activeTab = tab;
    }

    public get isApplyDisabled(): boolean {
        const isHeaderActivated = !!this.form.get('header_activated')?.value;
        const isFooterActivated = !!this.form.get('footer_activated')?.value;
        const headerContent = this.form.get('header_content')?.value;
        const footerContent = this.form.get('footer_content')?.value;

        if (isHeaderActivated && !this.hasMeaningfulContent(headerContent)) {
            return true;
        }

        if (isFooterActivated && !this.hasMeaningfulContent(footerContent)) {
            return true;
        }

        return false;
    }


    public apply(): void {
        const top = parseMarginValue(this.form.get('top')?.value);
        const bottom = parseMarginValue(this.form.get('bottom')?.value);
        const left = parseMarginValue(this.form.get('left')?.value);
        const right = parseMarginValue(this.form.get('right')?.value);
        const isHeaderActivated = !!this.form.get('header_activated')?.value;
        const isFooterActivated = !!this.form.get('footer_activated')?.value;
        const headerContent = this.form.get('header_content')?.value;
        const footerContent = this.form.get('footer_content')?.value;

        if (top === null || bottom === null || left === null || right === null) {
            this.validationError = 'Please enter valid margin values (numbers >= 0).';
            return;
        }

        if (isHeaderActivated && !this.hasMeaningfulContent(headerContent)) {
            this.activeTab = 'header';
            this.validationError = `Header content cannot be empty. Minimum content height is ${MIN_PAGE_SECTION_HEIGHT_PT}pt.`;
            return;
        }

        if (isFooterActivated && !this.hasMeaningfulContent(footerContent)) {
            this.activeTab = 'footer';
            this.validationError = `Footer content cannot be empty. Minimum content height is ${MIN_PAGE_SECTION_HEIGHT_PT}pt.`;
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
                    height: this.sectionHeights.header
                }
            } as DocTemplatePageSection,
            footer: {
                activated: !!this.form.get('footer_activated')?.value,
                content: this.form.get('footer_content')?.value ?? '',
                config: {
                    height: this.sectionHeights.footer
                }
            } as DocTemplatePageSection,
            tableOfContents: {
                activated: !!this.form.get('table_of_contents_activated')?.value,
                config: normalizeTableOfContentsConfig(this.form.get('table_of_contents_config')?.value)
            } as DocTemplateTableOfContents
        } as DocumentOptionsModalResult);
    }


    private initializeEditorConfig(): void {
        const baseConfig = this.editorConfigService.createConfig({
            getTemplateType: () => this.templateType,
            getTemplateHelperData: () => this.templateHelperData,
            onPreviewRequested: () => undefined,
            onPageMarginsRequested: () => undefined,
            onAiAssistantRequested: () => undefined,
            onExternalObjectsRequested: (editor: TinyMceEditor) => this.openExternalObjectsModal(editor),
            onRelationTemplateRequested: (editor: TinyMceEditor) => this.openRelationTemplateModal(editor)
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
        this.headerEditorConfig = this.createPageSectionEditorConfig(sharedEditorConfig, 'header', 'Header');
        this.footerEditorConfig = this.createPageSectionEditorConfig(sharedEditorConfig, 'footer', 'Footer');
    }


    private createPageSectionEditorConfig(
        baseConfig: Record<string, unknown>,
        sectionType: 'header' | 'footer',
        sectionLabel: string
    ): Record<string, unknown> {
        const maxSectionHeightPx = this.pointsToPixels(MAX_PAGE_SECTION_HEIGHT_PT);
        const minSectionHeightPx = this.pointsToPixels(MIN_PAGE_SECTION_HEIGHT_PT);
        const existingContentStyle = typeof baseConfig['content_style'] === 'string'
            ? baseConfig['content_style']
            : '';
        const baseSetup = typeof baseConfig['setup'] === 'function'
            ? baseConfig['setup'] as (editor: TinyMceEditor) => void
            : null;

        return {
            ...baseConfig,
            content_style: `${existingContentStyle} body { min-height: ${MIN_PAGE_SECTION_HEIGHT_PT}pt; max-height: ${MAX_PAGE_SECTION_HEIGHT_PT}pt; overflow: hidden; }`,
            setup: (editor: TinyMceEditor) => {
                baseSetup?.(editor);
                this.setupPageSectionHeightGuard(editor, minSectionHeightPx, maxSectionHeightPx, sectionType, sectionLabel);
            }
        };
    }


    private setupPageSectionHeightGuard(
        editor: TinyMceEditor,
        minPageSectionHeightPx: number,
        maxPageSectionHeightPx: number,
        sectionType: 'header' | 'footer',
        sectionLabel: string
    ): void {
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
                text: `${sectionLabel} content height must stay between ${MIN_PAGE_SECTION_HEIGHT_PT}pt and ${MAX_PAGE_SECTION_HEIGHT_PT}pt.`,
                type: 'warning',
                timeout: 2200
            });
        };

        const updateSectionHeight = (): void => {
            const body = editor?.getBody?.();
            if (!body) {
                return;
            }

            this.sectionHeights[sectionType] = this.normalizePageSectionHeight(this.pixelsToPoints(body.scrollHeight));
        };

        const enforceLimit = (): void => {
            if (isReverting || !editor?.getBody) {
                return;
            }

            if (!isOverflowing()) {
                lastValidContent = editor.getContent({ format: 'raw' });
                updateSectionHeight();
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
            updateSectionHeight();
            showWarning();
        };

        editor.on('init', () => {
            lastValidContent = editor.getContent({ format: 'raw' });
            const body = editor?.getBody?.();
            if (body && body.scrollHeight < minPageSectionHeightPx) {
                body.style.minHeight = `${MIN_PAGE_SECTION_HEIGHT_PT}pt`;
            }
            updateSectionHeight();
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

    private pixelsToPoints(pixels: number): number {
        return Math.round((pixels * 72) / 96);
    }

    private normalizePageSectionHeight(height: unknown): number {
        const parsed = Number(height);
        const normalized = Number.isFinite(parsed) ? Math.trunc(parsed) : MIN_PAGE_SECTION_HEIGHT_PT;
        return this.clampPageSectionHeight(normalized);
    }

    private clampPageSectionHeight(height: number): number {
        return Math.min(MAX_PAGE_SECTION_HEIGHT_PT, Math.max(MIN_PAGE_SECTION_HEIGHT_PT, height));
    }

    private createTocLevelGroup(initial: Partial<DocTemplateTocBaseStyle>): UntypedFormGroup {
        return new UntypedFormGroup({
            'font-size': new UntypedFormControl(initial['font-size']),
            'margin-left': new UntypedFormControl(initial['margin-left']),
            'margin-top': new UntypedFormControl(initial['margin-top']),
            'margin-bottom': new UntypedFormControl(initial['margin-bottom']),
            'padding-bottom': new UntypedFormControl(initial['padding-bottom']),
            color: new UntypedFormControl(initial['color']),
            'font-style': new UntypedFormControl(initial['font-style']),
            'font-weight': new UntypedFormControl(initial['font-weight'])
        });
    }

    private hasMeaningfulContent(value: unknown): boolean {
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


    private openExternalObjectsModal(editor: TinyMceEditor): void {
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

    private openRelationTemplateModal(editor: TinyMceEditor): void {
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
