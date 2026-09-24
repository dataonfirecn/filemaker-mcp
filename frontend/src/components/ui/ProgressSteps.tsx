import { Check, CircleAlert, LoaderCircle } from 'lucide-react';
import './progress-steps.css';

export type ProgressStep = { label: string; detail: string; state: 'waiting' | 'active' | 'done' | 'error' };
export function ProgressSteps({ steps }: { steps: ProgressStep[] }) {
  return <ol className="ui-progress-steps" aria-label="保存进度">{steps.map((step, index) =>
    <li key={step.label} data-state={step.state} aria-current={step.state === 'active' ? 'step' : undefined}>
      <span className="ui-progress-node" aria-hidden="true">{step.state === 'done' ? <Check /> : step.state === 'error' ? <CircleAlert /> : step.state === 'active' ? <LoaderCircle /> : index + 1}</span>
      <div><strong>{step.label}</strong><p>{step.detail}</p></div>
    </li>)}</ol>;
}
