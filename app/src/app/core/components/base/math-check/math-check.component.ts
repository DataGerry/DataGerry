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
import { ChangeDetectionStrategy, Component, computed, output, signal } from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { FormControl } from '@angular/forms';

/** Asks a small random sum before a risky action; not a security control. */
@Component({
  selector: 'app-math-check',
  templateUrl: './math-check.component.html',
  styleUrls: ['./math-check.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
  standalone: false
})
export class MathCheckComponent {
  public readonly solvedChange = output<boolean>();

  public readonly answerControl = new FormControl('', { nonNullable: true });
  public readonly question = signal('');

  private readonly expectedAnswer = signal('');
  private readonly answer = toSignal(this.answerControl.valueChanges, { initialValue: '' });

  public readonly isSolved = computed(() => this.answer() === this.expectedAnswer());

  /** Flags a wrong answer only once it has as many digits as the right one. */
  public readonly errorMessage = computed(() => {
    const isComplete = this.answer().length >= this.expectedAnswer().length;

    return isComplete && !this.isSolved() ? 'That is not the right answer.' : '';
  });

  /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

  constructor() {
    this.createQuestion();

    this.answerControl.valueChanges.pipe(takeUntilDestroyed()).subscribe(value => {
      this.solvedChange.emit(value === this.expectedAnswer());
    });
  }

  /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

  public onNewQuestion(): void {
    this.createQuestion();
    this.answerControl.reset();
  }

  /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

  private createQuestion(): void {
    const first = this.randomOperand();
    const second = this.randomOperand();

    this.question.set(`What is ${first} + ${second}?`);
    this.expectedAnswer.set(String(first + second));
  }

  private randomOperand(): number {
    return 2 + Math.floor(Math.random() * 9);
  }
}
