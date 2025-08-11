// src/app/shared/components/loading-popup/loading-popup.component.ts
import { Component, Input, OnChanges } from '@angular/core';

@Component({
    selector: 'app-loading-popup',
    templateUrl: './loading-popup.component.html',
    styleUrls: ['./loading-popup.component.scss'],
    standalone: false
})
export class LoadingPopupComponent implements OnChanges {
  @Input() message = 'Creating your object...';
  @Input() isVisible = false;
  @Input() progress = 0;
  
  stages = [
    { label: 'Validating', active: false },
    { label: 'Sending', active: false },
    { label: 'Processing', active: false }
  ];

  ngOnChanges() {
    if(this.isVisible) {
      this.animateStages();
    }
  }

  private animateStages() {
    this.stages.forEach((stage, index) => {
      setTimeout(() => {
        stage.active = true;
        if(index === this.stages.length - 1) {
          setTimeout(() => this.resetStages(), 2000);
        }
      }, index * 1500);
    });
  }

  private resetStages() {
    this.stages.forEach(stage => stage.active = false);
    this.animateStages();
  }
}