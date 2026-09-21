export function humanize(value: string | null | undefined) { return value ? value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase()) : "—"; }
export function formatNumber(value: number) { return new Intl.NumberFormat("en-US").format(value); }
export function formatDuration(seconds: number) { return seconds < 1 ? `${Math.round(seconds * 1000)} ms` : `${seconds.toFixed(2)} s`; }
export function formatDate(timestamp: number | null | undefined) { return timestamp ? new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" }).format(timestamp * 1000) : "—"; }
export function formatBytes(bytes: number | null | undefined) { return bytes == null ? "—" : bytes < 1024 * 1024 ? `${Math.round(bytes / 1024)} KB` : `${(bytes / 1024 / 1024).toFixed(2)} MB`; }
