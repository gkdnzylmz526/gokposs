import { useState } from "react";
import { Check, Pencil, Trash2, X } from "lucide-react";

export const RowActions = ({ testId, onEdit, onDelete }) => {
  const [confirm, setConfirm] = useState(false);
  if (confirm) {
    return (
      <span className="row-actions">
        <button className="icon-button danger" title="Silmeyi onayla" data-testid={`${testId}-confirm-delete`} onClick={() => { setConfirm(false); onDelete(); }}><Check size={14} /></button>
        <button className="icon-button" title="Vazgeç" data-testid={`${testId}-cancel-delete`} onClick={() => setConfirm(false)}><X size={14} /></button>
      </span>
    );
  }
  return (
    <span className="row-actions">
      <button className="icon-button" title="Düzenle" data-testid={`${testId}-edit`} onClick={onEdit}><Pencil size={14} /></button>
      <button className="icon-button" title="Sil" data-testid={`${testId}-delete`} onClick={() => setConfirm(true)}><Trash2 size={14} /></button>
    </span>
  );
};
