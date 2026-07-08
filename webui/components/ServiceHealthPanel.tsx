"use client";

import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  ChevronDown,
  LoaderCircle,
  RefreshCw,
  Wifi,
} from "lucide-react";
import { useState } from "react";
import { STARTUP_CACHE_ITEM_ID, formatBytes } from "@/lib/startup-cache";
import type {
  ServiceHealthItem,
  ServiceHealthSummary,
  StartupCacheStatusDetail,
} from "@/lib/types";

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

function trafficLight({
  items,
  checking,
  error,
}: {
  items: ServiceHealthItem[];
  checking: boolean;
  error: string | null;
}): { className: string; label: string } {
  if (error || items.some((item) => item.status === "error")) {
    return {
      className: "bg-destructive shadow-[0_0_14px_rgba(255,82,82,0.55)]",
      label: "异常",
    };
  }
  if (checking || items.some((item) => item.status === "checking")) {
    return {
      className: "bg-amber-300 shadow-[0_0_14px_rgba(252,211,77,0.55)]",
      label: "检查中",
    };
  }
  if (items.some((item) => item.status === "ok")) {
    return {
      className: "bg-emerald-300 shadow-[0_0_14px_rgba(110,231,183,0.55)]",
      label: "正常",
    };
  }
  return { className: "bg-muted-foreground/60", label: "待检查" };
}

export function ServiceHealthPanel({
  items,
  summary,
  checking,
  error,
  lastCheckedAt,
  onCheck,
  onCheckOne,
  checkingIds = new Set(),
  startupCacheStatus,
}: {
  items: ServiceHealthItem[];
  summary: ServiceHealthSummary | null;
  checking: boolean;
  error: string | null;
  lastCheckedAt: string | null;
  onCheck: () => void;
  onCheckOne?: (serviceId: string) => void;
  checkingIds?: Set<string>;
  startupCacheStatus?: StartupCacheStatusDetail | null;
}) {
  const [expanded, setExpanded] = useState(false);
  const visible = items.length > 0 || checking || error;
  const hasFailures = Boolean(error) || items.some((item) => item.status === "error");
  const light = trafficLight({ items, checking, error });

  return (
    <div
      className={`glass rounded-lg px-3 py-2 ${
        hasFailures ? "border-destructive/60 bg-destructive/10" : ""
      }`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          className="flex min-w-0 flex-1 items-center gap-2 text-left focus-visible:outline-none focus-visible:text-primary"
        >
          <span
            className={`size-3 shrink-0 rounded-full ${light.className}`}
            aria-label={`服务状态：${light.label}`}
          />
          <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
            <span className="flex items-center gap-1.5 font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
              <Wifi className="size-3.5" aria-hidden="true" />
              Service Health
            </span>
            <span className="font-mono text-[0.68rem] uppercase tracking-[0.12em] text-foreground">
              {light.label}
            </span>
            <span className="font-mono text-[0.65rem] uppercase tracking-[0.12em] text-muted-foreground">
              {checking ? "正在检查" : `更新 ${formatCheckedAt(lastCheckedAt)}`}
            </span>
            {summary && (
              <span className="font-mono text-[0.65rem] uppercase tracking-[0.12em] text-muted-foreground">
                OK {summary.ok} · Error {summary.error} · Disabled {summary.disabled}
              </span>
            )}
          </span>
          <ChevronDown
            className={`ml-auto size-3.5 shrink-0 text-muted-foreground transition-transform ${
              expanded ? "rotate-180" : ""
            }`}
            aria-hidden="true"
          />
        </button>
        <div className="flex items-center gap-2">
          {hasFailures && !expanded && (
            <span className="hidden font-mono text-[0.65rem] uppercase tracking-[0.12em] text-destructive sm:inline">
              有服务不可达
            </span>
          )}
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
      </div>

      {expanded && error && (
        <div className="glass-readable mt-3 rounded-md border-destructive/50 bg-destructive/10 px-3 py-2 font-mono text-xs text-destructive">
          {error}
        </div>
      )}

      {expanded && !visible && (
        <div className="glass-readable mt-3 rounded-md border-dashed border-border px-3 py-3 font-mono text-xs text-muted-foreground">
          等待服务可达性检查。
        </div>
      )}

      {expanded && items.length > 0 && (
        <div className="mt-3 space-y-2">
          {items.map((item) => {
            const checkingOne = checkingIds.has(item.id) || item.status === "checking";
            const startupDetails =
              item.id === STARTUP_CACHE_ITEM_ID && startupCacheStatus ? startupCacheStatus : null;
            return (
              <div key={item.id} className="glass-readable rounded-md px-3 py-2">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-sm text-foreground">{item.name}</div>
                    <div className="mt-1 truncate font-mono text-[0.65rem] uppercase tracking-[0.12em] text-muted-foreground">
                      {item.kind}
                      {item.latency_ms === null ? "" : ` · ${item.latency_ms}ms`}
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <div
                      className={`inline-flex items-center gap-1.5 font-mono text-[0.68rem] uppercase tracking-[0.12em] ${statusClass(
                        item.status,
                      )}`}
                    >
                      <StatusIcon status={item.status} />
                      {statusLabel(item.status)}
                    </div>
                    {onCheckOne && (
                      <button
                        type="button"
                        onClick={() => onCheckOne(item.id)}
                        disabled={checking || checkingOne}
                        title={`重新检查 ${item.name}`}
                        aria-label={`重新检查 ${item.name}`}
                        className="glass-control inline-flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:border-primary/60 hover:text-primary focus-visible:outline-none focus-visible:border-primary disabled:cursor-not-allowed disabled:opacity-70"
                      >
                        {checkingOne ? (
                          <LoaderCircle className="size-3.5 animate-spin motion-reduce:animate-none" />
                        ) : (
                          <RefreshCw className="size-3.5" />
                        )}
                      </button>
                    )}
                  </div>
                </div>
                {item.message && (
                  <div className="mt-2 break-words font-mono text-xs leading-5 text-muted-foreground">
                    {item.message}
                  </div>
                )}
                {startupDetails && (
                  <div className="mt-2 space-y-1 font-mono text-xs leading-5 text-muted-foreground">
                    <div>
                      进度 {startupDetails.processed_items}/{startupDetails.total_items} · 删除{" "}
                      {startupDetails.deleted_files} 个文件 · 释放{" "}
                      {formatBytes(startupDetails.released_bytes)}
                    </div>
                    {startupDetails.current_path && (
                      <div className="break-words">当前：{startupDetails.current_path}</div>
                    )}
                    {startupDetails.errors.length > 0 && (
                      <div className="space-y-1 text-destructive">
                        {startupDetails.errors.map((err) => (
                          <div key={`${err.path}:${err.message}`} className="break-words">
                            {err.path}: {err.message}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
