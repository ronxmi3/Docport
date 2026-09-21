"use client";

import { LoaderCircle, Play } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";

export function RunVerificationButton() {
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setRunning(true); setError(null);
    try { await api.run(); window.dispatchEvent(new Event("averis:refreshed")); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Unable to run verification"); }
    finally { setRunning(false); }
  }

  return <div className="relative"><button onClick={run} disabled={running} className="inline-flex h-10 items-center gap-2 rounded-lg bg-cyan px-3.5 text-sm font-semibold text-[#062031] transition hover:bg-[#7adcf6] disabled:cursor-wait disabled:opacity-70"><>{running ? <LoaderCircle className="animate-spin" size={16} /> : <Play size={16} fill="currentColor" />}</>{running ? "Running…" : "Run Verification"}</button>{error && <p className="absolute right-0 top-12 w-64 rounded-lg border border-danger/40 bg-panel p-3 text-xs text-danger shadow-panel">{error}</p>}</div>;
}
