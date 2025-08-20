import { Component, OnInit } from '@angular/core';
import { FormGroup, FormControl, Validators } from '@angular/forms';
import { AiAssistantService } from 'src/app/ai-assistant/services/ai-assistant.service';
import { AiAssistantMessage } from '../../models/ai-suggestion.model';
import { Router } from '@angular/router';

@Component({
    selector: 'cmdb-ai-prompt-page',
    templateUrl: './ai-prompt-page.component.html',
    standalone: false
})
export class AiPromptPageComponent implements OnInit {
  public promptForm!: FormGroup;

  constructor(
    private aiAssistantService: AiAssistantService,
    private router: Router
  ) {}

  ngOnInit(): void {
    this.promptForm = new FormGroup({
      prompt: new FormControl('', Validators.required)
    });
  }

  public submit(): void {
    if (this.promptForm.valid) {
      const message: AiAssistantMessage = { message: this.promptForm.get('prompt')?.value };
      this.aiAssistantService.postMessage(message).subscribe({
        next: (response) => {
          // console.log('AI response:', response);
        },
        error: (error) => {
          console.error('Error posting AI message:', error);
        }
      });
    }
  }

  public cancel(): void {
    this.router.navigate(['/']);
  }
}
