import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import type { UsageLimits, UsageRemaining } from '../services/api';

interface SessionUsageNoticeModalProps {
  open: boolean;
  limits: UsageLimits;
  remaining?: UsageRemaining;
  onClose: () => void;
}

export function SessionUsageNoticeModal({ open, limits, remaining, onClose }: SessionUsageNoticeModalProps) {
  useEffect(() => {
    if (!open) {
      return;
    }

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        onClose();
      }
    }

    window.addEventListener('keydown', onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [open, onClose]);

  if (!open || typeof document === 'undefined') {
    return null;
  }

  return createPortal(
    <div
      className="fixed inset-0 z-[3000] flex items-center justify-center bg-slate-950/78 px-4 py-6 backdrop-blur-[2px]"
      onMouseDown={onClose}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Session Usage Notice"
        onMouseDown={(event) => event.stopPropagation()}
        className="w-full max-w-xl rounded-2xl border border-cyan-400/30 bg-[linear-gradient(180deg,rgba(2,6,23,0.98),rgba(15,23,42,0.96))] shadow-[0_0_45px_rgba(34,211,238,0.22)]"
      >
        <div className="border-b border-cyan-400/20 px-5 py-4">
          <h2 className="text-lg font-semibold tracking-wide text-cyan-200">Session Usage Notice</h2>
        </div>
        <div className="space-y-3 px-5 py-4 text-sm leading-6 text-slate-200">
          <p>
            Chat per session: <span className="font-semibold text-cyan-200">{limits.session_chat_max}</span> requests.
          </p>
          <p>
            Run Analysis per session: <span className="font-semibold text-cyan-200">{limits.session_analysis_max}</span> requests.
          </p>
          <p>
            Per-device daily limit: <span className="font-semibold text-cyan-200">{limits.device_daily_max}</span> requests.
          </p>
          {remaining && (
            <div className="space-y-1 rounded-lg border border-cyan-400/20 bg-slate-900/40 px-3 py-2 text-xs">
              <p>
                Today remaining: <span className="font-semibold text-cyan-200">{remaining.today_remaining}</span>
                {' '}({remaining.device_daily_used}/{limits.device_daily_max} used)
              </p>
              <p>
                Session remaining — chat: <span className="font-semibold text-cyan-200">{remaining.session_chat_remaining}</span>,
                {' '}analysis: <span className="font-semibold text-cyan-200">{remaining.session_analysis_remaining}</span>
              </p>
            </div>
          )}
          <p>
            Per-IP daily protection: <span className="font-semibold text-cyan-200">{limits.ip_daily_max}</span> requests.
          </p>
        </div>
        <div className="flex justify-end border-t border-cyan-400/20 px-5 py-3">
          <button
            type="button"
            onClick={onClose}
            className="cyber-action rounded-md px-4 py-1.5 text-sm font-semibold text-white transition"
          >
            I Understand
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
