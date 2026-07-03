export type GenerateDialogProps = {
  open: boolean;
  qty: string;
  loading: boolean;
  onQtyChange: (value: string) => void;
  onGenerate: () => void;
  onCancel: () => void;
};

export default function GenerateDialog({
  open,
  qty,
  loading,
  onQtyChange,
  onGenerate,
  onCancel
}: GenerateDialogProps) {
  if (!open) return null;

  return (
    <div className="modal-backdrop" role="presentation">
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="generate-title">
        <h2 id="generate-title">生成 BOM 计算单</h2>
        <label htmlFor="generateQty">生成数量</label>
        <input
          id="generateQty"
          type="number"
          min="1"
          step="1"
          value={qty}
          onChange={(event) => onQtyChange(event.target.value)}
          autoFocus
        />
        <div className="modal-actions">
          <button className="btn" onClick={onCancel} disabled={loading}>
            取消
          </button>
          <button className="btn primary" onClick={onGenerate} disabled={loading}>
            生成
          </button>
        </div>
      </div>
    </div>
  );
}
