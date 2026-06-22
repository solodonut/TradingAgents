"use client";

import { useEffect, useState } from "react";
import type {
  InvestmentHorizon,
  RiskTolerance,
  SessionProfile,
} from "@/lib/types";

const RISK_OPTIONS: { value: RiskTolerance; label: string }[] = [
  { value: "conservative", label: "保守" },
  { value: "balanced", label: "稳健" },
  { value: "aggressive", label: "激进" },
];
const HORIZON_OPTIONS: { value: InvestmentHorizon; label: string }[] = [
  { value: "short", label: "短期" },
  { value: "medium", label: "中期" },
  { value: "long", label: "长期" },
];

export function ProfilePanel({
  value,
  onChange,
  disabled = false,
}: {
  value: SessionProfile;
  onChange: (next: SessionProfile) => void;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState<SessionProfile>(value);
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setDraft(value), [value]);

  const num = (raw: string): number | null => {
    const n = Number(raw);
    return raw.trim() === "" || Number.isNaN(n) ? null : n;
  };

  return (
    <div className="space-y-2 text-sm">
      <label className="block">
        <span className="text-xs text-muted-foreground">可用资金池</span>
        <div className="mt-1 flex gap-2">
          <input
            type="number"
            className="glass-control min-w-0 flex-1 rounded-md px-2 py-1.5 outline-none focus:border-primary"
            value={draft.available_capital ?? ""}
            onChange={(e) =>
              setDraft({ ...draft, available_capital: num(e.target.value) })
            }
            disabled={disabled}
            aria-label="可用资金池"
          />
          <input
            type="text"
            className="glass-control w-20 rounded-md px-2 py-1.5 outline-none focus:border-primary"
            value={draft.capital_currency}
            onChange={(e) =>
              setDraft({ ...draft, capital_currency: e.target.value })
            }
            disabled={disabled}
            aria-label="币种"
          />
        </div>
      </label>

      <label className="block">
        <span className="text-xs text-muted-foreground">风险偏好</span>
        <select
          className="glass-control mt-1 w-full rounded-md px-2 py-1.5 outline-none focus:border-primary"
          value={draft.risk_tolerance ?? ""}
          onChange={(e) =>
            setDraft({
              ...draft,
              risk_tolerance: (e.target.value || null) as RiskTolerance | null,
            })
          }
          disabled={disabled}
          aria-label="风险偏好"
        >
          <option value="">未设置</option>
          {RISK_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>

      <label className="block">
        <span className="text-xs text-muted-foreground">单票最大仓位 (%)</span>
        <input
          type="number"
          className="glass-control mt-1 w-full rounded-md px-2 py-1.5 outline-none focus:border-primary"
          value={draft.max_single_position_pct ?? ""}
          onChange={(e) =>
            setDraft({ ...draft, max_single_position_pct: num(e.target.value) })
          }
          disabled={disabled}
          aria-label="单票最大仓位"
        />
      </label>

      <label className="block">
        <span className="text-xs text-muted-foreground">投资期限</span>
        <select
          className="glass-control mt-1 w-full rounded-md px-2 py-1.5 outline-none focus:border-primary"
          value={draft.horizon ?? ""}
          onChange={(e) =>
            setDraft({
              ...draft,
              horizon: (e.target.value || null) as InvestmentHorizon | null,
            })
          }
          disabled={disabled}
          aria-label="投资期限"
        >
          <option value="">未设置</option>
          {HORIZON_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>

      <label className="block">
        <span className="text-xs text-muted-foreground">偏好 / 禁投</span>
        <textarea
          className="glass-control mt-1 w-full rounded-md px-2 py-1.5 outline-none focus:border-primary"
          rows={2}
          value={draft.constraints ?? ""}
          onChange={(e) =>
            setDraft({ ...draft, constraints: e.target.value || null })
          }
          disabled={disabled}
          aria-label="偏好或禁投约束"
        />
      </label>

      <button
        type="button"
        onClick={() => onChange(draft)}
        disabled={disabled}
        className="glass-control w-full rounded-md px-3 py-1.5 text-sm transition-colors hover:border-primary/60 hover:text-primary disabled:cursor-not-allowed disabled:opacity-45"
      >
        保存参数
      </button>
    </div>
  );
}
