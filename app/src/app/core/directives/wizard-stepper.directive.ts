import { Directive, computed, input } from '@angular/core';


export type WizardStepperTone = 'progress' | 'validity';


@Directive({
  selector: 'aw-wizard[dgStepper]',
  standalone: true,
  host: {
    class: 'dg-stepper',
    '[class.dg-stepper--validity]': 'tone() === "validity"',
    '[attr.data-invalid-steps]': 'invalidStepPositions()'
  }
})
export class WizardStepperDirective {
  readonly tone = input<WizardStepperTone>('progress');

  /** 1-based positions of the steps that currently fail validation. */
  readonly invalidSteps = input<readonly number[]>([]);

  readonly invalidStepPositions = computed(() => this.invalidSteps().join(' ') || null);
}
