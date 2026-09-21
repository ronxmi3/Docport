export type Status = "OK" | "MISMATCH" | "NEEDS_REVIEW" | null;
export type EmailListItem = { email_id: string; subject: string; category: string; status: Status; defect_count: number; review_reason: string | null };
export type Distribution = { name: string; value: number };
export type Summary = {
  metrics: { total_emails: number; bl_comparisons: number; ok: number; mismatch: number; needs_review: number; runtime_seconds: number; throughput: number };
  category_distribution: Distribution[];
  outcome_distribution: Distribution[];
  review_distribution: Distribution[];
  notable_cases: EmailListItem[];
  source: string;
  loader: string;
  generated_at: number;
};
export type Attachment = { filename: string; source_format: string | null; extraction: string | null; read_error: string | null; detected_type: string | null; evidence: string[] };
export type ComparisonField = { field: string; si_value: string | null; bl_value: string | null; si_normalized: string | null; bl_normalized: string | null; result: string };
export type EmailDetail = {
  email_id: string; subject: string; category: string; classification_reasons: string[]; attachments: Attachment[]; selected_documents: { si: string | null; bl: string | null };
  extraction_status: string; status: Status; defect_fields: string[]; review_reason: string | null; comparison_fields: ComparisonField[]; error: string | null; timings_ms: Record<string, number>; generated_at: number;
};
export type ReviewItem = EmailListItem & { attachments: Attachment[]; evidence: string[] };
export type ReportStatus = { exists: boolean; filename: string; size_bytes: number | null; generated_at: number | null; download_url: string | null };
