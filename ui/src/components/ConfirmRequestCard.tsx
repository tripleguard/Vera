type ConfirmRequest = {
  confirm_id: string;
  task_id?: string;
  risk?: string;
  reason?: string;
  action_key?: string;
  preview?: string;
};

type Props = {
  request: ConfirmRequest | null;
  isLightMode: boolean;
  onApprove: (id: string) => void;
  onDeny: (id: string) => void;
};

export function ConfirmRequestCard({ request, isLightMode, onApprove, onDeny }: Props) {
  if (!request) return null;

  const risk = (request.risk || 'high').toLowerCase();
  const riskColor = risk === 'critical' ? 'text-red-500' : risk === 'high' ? 'text-amber-500' : 'text-blue-500';

  return (
    <div className={`mb-3 rounded-xl border px-4 py-3 ${isLightMode ? 'bg-white border-gray-300' : 'bg-white/5 border-white/20'}`}>
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className={`text-xs uppercase tracking-wide font-semibold ${riskColor}`}>Подтверждение действия ({risk})</div>
          <div className={`text-sm mt-1 ${isLightMode ? 'text-gray-700' : 'text-white/80'}`}>{request.reason || 'Действие требует подтверждения.'}</div>
          {request.preview && (
            <div className={`text-xs mt-1 truncate ${isLightMode ? 'text-gray-500' : 'text-white/50'}`}>Запрос: {request.preview}</div>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => onDeny(request.confirm_id)}
            className={`px-3 py-1.5 rounded-lg text-sm ${isLightMode ? 'bg-gray-100 hover:bg-gray-200 text-gray-700' : 'bg-white/10 hover:bg-white/20 text-white/80'}`}
          >
            Отклонить
          </button>
          <button
            onClick={() => onApprove(request.confirm_id)}
            className="px-3 py-1.5 rounded-lg text-sm bg-red-500 hover:bg-red-600 text-white"
          >
            Подтвердить
          </button>
        </div>
      </div>
    </div>
  );
}
