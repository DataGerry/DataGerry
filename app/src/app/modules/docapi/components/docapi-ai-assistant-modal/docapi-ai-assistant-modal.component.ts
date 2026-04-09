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
import { Component } from '@angular/core';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';
import { firstValueFrom } from 'rxjs';

import { DocapiAiAssistantService } from '../../services/docapi-ai-assistant.service';
/* ------------------------------------------------------------------------------------------------------------------ */

export type PreviewMode = 'preview' | 'source';

@Component({
    selector: 'cmdb-docapi-ai-assistant-modal',
    templateUrl: './docapi-ai-assistant-modal.component.html',
    styleUrls: ['./docapi-ai-assistant-modal.component.scss'],
    standalone: false
})
export class DocapiAiAssistantModalComponent {
    public readonly promptForm = new UntypedFormGroup({
        prompt: new UntypedFormControl('', [Validators.required, Validators.maxLength(4000)])
    });

    public generatedHtml = '';
    public requestError = '';
    public isGenerating = false;
    public previewMode: PreviewMode = 'preview';

    constructor(
        public readonly activeModal: NgbActiveModal,
        private readonly aiAssistantService: DocapiAiAssistantService
    ) {
    }


    public get promptControl(): UntypedFormControl {
        return this.promptForm.get('prompt') as UntypedFormControl;
    }


    public async generate(): Promise<void> {
        if (this.promptForm.invalid || this.isGenerating) {
            this.promptForm.markAllAsTouched();
            return;
        }

        this.requestError = '';
        this.isGenerating = true;

        try {
            const prompt = String(this.promptControl.value || '').trim();
            const responseHtml = await firstValueFrom(this.aiAssistantService.generateHtml(prompt));
            this.generatedHtml = responseHtml || '';

            if (!this.generatedHtml) {
                this.requestError = 'No HTML response was returned by the AI Assistant.';
            }
        } catch {
            this.requestError = 'Failed to generate HTML. Please try again.';
        } finally {
            this.isGenerating = false;
        }
    }


    public setPreviewMode(mode: PreviewMode): void {
        this.previewMode = mode;
    }


    public insertGeneratedHtml(): void {
        if (!this.generatedHtml) {
            return;
        }

        this.activeModal.close(this.generatedHtml);
    }


    public cancel(): void {
        this.activeModal.dismiss();
    }
}