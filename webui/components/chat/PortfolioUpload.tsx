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
  const handle = async (file: File) => {
    setBusy(true);
    try {
      const res = await uploadPortfolio(sessionId, file);
      onExtracted(res.holdings);
    } finally {
      setBusy(false);
    }
  };
  return (
    <label className="inline-flex cursor-pointer items-center gap-2 rounded-md border border-border bg-background px-3 py-1.5 text-sm hover:bg-card">
      <input
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(e) => e.target.files?.[0] && handle(e.target.files[0])}
      />
      <Upload className="h-4 w-4" />
      {busy ? "识别中…" : "上传持仓截图"}
    </label>
  );
}
