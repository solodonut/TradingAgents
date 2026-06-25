"use client";

import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  LoaderCircle,
  RefreshCw,
  Wifi,
} from "lucide-react";
import type { ServiceHealthItem, ServiceHealthSummary } from "@/lib/types";

function statusLabel(status: ServiceHealthItem["status"]): string {
  if (status === "ok") return "可达";
  if (status === "error") return "异常";
  if (status === "disabled") return "禁用";
  return "检查中";
}

function statusClass(status: ServiceHealthItem["status"]): string {
  if (status === "ok") return "text-emerald-300";
  if (status === "error") return "text-destructive";
  if (status === "disabled") return "text-muted-foreground";
  return "text-amber-300";
}

function StatusIcon({ status }: { status: ServiceHealthItem["status"] }) {
  if (status === "ok") return <CheckCircle2 className="size-3.5" aria-hidden="true" />;
  if (status === "error") return <AlertTriangle className="size-3.5" aria-hidden="true" />;
  if (status === "disabled") return <Ban className="size-3.5" aria-hidden="true" />;
  return (
    <LoaderCircle
      className="size-3.5 animate-spin motion-reduce:animate-none"
      aria-hidden="true"
    />
  );
}

function formatCheckedAt(iso: string | null): string {
  if (!iso) return "尚未完成";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleTimeString();
}

export function ServiceHealthPanel({
  items,
  summary,
  checking,
  error,
  lastCheckedAt,
  onCheck,
}: {
  items: ServiceHealthItem[];
  summary: ServiceHealthSummary | null;
  checking: boolean;
  error: string | null;
  lastCheckedAt: string | null;
  onCheck: () => void;
}) {
  const visible = items.length > 0 || checking || error;
  const hasFailures = items.some((item) => item.status === "error");

  return (
    <div
      className={`glass rounded-lg px-3 py-3 ${
        hasFailures ? "border-destructive/60 bg-destructive/10" : ""
      }`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
          <Wifi className="size-3.5" aria-hidden="true" />
          Service Health
        </div>
        <button
          type="button"
          onClick={onCheck}
          disabled={checking}
          className="glass-control inline-flex h-7 items-center gap-1.5 rounded-md px-2 font-mono text-[0.68rem] uppercase tracking-[0.12em] text-foreground transition-colors hover:border-primary/60 hover:text-primary focus-visible:outline-none focus-visible:border-primary disabled:cursor-not-allowed disabled:opacity-70"
        >
          {checking ? (
            <LoaderCircle className="size-3.5 animate-spin motion-reduce:animate-none" />
          ) : (
            <RefreshCw className="size-3.5" />
          )}
          检查
        </button>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2 font-mono text-[0.65rem] uppercase tracking-[0.12em] text-muted-foreground">
        <span>{checking ? "正在检查" : `更新 ${formatCheckedAt(lastCheckedAt)}`}</span>
        {summary && (
          <span>
            OK {summary.ok} · Error {summary.error} · Disabled {summary.disabled}
          </span>
        )}
      </div>

      {error && (
        <div className="glass-readable mt-3 rounded-md border-destructive/50 bg-destructive/10 px-3 py-2 font-mono text-xs text-destructive">
          {error}
        </div>
      )}

      {!visible && (
        <div className="glass-readable mt-3 rounded-md border-dashed border-border px-3 py-3 font-mono text-xs text-muted-foreground">
          等待服务可达性检查。
        </div>
      )}

      {items.length > 0 && (
        <div className="mt-3 space-y-2">
          {items.map((item) => (
            <div key={item.id} className="glass-readable rounded-md px-3 py-2">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate text-sm text-foreground">{item.name}</div>
                  <div className="mt-1 truncate font-mono text-[0.65rem] uppercase tracking-[0.12em] text-muted-foreground">
                    {item.kind}
                    {item.latency_ms === null ? "" : ` · ${item.latency_ms}ms`}
                  </div>
                </div>
                <div
                  className={`inline-flex shrink-0 items-center gap-1.5 font-mono text-[0.68rem] uppercase tracking-[0.12em] ${statusClass(
                    item.status,
                  )}`}
                >
                  <StatusIcon status={item.status} />
                  {statusLabel(item.status)}
                </div>
              </div>
              {item.message && (
                <div className="mt-2 break-words font-mono text-xs leading-5 text-muted-foreground">
                  {item.message}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
