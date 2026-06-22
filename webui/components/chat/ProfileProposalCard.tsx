"use client";

import { useState } from "react";
import type { SessionProfile } from "@/lib/types";

const FIELD_LABELS: Record<string, string> = {
  available_capital: "可用资金池",
  capital_currency: "币种",
  risk_tolerance: "风险偏好",
  max_single_position_pct: "单票最大仓位(%)",
  horizon: "投资期限",
  constraints: "偏好/禁投",
};

export function ProfileProposalCard({
  proposal,
  current,
  disabled = false,
  onConfirm,
  onDismiss,
}: {
  proposal: Partial<SessionProfile>;
  current: SessionProfile;
  disabled?: boolean;
  onConfirm: (merged: SessionProfile) => void;
  onDismiss: () => void;
}) {
  const [draft, setDraft] = useState<Partial<SessionProfile>>(proposal);
  const entries = Object.keys(proposal) as (keyof SessionProfile)[];

  return (
    <div className="mt-3 rounded-md border border-primary/30 bg-primary/5 p-3" aria-label="会话参数确认卡片">
      <div className="mb-2 text-xs text-muted-foreground">
        请确认以下参数将写入会话档案：
      </div>
      <div className="space-y-1.5">
        {entries.map((field) => (
          <label key={field} className="flex items-center gap-2 text-sm">
            <span className="w-28 shrink-0 text-xs text-muted-foreground">
              {FIELD_LABELS[field] ?? field}
            </span>
            <input
              type="text"
              className="glass-control min-w-0 flex-1 rounded-md px-2 py-1 outline-none focus:border-primary"
              value={String(draft[field] ?? "")}
              onChange={(e) =>
                setDraft({ ...draft, [field]: e.target.value })
              }
              disabled={disabled}
              aria-label={FIELD_LABELS[field] ?? String(field)}
            />
          </label>
        ))}
      </div>
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          disabled={disabled}
          onClick={() => onConfirm({ ...current, ...coerce(draft) })}
          className="glass-control rounded-md px-2.5 py-1.5 text-xs transition-colors hover:border-primary/60 hover:text-primary disabled:cursor-not-allowed disabled:opacity-45"
        >
          确认填入
        </button>
        <button
          type="button"
          disabled={disabled}
          onClick={onDismiss}
          className="glass-control rounded-md px-2.5 py-1.5 text-xs text-muted-foreground transition-colors hover:border-destructive/50 hover:text-destructive disabled:cursor-not-allowed disabled:opacity-45"
        >
          忽略
        </button>
      </div>
    </div>
  );
}

function coerce(draft: Partial<SessionProfile>): Partial<SessionProfile> {
  const out: Partial<SessionProfile> = { ...draft };
  for (const key of ["available_capital", "max_single_position_pct"] as const) {
    if (out[key] !== undefined) {
      const n = Number(out[key]);
      out[key] = Number.isNaN(n) ? null : n;
    }
  }
  return out;
}
