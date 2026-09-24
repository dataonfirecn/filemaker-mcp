import { useEffect, useId, useRef } from 'react';
import type { ReactNode } from 'react';
import './modal.css';

export function Modal({ title, children, footer, onClose }: {
  title: string; children: ReactNode; footer: ReactNode; onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);
  return <dialog ref={dialog} className="ui-modal" aria-labelledby={titleId}
    onCancel={event => { event.preventDefault(); onClose(); }}>
    <h2 id={titleId}>{title}</h2>
    <div className="ui-modal-body">{children}</div>
    <footer className="ui-modal-footer">{footer}</footer>
  </dialog>;
}
