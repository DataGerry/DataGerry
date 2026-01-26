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
import { Component, Input, OnInit } from '@angular/core';
import { FormBuilder, FormGroup, Validators } from '@angular/forms';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

type CronMode = 'manual' | 'generate';
type CronFrequency = 'everyMinutes' | 'hourly' | 'daily' | 'weekly' | 'monthly';

@Component({
  selector: 'app-cron-expression-modal',
  templateUrl: './cron-expression-modal.component.html',
  styleUrls: ['./cron-expression-modal.component.scss'],
  standalone: false
})
export class CronExpressionModalComponent implements OnInit {
  @Input() currentCron = '';
  @Input() automationName = '';

  form: FormGroup;
  frequencyOptions = [
    { label: 'Every N minutes', value: 'everyMinutes' },
    { label: 'Hourly at minute', value: 'hourly' },
    { label: 'Daily at time', value: 'daily' },
    { label: 'Weekly on day', value: 'weekly' },
    { label: 'Monthly on day', value: 'monthly' }
  ];
  dayOfWeekOptions = [
    { label: 'Monday', value: 'MON' },
    { label: 'Tuesday', value: 'TUE' },
    { label: 'Wednesday', value: 'WED' },
    { label: 'Thursday', value: 'THU' },
    { label: 'Friday', value: 'FRI' },
    { label: 'Saturday', value: 'SAT' },
    { label: 'Sunday', value: 'SUN' }
  ];

  constructor(private fb: FormBuilder, public activeModal: NgbActiveModal) {
    this.form = this.fb.group({
      cronExp: ['', Validators.required],
      mode: ['manual' as CronMode],
      frequency: ['daily' as CronFrequency],
      interval: [5, Validators.min(1)],
      minute: [0, [Validators.min(0), Validators.max(59)]],
      hour: [0, [Validators.min(0), Validators.max(23)]],
      dayOfWeek: ['MON'],
      dayOfMonth: [1, [Validators.min(1), Validators.max(31)]]
    });
  }

  ngOnInit(): void {
    this.form.patchValue({ cronExp: this.currentCron || '' });
  }

  get mode(): CronMode {
    return this.form.get('mode')?.value as CronMode;
  }

  onSubmit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    this.activeModal.close(this.form.get('cronExp')?.value);
  }

  onCancel(): void {
    this.activeModal.dismiss('cancel');
  }

  generateCron(): void {
    const frequency = this.form.get('frequency')?.value as CronFrequency;
    const interval = this.normalizeNumber(this.form.get('interval')?.value, 1, 60, 5);
    const minute = this.normalizeNumber(this.form.get('minute')?.value, 0, 59, 0);
    const hour = this.normalizeNumber(this.form.get('hour')?.value, 0, 23, 0);
    const dayOfWeek = this.form.get('dayOfWeek')?.value || 'MON';
    const dayOfMonth = this.normalizeNumber(this.form.get('dayOfMonth')?.value, 1, 31, 1);

    let cronExp = '0 0 * * * ?';

    switch (frequency) {
      case 'everyMinutes':
        cronExp = `0 */${interval} * * * ?`;
        break;
      case 'hourly':
        cronExp = `0 ${minute} * * * ?`;
        break;
      case 'daily':
        cronExp = `0 ${minute} ${hour} * * ?`;
        break;
      case 'weekly':
        cronExp = `0 ${minute} ${hour} ? * ${dayOfWeek}`;
        break;
      case 'monthly':
        cronExp = `0 ${minute} ${hour} ${dayOfMonth} * ?`;
        break;
    }

    this.form.patchValue({ cronExp, mode: 'manual' as CronMode });
  }

  private normalizeNumber(value: any, min: number, max: number, fallback: number): number {
    const num = Number(value);
    if (Number.isNaN(num)) {
      return fallback;
    }
    return Math.min(max, Math.max(min, num));
  }
}
