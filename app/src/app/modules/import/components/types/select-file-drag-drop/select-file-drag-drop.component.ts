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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { Component, EventEmitter, OnDestroy, Output } from '@angular/core';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';

import { ImportTypeEntry } from '../../../models/import-type.models';
/* ------------------------------------------------------------------------------------------------------------------ */

export interface ParsedTypeFile {
    file: File;
    types: ImportTypeEntry[];
}

@Component({
    selector: 'cmdb-select-file-drag-drop',
    templateUrl: './select-file-drag-drop.component.html',
    styleUrls: ['./select-file-drag-drop.component.scss'],
    standalone: false
})
export class SelectFileDragDropComponent implements OnDestroy {

    /** Emitted once the picked file was read and decoded into a list of types. */
    @Output() public fileParsed = new EventEmitter<ParsedTypeFile>();

    /** Emitted whenever the current selection becomes unusable (removed or not decodable). */
    @Output() public fileCleared = new EventEmitter<void>();

    public readonly fileForm = new UntypedFormGroup({
        file: new UntypedFormControl(null, Validators.required)
    });

    public parsedTypes: ImportTypeEntry[] = [];
    public parseError = '';
    public isParsing = false;

    private readonly fileReader = new FileReader();
    private pendingFile: File | null = null;

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    public constructor() {
        this.fileReader.onload = () => this.decodeFileContent(this.fileReader.result);
        this.fileReader.onerror = () => this.rejectFile('The file could not be read. Please try again.');
    }


    public ngOnDestroy(): void {
        this.abortPendingRead();
    }

/* ------------------------------------------------- GETTER / SETTER ------------------------------------------------ */

    public get canContinue(): boolean {
        return this.parsedTypes.length > 0 && !this.parseError && !this.isParsing;
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onFileSelected(file: File): void {
        this.abortPendingRead();
        this.resetState();
        this.pendingFile = file;
        this.isParsing = true;
        this.fileReader.readAsText(file, 'UTF-8');
    }


    public onFileCleared(): void {
        this.abortPendingRead();
        this.resetState();
        this.fileCleared.emit();
    }


    /** A file refused by the dropzone filter must not leave a previously parsed upload behind. */
    public onFileRejected(): void {
        this.onFileCleared();
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    /** Turns the raw file content into the list of types the following steps work on. */
    private decodeFileContent(content: string | ArrayBuffer | null): void {
        const file = this.pendingFile;

        if (!file || typeof content !== 'string') {
            this.rejectFile('The file could not be read. Please try again.');
            return;
        }

        let decoded: unknown;

        try {
            decoded = JSON.parse(content);
        } catch {
            this.rejectFile('This file is not valid JSON. Please upload a type export created by DATAGerry.');
            return;
        }

        if (!Array.isArray(decoded)) {
            this.rejectFile('The file must contain a JSON list of types.');
            return;
        }

        if (decoded.length === 0) {
            this.rejectFile('The file does not contain any types.');
            return;
        }

        this.isParsing = false;
        this.parsedTypes = decoded as ImportTypeEntry[];
        this.fileParsed.emit({ file, types: this.parsedTypes });
    }


    /** Keeps the file visible in the dropzone but blocks the step until a usable file is picked. */
    private rejectFile(message: string): void {
        this.isParsing = false;
        this.parsedTypes = [];
        this.parseError = message;
        this.fileCleared.emit();
    }


    private resetState(): void {
        this.isParsing = false;
        this.parsedTypes = [];
        this.parseError = '';
        this.pendingFile = null;
    }


    /** Keeps a superseded read from resolving onto the newly picked file. */
    private abortPendingRead(): void {
        if (this.fileReader.readyState === FileReader.LOADING) {
            this.fileReader.abort();
        }
    }
}
