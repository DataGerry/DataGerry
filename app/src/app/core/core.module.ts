import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatTreeModule } from '@angular/material/tree';
import { LoadingPopupComponent } from './components/loading-popup/loading-popup.component';
import { NgSelectModule } from '@ng-select/ng-select';
import { ObjectSelectorComponent } from './components/object_selector/object-selector.component';
import { LocationTreeSelectComponent } from './components/location-tree-select/location-tree-select.component';
import { LocationTreePickerModalComponent } from './components/location-tree-select/location-tree-picker-modal.component';
import { LocationTreeOrganizerModalComponent } from './components/location-tree-organizer/location-tree-organizer-modal.component';
import { DgModalComponent } from './components/modal/dg-modal.component';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';
import { WarningAlertComponent } from './components/warning-message/warning-alert.component';
import { ExtendableOptionManagerComponent } from './components/extendable_option_manager/extendable-option-manager.component';
import { FormInputComponent } from './components/base/input/form-input.component';
import { FormTextareaComponent } from './components/base/textarea/form-textarea.component';
import { ButtonComponent } from './components/base/button/app-button.component';
import { CheckboxComponent } from './components/base/checkbox/checkbox.component';
import { RadioComponent } from './components/base/radio/radio.component';
import { SelectComponent } from './components/base/select/select.component';
import { FileDropzoneComponent } from './components/base/file-dropzone/file-dropzone.component';
import { SliderComponent } from './components/base/slider/slider.component';
import { ToggleComponent } from './components/base/toggle/toggle.component';
import { FormDateComponent } from './components/base/date/form-date.component';
import { ProgressBarComponent } from './components/base/progress-bar/progress-bar.component';
import { CoreDeleteConfirmationModalComponent } from './components/dialog/delete-dialog/core-delete-confirmation-modal.component';
import { CoreWarningModalComponent } from './components/dialog/core-warning-modal/core-warning-modal.component';
import { AppUsageBarComponent } from './components/usage-bar/app-usage-bar.component';
import { CoreConfirmationModalComponent } from './components/dialog/confirmation/core-confirmation-modal.component';
import { PremiumFeatureModalComponent } from './components/dialog/premium-feature-modal/premium-feature-modal.component';
import { HorizontalResizeDirective } from './directives/horizontal-resize.directive';
import { FullscreenDirective } from './directives/fullscreen.directive';
import { PremiumFeatureDirective } from './directives/premium-feature.directive';
import { PremiumGateDirective } from './directives/premium-gate.directive';
import { WizardStepperDirective } from './directives/wizard-stepper.directive';
import { PremiumLockedComponent } from './components/premium-locked/premium-locked.component';
import { CompactNumberPipe } from './pipes/compact-number.pipe';

@NgModule({
  declarations: [
    LoadingPopupComponent,
    ObjectSelectorComponent,
    LocationTreeSelectComponent,
    LocationTreePickerModalComponent,
    LocationTreeOrganizerModalComponent,
    WarningAlertComponent,
    ExtendableOptionManagerComponent,
    FormInputComponent,
    FormTextareaComponent,
    ButtonComponent,
    CheckboxComponent,
    RadioComponent,
    SelectComponent,
    FileDropzoneComponent,
    SliderComponent,
    ToggleComponent,
    FormDateComponent,
    ProgressBarComponent,
    CoreDeleteConfirmationModalComponent,
    CoreWarningModalComponent,
    AppUsageBarComponent,
    CoreConfirmationModalComponent,
    PremiumFeatureModalComponent,
    CompactNumberPipe
  ],
  imports: [
    CommonModule,
    NgSelectModule,
    MatTreeModule,
    FormsModule,
    ReactiveFormsModule,
    HorizontalResizeDirective,
    FullscreenDirective,
    PremiumFeatureDirective,
    PremiumGateDirective,
    WizardStepperDirective,
    PremiumLockedComponent,
    DgModalComponent
  ],
  exports: [
    LoadingPopupComponent,
    ObjectSelectorComponent,
    LocationTreeSelectComponent,
    WarningAlertComponent,
    ExtendableOptionManagerComponent,
    FormInputComponent,
    FormTextareaComponent,
    ButtonComponent,
    CheckboxComponent,
    RadioComponent,
    SelectComponent,
    FileDropzoneComponent,
    SliderComponent,
    ToggleComponent,
    FormDateComponent,
    ProgressBarComponent,
    CoreDeleteConfirmationModalComponent,
    CoreWarningModalComponent,
    AppUsageBarComponent,
    CoreConfirmationModalComponent,
    PremiumFeatureModalComponent,
    HorizontalResizeDirective,
    FullscreenDirective,
    PremiumFeatureDirective,
    PremiumGateDirective,
    WizardStepperDirective,
    PremiumLockedComponent,
    CompactNumberPipe,
    DgModalComponent
  ]
})
export class CoreModule { }
