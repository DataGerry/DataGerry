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

* You should have received a copy of the GNU Affero General Public License
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { Component, EventEmitter, Input, Output, forwardRef } from '@angular/core';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';

import { FileDropzoneRejection } from './file-dropzone.model';

/** Guarantees a unique id per instance so the label and helper texts can be wired for screen readers. */
let uniqueDropzoneId = 0;

/**
 * Reusable click-or-drop file field.
 */
@Component({
    selector: 'app-file-dropzone',
    templateUrl: './file-dropzone.component.html',
    styleUrls: ['./file-dropzone.component.scss'],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => FileDropzoneComponent),
            multi: true
        }
    ],
    standalone: false
})
export class FileDropzoneComponent implements ControlValueAccessor {
    /** Optional field label rendered above the drop area. */
    @Input() label = '';

    /** Marks the field as required (adds the * next to the label). */
    @Input() required = false;

    /**
     * Accepted file extensions. Accepts a separated string (`'csv'`, `'.csv'`,
     * `'csv, json'`) or an array (`['csv', 'json']`). Values are normalised to
     * lowercase, dot-prefixed extensions. Leave empty to accept any file.
     */
    @Input()
    set acceptedExtensions(value: string | string[] | null | undefined) {
        this.extensions = this.normalizeExtensions(value);
        this.revalidateSelection();
    }
    get acceptedExtensions(): string[] {
        return this.extensions;
    }

    /** Disables the field (also driven by the parent form through `setDisabledState`). */
    @Input() disabled = false;

    /** Helper text shown inside the drop area while the field is disabled. */
    @Input() disabledHint = '';

    /** Emitted with the accepted file whenever a valid selection is made. */
    @Output() fileSelected = new EventEmitter<File>();

    /** Emitted when the current selection is removed. */
    @Output() cleared = new EventEmitter<void>();

    /** Emitted when a chosen or dropped file is refused by the extension filter. */
    @Output() rejected = new EventEmitter<FileDropzoneRejection>();

    public readonly inputId = `app-file-dropzone-${++uniqueDropzoneId}`;
    public selectedFile: File | null = null;
    public errorMessage = '';

    private extensions: string[] = [];
    private onChange: (value: File | null) => void = () => {};
    private onTouched: () => void = () => {};

/* ------------------------------------------------- GETTER / SETTER ------------------------------------------------ */

    public get acceptAttr(): string {
        return this.extensions.join(',');
    }

    public get acceptedLabel(): string {
        return this.extensions.join(', ');
    }

    public get fileName(): string {
        return this.selectedFile?.name ?? '';
    }

    public get describedBy(): string {
        const ids = [`${ this.inputId }-meta`];

        if (this.errorMessage) {
            ids.push(`${ this.inputId }-error`);
        }

        return ids.join(' ');
    }

/* --------------------------------------------- CONTROL VALUE ACCESSOR --------------------------------------------- */

    public writeValue(value: File | null): void {
        this.selectedFile = value ?? null;

        if (this.selectedFile) {
            this.errorMessage = '';
        }
    }

    public registerOnChange(fn: (value: File | null) => void): void {
        this.onChange = fn;
    }

    public registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    public setDisabledState(isDisabled: boolean): void {
        this.disabled = isDisabled;
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onFilesPicked(fileList: FileList | null, input: HTMLInputElement): void {
        this.onTouched();

        const file = fileList?.item(0) ?? null;

        // Reset the native input so the same file can be picked again after a removal or rejection.
        input.value = '';

        if (!file) {
            return;
        }

        if (!this.isExtensionAllowed(file)) {
            this.errorMessage = this.buildRejectionMessage();
            this.selectedFile = null;
            this.onChange(null);
            this.rejected.emit({ file, reason: this.errorMessage });
            return;
        }

        this.errorMessage = '';
        this.selectedFile = file;
        this.onChange(file);
        this.fileSelected.emit(file);
    }

    public clear(): void {
        if (!this.selectedFile) {
            return;
        }

        this.selectedFile = null;
        this.errorMessage = '';
        this.onChange(null);
        this.onTouched();
        this.cleared.emit();
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private normalizeExtensions(value: string | string[] | null | undefined): string[] {
        if (!value) {
            return [];
        }

        const raw = Array.isArray(value) ? value : value.split(/[\s,]+/);
        const seen = new Set<string>();
        const result: string[] = [];

        for (const item of raw) {
            const trimmed = item.trim().toLowerCase().replace(/^\.+/, '');

            if (!trimmed || seen.has(trimmed)) {
                continue;
            }

            seen.add(trimmed);
            result.push(`.${ trimmed }`);
        }

        return result;
    }

    private isExtensionAllowed(file: File): boolean {
        if (this.extensions.length === 0) {
            return true;
        }

        const name = file.name.toLowerCase();
        return this.extensions.some(ext => name.endsWith(ext));
    }

    /** Drops the current selection if a changed extension list no longer allows it. */
    private revalidateSelection(): void {
        if (this.selectedFile && !this.isExtensionAllowed(this.selectedFile)) {
            this.selectedFile = null;
            this.errorMessage = '';
            this.onChange(null);
            this.cleared.emit();
        }
    }

    private buildRejectionMessage(): string {
        const accepted = this.acceptedLabel || 'the required format';
        return `Unsupported file type. Please choose a ${ accepted } file.`;
    }
}
