import { Component, Input } from '@angular/core';

@Component({
    selector: 'app-import-instructions',
    templateUrl: './import-instructions.component.html',
    standalone: false
})
export class ImportInstructionsComponent {
  @Input() title!: string;
  @Input() description!: string;
  @Input() headers: { header: string; type: string; required: string; description: string }[] = [];
  @Input() mappings?: string;
  @Input() duplicates?: string;
  @Input() exampleCsv?: string;
  @Input() notes?: string;
}
