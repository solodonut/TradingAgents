"use client";
import { Activity, AlertTriangle, Clock3, Radio } from "lucide-react";
import type { RunStatusDetail } from "@/lib/types";

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

export function RuntimeStatusPanel({
  runtime,
  runtimeError,
  currentAgentLabel,
}: {
  runtime?: RunStatusDetail | null;
  runtimeError?: string | null;
  currentAgentLabel?: string | null;
}) {
  return (
    <div className="glass rounded-lg px-3 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
          <Radio className="size-3.5" aria-hidden="true" />
          Runtime Status
        </div>
        <div className="font-mono text-[0.65rem] uppercase tracking-[0.12em] text-muted-foreground">
          {runtime?.updated_at ? `更新 ${fmtTime(runtime.updated_at)}` : "等待遥测"}
        </div>
      </div>

      {runtimeError && (
        <div className="glass-readable mt-3 rounded-md border-destructive/50 bg-destructive/10 px-3 py-2 font-mono text-xs text-destructive">
          {runtimeError}
        </div>
      )}

      {!runtime && !runtimeError && (
        <div className="glass-readable mt-3 rounded-md border-dashed border-border px-3 py-3 font-mono text-xs text-muted-foreground">
          暂无后台遥测，可能是旧分析、服务重启前启动，或正在初始化。
        </div>
      )}

      {runtime && (
        <div className="mt-3 space-y-3">
          <div className="grid gap-2 text-sm sm:grid-cols-2">
            <div className="glass-readable rounded-md px-3 py-2">
              <div className="flex items-center gap-2 font-mono text-[0.65rem] uppercase tracking-[0.14em] text-muted-foreground">
                <Activity className="size-3.5" aria-hidden="true" />
                Process
              </div>
              <div className="mt-1 text-foreground">
                {runtime.process_alive ? "后台线程/队列仍存在" : "未发现活动后台进程"}
              </div>
            </div>
            <div className="glass-readable rounded-md px-3 py-2">
              <div className="flex items-center gap-2 font-mono text-[0.65rem] uppercase tracking-[0.14em] text-muted-foreground">
                <Clock3 className="size-3.5" aria-hidden="true" />
                LLM
              </div>
              <div className="mt-1 text-foreground">
                {runtime.llm_active
                  ? `正在等待 LLM 返回 (${runtime.active_llm_calls})`
                  : "当前没有活动 LLM 调用"}
              </div>
            </div>
          </div>

          <dl className="grid gap-x-4 gap-y-2 font-mono text-xs sm:grid-cols-2">
            <div className="flex justify-between gap-3 border-b border-border/60 pb-1">
              <dt className="text-muted-foreground">模型</dt>
              <dd className="max-w-[14rem] truncate text-foreground">
                {runtime.last_llm_model ?? "未知"}
              </dd>
            </div>
            <div className="flex justify-between gap-3 border-b border-border/60 pb-1">
              <dt className="text-muted-foreground">最后发出</dt>
              <dd className="text-foreground">{fmtTime(runtime.last_llm_start_at)}</dd>
            </div>
            <div className="flex justify-between gap-3 border-b border-border/60 pb-1">
              <dt className="text-muted-foreground">最后返回</dt>
              <dd className="text-foreground">{fmtTime(runtime.last_llm_end_at)}</dd>
            </div>
            <div className="flex justify-between gap-3 border-b border-border/60 pb-1">
              <dt className="text-muted-foreground">当前 Agent</dt>
              <dd className="text-foreground">{currentAgentLabel ?? "—"}</dd>
            </div>
            <div className="flex justify-between gap-3 border-b border-border/60 pb-1">
              <dt className="text-muted-foreground">阶段写入</dt>
              <dd className="text-foreground">{fmtTime(runtime.last_report_at)}</dd>
            </div>
            <div className="flex justify-between gap-3 border-b border-border/60 pb-1">
              <dt className="text-muted-foreground">Prompt 字符</dt>
              <dd className="text-foreground">
                {runtime.last_prompt_chars === null ? "—" : runtime.last_prompt_chars}
              </dd>
            </div>
          </dl>

          {runtime.last_llm_error && (
            <div className="glass-readable rounded-md border-destructive/50 bg-destructive/10 px-3 py-2">
              <div className="flex items-center gap-2 font-mono text-[0.65rem] uppercase tracking-[0.14em] text-destructive">
                <AlertTriangle className="size-3.5" aria-hidden="true" />
                Last LLM Error · {fmtTime(runtime.last_llm_error_at)}
              </div>
              <p className="mt-1 font-mono text-xs text-destructive">
                {runtime.last_llm_error}
              </p>
            </div>
          )}

          {runtime.last_prompt_preview && (
            <details className="glass-readable rounded-md px-3 py-2">
              <summary className="cursor-pointer font-mono text-[0.65rem] uppercase tracking-[0.14em] text-muted-foreground">
                最近一次发给 LLM 的 Prompt 摘要
              </summary>
              <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap break-words font-mono text-xs leading-5 text-muted-foreground">
                {runtime.last_prompt_preview}
              </pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
