export type StepIndicatorProps = {
  currentStep: 1 | 2 | 3;
};

const steps = [
  { label: "读取产品 BOM", description: "只读展示 FileMaker 数据" },
  { label: "待确认计算结果", description: "编辑数量或替换零件" },
  { label: "写入本地单据", description: "确认后保存到 PostgreSQL" }
];

export default function StepIndicator({ currentStep }: StepIndicatorProps) {
  return (
    <nav className="step-indicator" aria-label="业务流程">
      <ol>
        {steps.map((step, index) => {
          const stepNumber = index + 1;
          const isActive = stepNumber === currentStep;
          const isCompleted = stepNumber < currentStep;
          return (
            <li
              key={stepNumber}
              className={[
                "step-item",
                isActive ? "active" : "",
                isCompleted ? "completed" : ""
              ].join(" ")}
              aria-current={isActive ? "step" : undefined}
            >
              <span className="step-badge">{stepNumber}</span>
              <div className="step-body">
                <span className="step-title">{step.label}</span>
                <span className="step-desc">{step.description}</span>
              </div>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
