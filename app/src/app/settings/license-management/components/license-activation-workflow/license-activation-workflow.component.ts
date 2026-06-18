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
import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  OnChanges,
  Output,
  SimpleChanges
} from '@angular/core';

import { LicenseEdition, LicenseEntitlement, LicenseFeature } from '../../models/license.model';
import { WizardStep } from '../license-wizard-stepper/license-wizard-stepper.component';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
  selector: 'cmdb-license-activation-workflow',
  templateUrl: './license-activation-workflow.component.html',
  styleUrls: ['./license-activation-workflow.component.scss'],
  standalone: false,
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class LicenseActivationWorkflowComponent implements OnChanges {
  @Input() generated = false;
  @Input() importing = false;
  @Input() activatedEntitlement: LicenseEntitlement | null = null;
  @Input() features: LicenseFeature[] = [];

  @Output() generate = new EventEmitter<void>();
  @Output() activate = new EventEmitter<File>();
  @Output() finished = new EventEmitter<void>();

  public readonly LicenseEdition = LicenseEdition;
  public readonly stepGenerate = 0;
  public readonly stepPortal = 1;
  public readonly stepImport = 2;
  public readonly stepComplete = 3;
  public readonly steps: WizardStep[] = [
    { title: 'Generate request', icon: 'fas fa-file-export' },
    { title: 'Service portal', icon: 'fas fa-arrow-up-from-bracket' },
    { title: 'Import license', icon: 'fas fa-file-import' },
    { title: 'Complete', icon: 'fas fa-circle-check' }
  ];

  public currentStep = this.stepGenerate;
  public selectedFile: File | null = null;

  /* -------------------------------------------------- LIFE CYCLE -------------------------------------------------- */

  public ngOnChanges(changes: SimpleChanges): void {
    // Jump to the completion step once the backend confirms activation.
    if (changes['activatedEntitlement'] && this.activatedEntitlement) {
      this.currentStep = this.stepComplete;
    }
  }

  /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

  public onStepSelected(index: number): void {
    this.currentStep = index;
  }

  public onNext(): void {
    if (this.currentStep < this.stepComplete) {
      this.currentStep++;
    }
  }

  public onBack(): void {
    if (this.currentStep > this.stepGenerate) {
      this.currentStep--;
    }
  }

  public onGenerate(): void {
    this.generate.emit();
  }

  public onFileSelected(file: File): void {
    this.selectedFile = file;
  }

  public onClearFile(): void {
    this.selectedFile = null;
  }

  public onActivate(): void {
    if (this.selectedFile) {
      this.activate.emit(this.selectedFile);
    }
  }

  public onFinish(): void {
    this.finished.emit();
  }

  /* --------------------------------------------------- FUNCTIONS --------------------------------------------------- */

  /** Human-readable file size for the selected-file card. */
  public fileSize(bytes: number): string {
    if (bytes < 1024) {
      return `${bytes} B`;
    }

    if (bytes < 1024 * 1024) {
      return `${(bytes / 1024).toFixed(1)} KB`;
    }

    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
}
