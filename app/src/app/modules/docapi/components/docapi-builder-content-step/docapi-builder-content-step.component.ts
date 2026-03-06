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
import { Component, EventEmitter, Input, Output } from '@angular/core';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { TemplateHelperService } from '../../../../settings/services/template-helper.service';
import { CmdbMode } from '../../../../framework/modes.enum';
import { ExternalObjectSelectorModalComponent } from '../external-object-selector-modal/external-object-selector-modal.component';
import { RelationTemplateSelectorModalComponent } from '../relation-template-selector-modal/relation-template-selector-modal.component';
import { ReportTemplateSelectorModalComponent } from '../report-template-selector-modal/report-template-selector-modal.component';
import { DEFAULT_PAGE_MARGINS, PageMargins, parseMarginValue, parsePageMarginsFromStyle } from '../../utils/page-margins.util';
/* ------------------------------------------------------------------------------------------------------------------ */

declare var tinymce;

@Component({
    selector: 'cmdb-docapi-builder-content-step',
    templateUrl: './docapi-builder-content-step.component.html',
    styleUrls: ['./docapi-builder-content-step.component.scss'],
    standalone: false
})
export class DocapiBuilderContentStepComponent {
    private readonly defaultPageMargins: PageMargins = { ...DEFAULT_PAGE_MARGINS };

    @Input()
    set preData(data: any) {
        if (data !== undefined) {
            this.contentForm?.patchValue(data);
            this.pageMargins = parsePageMarginsFromStyle(data?.template_style, this.defaultPageMargins);
        }
    }

    @Input()
    set typeParam(data: any) {
        if (data) {
            // Store the template type
            this.templateType = data.templateType;
            this.templateTypeId = data?.parameters?.type ?? null;
            if (data.parameters?.type) {
                // Pass the template type to the helper service
                this.templateHelperService?.getObjectTemplateHelperData(data.parameters.type, '', 5, this.templateType).then(helperData => {
                    this.templateHelperData = helperData;
                });
            }
        }
    }

    @Input() public mode: CmdbMode;
    @Output() public previewRequested = new EventEmitter<void>();
    @Output() public pageMarginsChanged = new EventEmitter<PageMargins>();
    public modes = CmdbMode;
    public contentForm: UntypedFormGroup;
    public templateHelperData: any;
    public templateType: string = 'OBJECT';
    public templateTypeId: number | null = null;
    private pageMargins: PageMargins = { ...this.defaultPageMargins };


    public editorConfig = {
        base_url: '/tinymce',
        suffix: '.min',
        height: 500,
        menubar: false,
        plugins: [
            'accordion', 'advlist', 'anchor', 'autolink', 'autosave', 'charmap', 'code',
            'codesample', 'directionality', 'emoticons', 'fullscreen', 'help', 'image',
            'importcss', 'insertdatetime', 'link', 'lists', 'media',
            'nonbreaking', 'noneditable', 'pagebreak', 'preview', 'quickbars', 'save', 'searchreplace',
            'table', 'visualblocks', 'visualchars', 'wordcount',
            'hr'
        ],
        toolbar1:
            'undo redo | formatselect | bold italic underline forecolor backcolor removeformat | \
            alignleft aligncenter alignright alignjustify | \
            bullist numlist outdent indent | image table hr pagebreak | code ',
        toolbar2: 'cmdbdata pagemargins | previewdoc',
        noneditable_noneditable_class: 'mceNonEditable',
        paste_data_images: true,
        automatic_uploads: true,
        file_picker_types: 'image',
        file_picker_callback: (cb, value, meta) => {
            const input = document.createElement('input');
            input.setAttribute('type', 'file');
            input.setAttribute('accept', 'image/png,image/jpeg');
            input.onchange = () => {
                const file = input?.files[0];
                const reader = new FileReader();
                reader.onload = () => {
                    const id = 'blobid' + (new Date()).getTime();
                    const blobCache = tinymce?.activeEditor?.editorUpload?.blobCache;
                    const base64 = (reader?.result as string).split(',')[1];
                    const blobInfo = blobCache?.create(id, file, base64);
                    blobCache?.add(blobInfo);
                    cb(blobInfo.blobUri(), { title: file?.name });
                };
                reader?.readAsDataURL(file);
            };
            input?.click();
        },
        pagebreak_separator: '<pdf:nextpage />',
        extended_valid_elements: 'pdf:barcode[*]',
        custom_elements: 'pdf:barcode',
        valid_children: '-pdf:barcode[*]',
        content_css: '/assets/css/tinymce_custom.css',
        setup: (editor) => {
            editor?.ui?.registry?.addMenuButton('cmdbdata', {
                text: 'CMDB Data',
                icon: 'plus',
                fetch: (callback) => {
                    const items = this.getCmdbDataMenuItems(editor);
                    callback(items);
                }
            });

            editor?.ui?.registry?.addButton('previewdoc', {
                text: 'Preview',
                icon: 'preview',
                tooltip: 'Preview Document',
                onAction: () => this.previewRequested.emit()
            });

            editor?.ui?.registry?.addButton('pagemargins', {
                text: 'Page Margins',
                tooltip: 'Set page margins for all pages',
                onAction: () => this.openPageMarginsDialog(editor)
            });
        }
    };


