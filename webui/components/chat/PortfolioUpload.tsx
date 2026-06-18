"use client";

import { useState } from "react";
import { Upload } from "lucide-react";
import { uploadPortfolio } from "@/lib/api";
import type { PortfolioHolding } from "@/lib/types";

export function PortfolioUpload({
  sessionId,
  onExtracted,
}: {
  sessionId: string;
  onExtracted: (holdings: PortfolioHolding[]) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const handle = async (files: File[]) => {
    if (files.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      const res = await uploadPortfolio(sessionId, files);
      onExtracted(res.holdings);
    } catch (err) {
      setError(err instanceof Error ? err.message : "持仓截图上传失败");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex flex-col items-end gap-1">
      <label className="glass-control inline-flex cursor-pointer items-center gap-2 rounded-md px-3 py-1.5 text-sm transition-colors hover:border-primary/60 hover:text-primary">
        <input
          type="file"
          accept="image/*"
          multiple
          className="hidden"
          onChange={(e) => {
            handle(Array.from(e.target.files ?? []));
            e.currentTarget.value = "";
          }}
        />
        <Upload className="h-4 w-4" />
        {busy ? "识别中…" : "上传持仓截图"}
      </label>
      {error && <p className="max-w-48 text-right text-xs text-destructive">{error}</p>}
    </div>
  );
}
