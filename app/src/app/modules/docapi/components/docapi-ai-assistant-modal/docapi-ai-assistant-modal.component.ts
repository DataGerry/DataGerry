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
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';
import { firstValueFrom } from 'rxjs';

import { DocapiAiAssistantService } from '../../services/docapi-ai-assistant.service';
/* ------------------------------------------------------------------------------------------------------------------ */

export type PreviewMode = 'preview' | 'source';
export type AiAssistantStep = 1 | 2;

interface AiAssistantStepMeta {
    readonly id: AiAssistantStep;
    readonly eyebrow: string;
    readonly title: string;
    readonly icon: string;
}

@Component({
    selector: 'cmdb-docapi-ai-assistant-modal',
    templateUrl: './docapi-ai-assistant-modal.component.html',
    styleUrls: ['./docapi-ai-assistant-modal.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: false
})
export class DocapiAiAssistantModalComponent {
    public readonly promptForm = new UntypedFormGroup({
        prompt: new UntypedFormControl('', [Validators.required, Validators.maxLength(4000)])
    });

    public readonly steps: readonly AiAssistantStepMeta[] = [
        { id: 1, eyebrow: 'Step 1', title: 'Describe Content', icon: 'fa-solid fa-pen-to-square' },
        { id: 2, eyebrow: 'Step 2', title: 'Generate & Insert', icon: 'fa-solid fa-wand-magic-sparkles' }
    ];

    public readonly examplePrompts: readonly string[] = [
        'Create a server overview including hostname, IP, OS and owner.',
        'Generate a CI documentation template for a network device.',
        'Document an application with version, environment and dependencies.'
    ];

    public readonly currentStep = signal<AiAssistantStep>(1);
    public readonly isGenerating = signal(false);
    public readonly generatedHtml = signal('');
    public readonly requestError = signal('');
    public readonly previewMode = signal<PreviewMode>('preview');

    public readonly hasGeneratedContent = computed(
        () => !!this.generatedHtml() && !this.isGenerating() && !this.requestError()
    );

    private lastGeneratedPrompt = '';

    public readonly activeModal = inject(NgbActiveModal);
    private readonly aiAssistantService = inject(DocapiAiAssistantService);


    public get promptControl(): UntypedFormControl {
        return this.promptForm.get('prompt') as UntypedFormControl;
    }

    public get canContinueFromDescribe(): boolean {
        return this.promptForm.valid;
    }


    /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public proceedToReview(): void {
        if (!this.canContinueFromDescribe) {
            this.promptForm.markAllAsTouched();
            return;
        }

        this.currentStep.set(2);

        if (this.isGenerating()) {
            return;
        }

        const prompt = String(this.promptControl.value || '').trim();
        if (!this.generatedHtml() || prompt !== this.lastGeneratedPrompt) {
            void this.generate();
        }
    }


    public previousStep(): void {
        if (this.currentStep() > 1) {
            this.currentStep.set((this.currentStep() - 1) as AiAssistantStep);
        }
    }


    public goToStep(step: AiAssistantStep): void {
        if (step < this.currentStep()) {
            this.currentStep.set(step);
        }
    }


    public applyExamplePrompt(example: string): void {
        this.promptControl.setValue(example);
        this.promptControl.markAsDirty();
    }


    public setPreviewMode(mode: PreviewMode): void {
        this.previewMode.set(mode);
    }


    public cancel(): void {
        this.activeModal.dismiss();
    }


    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public async generate(): Promise<void> {
        if (this.promptForm.invalid || this.isGenerating()) {
            this.promptForm.markAllAsTouched();
            return;
        }

        this.requestError.set('');
        this.isGenerating.set(true);

        try {
            const prompt = String(this.promptControl.value || '').trim();
            this.lastGeneratedPrompt = prompt;
            const responseHtml = await firstValueFrom(this.aiAssistantService.generateHtml(prompt));
            this.generatedHtml.set(responseHtml || '');

            if (!this.generatedHtml()) {
                this.requestError.set('No HTML response was returned by the AI Assistant.');
            }
        } catch {
            this.requestError.set('Failed to generate HTML. Please try again.');
        } finally {
            this.isGenerating.set(false);
        }
    }


    public insertGeneratedHtml(): void {
        const html = this.generatedHtml();
        if (!html) {
            return;
        }

        this.activeModal.close(html);
    }


    public isStepCompleted(step: AiAssistantStep): boolean {
        return step < this.currentStep();
    }


    public isStepCurrent(step: AiAssistantStep): boolean {
        return step === this.currentStep();
    }


    public isStepPending(step: AiAssistantStep): boolean {
        return step > this.currentStep();
    }
}