    public get content() {
        return this.contentForm?.get('template_data');
    }

    
    constructor(
        private templateHelperService: TemplateHelperService,
        private modalService: NgbModal
    ) {
        this.contentForm = new UntypedFormGroup({
            template_data: new UntypedFormControl('', [Validators.required, Validators.max(15 * 1024 * 1024)])
        });
    }


    public getCmdbDataMenuItems(editor) {
        const items = [];
        items.push(this.getBarcodeMenuItem(editor));
        items.push({
            type: 'nestedmenuitem',
            text: 'Object Data',
            icon: 'code-sample',
            getSubmenuItems: () => {
                return this.getObjectDataMenuItems(editor, this.templateHelperData, true);
            }
        });
        
        if (this.templateType === 'DEFAULT') {
            items.push(this.getExternalObjectsMenuItem(editor));
            items.push(this.getReportMenuItem(editor));
        }
        
        return items;
    }


    public getObjectDataMenuItems(editor, templateHelperData = this.templateHelperData, isRoot: boolean = false) {
        const items = [];
        for (const item of templateHelperData) {
            if (item.subdata) {
                items.push({
                    type: 'nestedmenuitem',
                    text: item.label,
                    icon: 'chevron-right',
                    getSubmenuItems: () => {
                        return this.getObjectDataMenuItems(editor, item?.subdata);
                    }
                });
            } else {
                let icon = 'sourcecode';

                if (item?.label === 'Public ID') {
                    icon = 'character-count';
                }

                items.push({
                    type: 'menuitem',
                    text: item?.label,
                    icon,
                    onAction: function () {
                        editor.insertContent(item?.templatedata);
                    }
                });
            }
        }

        if (isRoot && this.templateType === 'DEFAULT') {
            items.push(this.getRelationsMenuItem(editor));
        }

        return items;
    }


    public getBarcodeMenuItem(editor) {
        const item = {
            type: 'menuitem',
            text: 'Barcode',
            icon: 'align-justify',
            onAction: () => {
                const selection = editor.selection.getNode();
                const preData = {};
                if (selection?.tagName === 'PDF:BARCODE') {
                    preData['type'] = selection?.attributes?.getNamedItem('type')?.value;
                    preData['content'] = selection?.attributes?.getNamedItem('value')?.value;
                }
                editor?.windowManager?.open({
                    title: 'Insert Barcode',
                    body: {
                        type: 'panel',
                        items: [
                            {
                                type: 'input',
                                name: 'content',
                                label: 'Barcode Content'
                            },
                            {
                                type: 'selectbox',
                                name: 'type',
                                label: 'Barcode Type',
                                items: [
                                    { value: 'qr', text: 'QR' },
                                    { value: 'code128', text: 'Code 128' },
                                ]
                            }
                        ]
                    },
                    buttons: [
                        {
                            type: 'submit',
                            text: 'OK'
                        }
                    ],
                    initialData: preData,
                    onSubmit: (dialogApi) => {
                        const barcodeContent = dialogApi?.getData()['content'];
                        const barcodeType = dialogApi?.getData()['type'];
                        const barcodeElementAttr = {
                            class: 'mceNonEditable',
                            type: barcodeType,
                            value: barcodeContent
                        };
                        if (barcodeType === 'qr') {
                            barcodeElementAttr['barwidth'] = '3cm';
                            barcodeElementAttr['barheight'] = '3cm';
                        }
                        const barcodeElement = editor?.dom?.create('pdf:barcode', barcodeElementAttr);
                        if (preData['content']) {
                            let selectionNext = editor?.selection?.getNode()?.nextSibling;
                            editor.dom.remove(selection);
                            if (selectionNext) {
                                editor?.selection?.setCursorLocation(selectionNext);
                            }
                        }
                        editor?.insertContent(barcodeElement?.outerHTML);
                        dialogApi?.close();
                    }
                });
            }
        };
        return item;
    }


