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
import { Component, Input, Output, EventEmitter, OnChanges, SimpleChanges } from '@angular/core';

@Component({
    selector: 'app-form-slider',
    templateUrl: './slider.component.html',
    styleUrls: ['./slider.component.scss'],
    standalone: false
})
export class SliderComponent implements OnChanges {
  @Input() items: any[] = [];
  @Input() allowNotRated = true;
  @Input() selectedId: number | null = null;
  @Input() showChosenText = false;
  @Input() showLabels = true; 
  @Input() primaryColor = '#4171f6'; 
  @Input() disabled = false;

  public sliderOptions: Array<{ id: number | null; label: string }> = [];
  public sliderValue = 0;
  public sliderSteps: number[] = [];

  @Output() selectedIdChange = new EventEmitter<number | null>();

  ngOnChanges(changes: SimpleChanges): void {
    this.buildSliderOptions();
    this.syncSliderValue();
    this.calculateSliderSteps();
  }

  private buildSliderOptions(): void {
    this.sliderOptions = [];
    
    if (this.allowNotRated) {
      this.sliderOptions.push({ id: null, label: 'Not rated' });
    }
    
    for (const item of this.items) {
      this.sliderOptions.push({
        id: item.public_id,
        label: item.name || `Item ${item.public_id}`
      });
    }
  }

  private syncSliderValue(): void {
    const idx = this.sliderOptions.findIndex(o => o.id === this.selectedId);
    this.sliderValue = idx >= 0 ? idx : 0;
  }

  private calculateSliderSteps(): void {
    // Create an array of step positions for tick marks
    this.sliderSteps = Array.from({ length: this.sliderOptions.length }, (_, i) => i);
  }

  onSliderChange(value: string): void {
    const idx = +value;
    const option = this.sliderOptions[idx];
    this.sliderValue = idx;
    this.selectedIdChange.emit(option ? option.id : null);
  }

  getTrackFillWidth(): string {
    // Calculate percentage width for the filled part of track
    if (this.sliderSteps.length <= 1) return '0%';
    
    const percentage = (this.sliderValue / (this.sliderSteps.length - 1)) * 100;
    return `${percentage}%`;
  }
}