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
import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
/* ------------------------------------------------------------------------------------------------------------------ */

/** A single step descriptor rendered by the stepper. */
export interface WizardStep {
  title: string;
  icon: string;
}

/** Compact vertical stepper showing completed / active / upcoming states. */
@Component({
  selector: 'cmdb-license-wizard-stepper',
  templateUrl: './license-wizard-stepper.component.html',
  styleUrls: ['./license-wizard-stepper.component.scss'],
  standalone: false,
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class LicenseWizardStepperComponent {
  @Input() steps: WizardStep[] = [];
  @Input() current = 0;

  @Output() stepSelected = new EventEmitter<number>();

  /* --------------------------------------------------- FUNCTIONS --------------------------------------------------- */

  public isCompleted(index: number): boolean {
    return index < this.current;
  }

  public isActive(index: number): boolean {
    return index === this.current;
  }

  /** Only already-reached steps are navigable, so users can review but not skip ahead. */
  public onSelect(index: number): void {
    if (index <= this.current) {
      this.stepSelected.emit(index);
    }
  }
}
