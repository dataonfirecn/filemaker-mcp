import { CheckCircle2, X } from "lucide-react";

export type SuccessAlertProps = {
  message: string;
  onClose?: () => void;
};

export default function SuccessAlert({ message, onClose }: SuccessAlertProps) {
  return (
    <div className="alert success">
      <CheckCircle2 size={16} />
      <span>{message}</span>
      {onClose && (
        <button className="alert-close" onClick={onClose} aria-label="关闭">
          <X size={14} />
        </button>
      )}
    </div>
  );
}
