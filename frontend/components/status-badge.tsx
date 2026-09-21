import { AlertTriangle, Check, CircleHelp, Minus } from "lucide-react";
import type { Status } from "@/lib/types";

export function StatusBadge({ status }: { status: Status | string }) {
  const style = status === "OK" ? "border-success/30 bg-success/10 text-success" : status === "MISMATCH" ? "border-danger/30 bg-danger/10 text-danger" : status === "NEEDS_REVIEW" ? "border-warning/30 bg-warning/10 text-warning" : "border-line bg-raised text-muted";
  const Icon = status === "OK" ? Check : status === "MISMATCH" ? AlertTriangle : status === "NEEDS_REVIEW" ? CircleHelp : Minus;
  return <span className={`inline-flex w-fit items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-1 text-[11px] font-semibold tracking-wide ${style}`}><Icon size={13} />{status ?? "N/A"}</span>;
}
