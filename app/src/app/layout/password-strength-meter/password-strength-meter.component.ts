import { Component, EventEmitter, Input, OnChanges, Output, SimpleChanges } from '@angular/core';
import { PasswordStrengthMeterService } from './password-strength-meter.service';

@Component({
    selector: 'password-strength-meter',
    templateUrl: './password-strength-meter.component.html',
    styleUrls: ['./password-strength-meter.component.scss'],
    providers: [PasswordStrengthMeterService],
    standalone: false
})
export class PasswordStrengthMeterComponent implements OnChanges {

  @Input() password: string;

  @Input() minPasswordLength = 8;

  @Input() enableFeedback = false;

  @Input() colors: string[] = [];

  @Output() strengthChange = new EventEmitter<number>();

  public passwordStrength: number = null;

  public feedback: { suggestions: string[]; warning: string } = null;

  private prevPasswordStrength = null;

  private defaultColours = [
    'darkred',
    'orangered',
    'orange',
    'yellowgreen',
    'green'
  ];

  constructor(
    private passwordStrengthMeterService: PasswordStrengthMeterService
  ) {
  }

  public ngOnChanges(changes: SimpleChanges) {
    if (changes.password) {
      this.calculatePasswordStrength();
    }
  }

  private calculatePasswordStrength() {
    if (!this.password) {
      this.passwordStrength = null;
    } else if (this.password && this.password.length < this.minPasswordLength) {
      this.passwordStrength = 0;
    } else {
      if (this.enableFeedback) {
        const result = this.passwordStrengthMeterService.scoreWithFeedback(
          this.password
        );
        this.passwordStrength = result.score;
        this.feedback = result.feedback;
      } else {
        this.passwordStrength = this.passwordStrengthMeterService.score(
          this.password
        );
        this.feedback = null;
      }
    }

    if (this.prevPasswordStrength !== this.passwordStrength) {
      this.strengthChange.emit(this.passwordStrength);
      this.prevPasswordStrength = this.passwordStrength;
    }
  }

  public getMeterFillColor(strength) {
    if (!strength || strength < 0 || strength > 5) {
      return this.colors[0] ? this.colors[0] : this.defaultColours[0];
    }

    return this.colors[strength]
      ? this.colors[strength]
      : this.defaultColours[strength];
  }
}
