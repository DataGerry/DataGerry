import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { LoadingPopupComponent } from './components/loading-popup/loading-popup.component';
import { NgSelectModule } from '@ng-select/ng-select';
import { ObjectSelectorComponent } from './components/object_selector/object-selector.component';
import { FormsModule } from '@angular/forms';
import { WarningAlertComponent } from './components/warning-message/warning-alert.component';
import { ExtendableOptionManagerComponent } from './components/extendable_option_manager/extendable-option-manager.component';
import { FormInputComponent } from './components/base/input/form-input.component';
import { FormTextareaComponent } from './components/base/textarea/form-textarea.component';
import { ButtonComponent } from './components/base/button/app-button.component';
import { CheckboxComponent } from './components/base/checkbox/checkbox.component';
import { RadioComponent } from './components/base/radio/radio.component';
import { SelectComponent } from './components/base/select/select.component';
import { SliderComponent } from './components/base/slider/slider.component';
import { FormDateComponent } from './components/base/date/form-date.component';
import { ProgressBarComponent } from './components/base/progress-bar/progress-bar.component';
import { CoreDeleteConfirmationModalComponent } from './components/dialog/delete-dialog/core-delete-confirmation-modal.component';
import { CoreWarningModalComponent } from './components/dialog/core-warning-modal/core-warning-modal.component';
import { AppUsageBarComponent } from './components/usage-bar/app-usage-bar.component';
import { CoreConfirmationModalComponent } from './components/dialog/confirmation/core-confirmation-modal.component';

@NgModule({
  declarations: [
    LoadingPopupComponent,
    ObjectSelectorComponent,
    WarningAlertComponent,
    ExtendableOptionManagerComponent,
    FormInputComponent,
    FormTextareaComponent,
    ButtonComponent,
    CheckboxComponent,
    RadioComponent,
    SelectComponent,
    SliderComponent,
    FormDateComponent,
    ProgressBarComponent,
    CoreDeleteConfirmationModalComponent,
    CoreWarningModalComponent,
    AppUsageBarComponent,
    CoreConfirmationModalComponent
  ],
  imports: [
    CommonModule,
    NgSelectModule,
    FormsModule  ],
  exports: [
    LoadingPopupComponent,
    ObjectSelectorComponent,
    WarningAlertComponent,
    ExtendableOptionManagerComponent,
    FormInputComponent,
    FormTextareaComponent,
    ButtonComponent,
    CheckboxComponent,
    RadioComponent,
    SelectComponent,
    SliderComponent,
    FormDateComponent,
    ProgressBarComponent,
    CoreDeleteConfirmationModalComponent,
    CoreWarningModalComponent,
    AppUsageBarComponent,
    CoreConfirmationModalComponent
  ]
})
export class CoreModule { }
