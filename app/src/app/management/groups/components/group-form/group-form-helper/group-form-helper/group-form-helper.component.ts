import { Component, Input, OnInit } from '@angular/core';
import { Right } from '../../../../../models/right';
import { UntypedFormGroup } from '@angular/forms';

@Component({
    selector: 'cmdb-group-form-helper',
    templateUrl: './group-form-helper.component.html',
    styleUrls: ['./group-form-helper.component.scss'],
    standalone: false
})
export class GroupFormHelperComponent implements OnInit {

  presetList = [];

  @Input() public rights: Array<Right> = [];

  public rightNames: any[] = [];

  @Input() public form: UntypedFormGroup;

  public minRights: any[] = [];

  constructor() { }

  ngOnInit() {
    this.rights.forEach( right => {
      this.rightNames.push(right.name);
    });
    this.minRights = this.rightNames.filter(right => right.includes('view') && (right.includes('framework') ||
      right.includes('user-management')));
    this.presetList.push({
        name: 'Read-Only',
        value: this.minRights
      },
      {
        name: 'Object-Write',
        value: this.rightNames.filter(right => right.includes('object.add')).concat(this.minRights)
      },
      {
        name: 'Administrator',
        value: this.rightNames.filter(right => right.includes('base.*'))
      }
    );
  }

  public insertSelectedRights(rights) {
    this.form.get('rights').patchValue(rights);
  }
}
