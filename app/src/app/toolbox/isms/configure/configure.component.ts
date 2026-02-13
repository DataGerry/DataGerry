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
import { Component, OnInit, ViewChild, ChangeDetectorRef, ElementRef, AfterViewInit } from '@angular/core';
import { WizardComponent } from '@rg-software/angular-archwizard';
import { IsmsConfig } from '../models/isms-config.model';
import { ISMSService } from '../services/isms.service';
import { IsmsConfigValidation } from '../models/isms-config-validation.model';
import { RiskCalculationComponent } from './steps/risk-calculation/risk-calculation.component';

@Component({
    selector: 'app-isms-configure',
    templateUrl: './configure.component.html',
    styleUrls: ['./configure.component.scss'],
    standalone: false
})
export class ConfigureComponent implements OnInit, AfterViewInit {
  @ViewChild('wizard') wizard: WizardComponent;
  @ViewChild(RiskCalculationComponent) riskCalculationComponent: RiskCalculationComponent;


  public ismsConfig: IsmsConfig;
  public totalSteps: number = 6;
  public riskClassesCount: number = 0;
  public likelihoodCount: number = 0;
  public impactCount: number = 0;
  public impactCategoriesCount: number = 0;
  public allowFreeNavigation: boolean = true;

  public validationStatus: IsmsConfigValidation = {
    impact_categories: true,
    impacts: true,
    likelihoods: true,
    risk_classes: true,
    risk_matrix: true
  };

  /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */


  constructor(
    private ismsService: ISMSService,
    private elRef: ElementRef
  ) {
    this.ismsConfig = {
      riskClasses: [],
      likelihoodEntries: [],
      impactEntries: [],
      impactCategories: [],
      protectionGoals: [],
      riskMatrix: null
    };
  }


  ngOnInit(): void {
    this.ismsService.getIsmsValidationStatus().subscribe((validationStatus: IsmsConfigValidation) => {
      this.validationStatus = validationStatus;
      this.updateStepIndicatorColors(); // Update colors on page load
    });
  }


  ngAfterViewInit(): void {
    if (!this.wizard) {
      return;
    }
  }

  /* --------------------------------------------------- STEP NAVIGATION AND VALIDATION --------------------------------------------------- */
  /**
 * Validates the current step based on the number of items.
 */
  isStepValid(): boolean {
    if (!this.wizard) {
      return false;
    }

    switch (this.wizard.currentStepIndex) {
      case 0: // Risk Classes
        return this.riskClassesCount >= 3;
      case 1: // Likelihood
        return this.likelihoodCount >= 3;
      case 2: // Impact
        return this.impactCount >= 3;
      case 3: // Impact Categories
        return this.impactCategoriesCount >= 1;
      case 4: // Protection Goals
        return true; // Always valid
      default:
        return true;
    }
  }

  /**
   * Updates the step-indicator color based on validation status.
   */
  updateStepIndicatorColors(): void {
    const steps = this.elRef.nativeElement.querySelectorAll('.steps-indicator li');
    steps.forEach((step: HTMLElement, index: number) => {
      let isValid = false;

      switch (index) {
        case 0: // Risk Classes
          isValid = this.validationStatus.risk_classes;
          break;
        case 1: // Likelihood
          isValid = this.validationStatus.likelihoods;
          break;
        case 2: // Impact
          isValid = this.validationStatus.impacts;
          break;
        case 3: // Impact Categories
          isValid = this.validationStatus.impact_categories;
          break;
        case 4: // Protection Goals
          isValid = true; // Always green
          break;
        case 5: // Risk Calculation
          isValid = this.validationStatus.risk_matrix;
          break;
        default:
          isValid = true;
      }

      if (isValid) {
        step.classList.add('valid-step');
        step.classList.remove('invalid-step');
      } else {
        step.classList.add('invalid-step');
        step.classList.remove('valid-step');
      }

      // Highlight the current step
      if (index === this.wizard.currentStepIndex) {
        step.classList.add('current');
      } else {
        step.classList.remove('current');
      }

      if (index === 3 && !this.validationStatus.impacts) {
        step.setAttribute(
          'title',
          'Cannot enter Impact Categories because Impact step is not valid yet.'
        );
      } else {
        // Remove any tooltip if conditions are satisfied
        step.removeAttribute('title');
      }
    });
  }

  /**
  * Navigates to the next step if the current step is valid.
  */
  nextStep(): void {
    this.ismsService.getIsmsValidationStatus().subscribe((validationStatus: IsmsConfigValidation) => {
      this.validationStatus = validationStatus;
      if (this.isStepValid()) {
        const nextIndex = this.wizard.currentStepIndex + 1;
        if (nextIndex < this.totalSteps) {
          this.wizard.goToStep(nextIndex);
        }
      }
      this.updateStepIndicatorColors(); // Update colors after navigation
    });
  }


  /**
   * Navigates to the previous step.
   */
  previousStep(): void {
    this.ismsService.getIsmsValidationStatus().subscribe((validationStatus: IsmsConfigValidation) => {
      this.validationStatus = validationStatus;
      const prevIndex = this.wizard.currentStepIndex - 1;
      if (prevIndex >= 0) {
        this.wizard.goToStep(prevIndex);
      }
      this.updateStepIndicatorColors(); // Update colors after navigation
    });
  }


  /**
   * Fetches the validation status and updates the step indicators.
   */
  private updateValidationStatusAndIndicators(): void {
    this.ismsService.getIsmsValidationStatus().subscribe((validationStatus: IsmsConfigValidation) => {
      this.validationStatus = validationStatus;
      this.updateStepIndicatorColors();
    });
  }

  /**
   * Save configurations by calling the saveMatrix() method of RiskCalculationComponent.
   */
  public onSaveConfigurations(): void {
    if (this.riskCalculationComponent) {
      this.riskCalculationComponent.saveMatrix();
    }
  }

  /* --------------------------------------------------- CONFIGURATION CHANGE HANDLERS --------------------------------------------------- */

  public onConfigChange(updatedConfig: IsmsConfig): void {
    this.ismsConfig = updatedConfig;
    this.updateStepIndicatorColors();
  }

  public onRiskClassesCountChange(count: number): void {
    this.riskClassesCount = count;
    this.updateValidationStatusAndIndicators();
  }

  public onLikelihoodCountChange(count: number): void {
    this.likelihoodCount = count;
    this.updateValidationStatusAndIndicators();
  }

  public onImpactCountChange(count: number): void {
    this.impactCount = count;
    this.updateValidationStatusAndIndicators();
  }

  public onImpactCategoriesCountChange(count: number): void {
    this.impactCategoriesCount = count;
    this.updateValidationStatusAndIndicators();
  }

}