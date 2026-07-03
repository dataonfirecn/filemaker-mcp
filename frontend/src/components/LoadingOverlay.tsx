export type LoadingOverlayProps = {
  loading: boolean;
};

export default function LoadingOverlay({ loading }: LoadingOverlayProps) {
  if (!loading) return null;
  return (
    <div className="loading-overlay">
      <div className="spinner" role="status" aria-live="polite">
        <span className="visually-hidden">加载中...</span>
      </div>
    </div>
  );
}