    public getExternalObjectsMenuItem(editor) {
        const item = {
            type: 'menuitem',
            text: 'External objects',
            icon: 'link',
            onAction: () => {
                this.openExternalObjectsModal(editor);
            }
        };
        return item;
    }


    public getRelationsMenuItem(editor) {
        const item = {
            type: 'menuitem',
            text: 'Relations',
            icon: 'link',
            onAction: () => {
                this.openRelationTemplateModal(editor);
            }
        };
        return item;
    }


    public getReportMenuItem(editor) {
        const item = {
            type: 'menuitem',
            text: 'Report',
            icon: 'table',
            onAction: () => {
                this.openReportTemplateModal(editor);
            }
        };
        return item;
    }


    private openExternalObjectsModal(editor: any): void {
        const modalRef = this.modalService.open(ExternalObjectSelectorModalComponent, {
            size: 'xl',
            backdrop: 'static'
        });
        
        modalRef.componentInstance.insertTemplate.subscribe((template: string) => {
            editor.insertContent(template);
        });
    }


    private openRelationTemplateModal(editor: any): void {
        const modalRef = this.modalService.open(RelationTemplateSelectorModalComponent, {
            size: 'lg',
            backdrop: 'static'
        });

        modalRef.componentInstance.rootTypeId = this.templateTypeId;
        modalRef.componentInstance.insertTemplate.subscribe((template: string) => {
            editor.insertContent(template);
        });
    }


    private openReportTemplateModal(editor: any): void {
        const modalRef = this.modalService.open(ReportTemplateSelectorModalComponent, {
            size: 'xl',
            backdrop: 'static'
        });

        modalRef.componentInstance.insertTemplate.subscribe((template: string) => {
            editor.insertContent(template);
        });
    }


    private openPageMarginsDialog(editor: any): void {
        editor?.windowManager?.open({
            title: 'Page Margins (All Pages)',
            body: {
                type: 'panel',
                items: [
                    { type: 'input', name: 'top', label: 'Margin: top (mm)' },
                    { type: 'input', name: 'bottom', label: 'Margin: bottom (mm)' },
                    { type: 'input', name: 'left', label: 'Margin: left (mm)' },
                    { type: 'input', name: 'right', label: 'Margin: right (mm)' }
                ]
            },
            buttons: [
                {
                    type: 'submit',
                    text: 'Apply'
                }
            ],
            initialData: {
                top: this.pageMargins.top.toString(),
                bottom: this.pageMargins.bottom.toString(),
                left: this.pageMargins.left.toString(),
                right: this.pageMargins.right.toString()
            },
            onSubmit: (dialogApi) => {
                const data = dialogApi?.getData();
                const top = parseMarginValue(data?.top);
                const bottom = parseMarginValue(data?.bottom);
                const left = parseMarginValue(data?.left);
                const right = parseMarginValue(data?.right);

                if (top === null || bottom === null || left === null || right === null) {
                    editor?.windowManager?.alert('Please enter valid margin values (numbers >= 0).');
                    return;
                }

                const margins: PageMargins = { top, bottom, left, right };
                this.pageMargins = margins;
                this.pageMarginsChanged.emit(margins);
                dialogApi?.close();
            }
        });
    }
}
