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
import { Component, Input } from '@angular/core';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';

import { TemplateHelperService } from '../../../../settings/services/template-helper.service';

import { CmdbMode } from '../../../../framework/modes.enum';
/* ------------------------------------------------------------------------------------------------------------------ */

declare var tinymce;

@Component({
    selector: 'cmdb-docapi-builder-content-step',
    templateUrl: './docapi-builder-content-step.component.html',
    styleUrls: ['./docapi-builder-content-step.component.scss'],
    standalone: false
})
export class DocapiBuilderContentStepComponent {

    @Input()
    set preData(data: any) {
        if (data !== undefined) {
            this.contentForm?.patchValue(data);
        }
    }

    @Input()
    set typeParam(data: any) {
        if (data) {
            if (data.type) {
                this.templateHelperService?.getObjectTemplateHelperData(data?.type).then(helperData => {
                    this.templateHelperData = helperData;
                });
            }
        }
    }

    @Input() public mode: CmdbMode;
    public modes = CmdbMode;
    public contentForm: UntypedFormGroup;
    public templateHelperData: any;

    public editorConfig = {
        base_url: '/tinymce',
        suffix: '.min',
        height: 500,
        menubar: false,
        plugins: [
            'advlist autolink lists link image charmap',
            'searchreplace visualblocks code',
            'insertdatetime media table paste',
            'noneditable, pagebreak, hr'
        ],
        toolbar1:
            'undo redo | formatselect | bold italic underline forecolor backcolor removeformat | \
            alignleft aligncenter alignright alignjustify | \
            bullist numlist outdent indent | image table hr pagebreak | code ',
        toolbar2: 'cmdbdata',
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
        }
    };


    public get content() {
        return this.contentForm?.get('template_data');
    }

    constructor(private templateHelperService: TemplateHelperService) {
        this.contentForm = new UntypedFormGroup({
            template_data: new UntypedFormControl('', [Validators.required, Validators.max(15 * 1024 * 1024)])
        });
    }


    public getCmdbDataMenuItems(editor) {
        const items = [];
        items.push(this.getBarcodeMenuItem(editor));
        items.push({
            type: 'nestedmenuitem',
            text: 'Object Template Data',
            icon: 'code-sample',
            getSubmenuItems: () => {
                return this.getObjectDataMenuItems(editor);
            }
        });
        return items;
    }


    public getObjectDataMenuItems(editor, templateHelperData = this.templateHelperData) {
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
}
