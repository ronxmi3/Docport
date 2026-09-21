import { AlertCircle, Inbox } from "lucide-react";

export function LoadingState({ rows = 4 }: { rows?: number }) { return <div className="space-y-3 p-5">{Array.from({ length: rows }, (_, index) => <div key={index} className="skeleton h-12 w-full" />)}</div>; }
export function ErrorState({ message }: { message: string }) { return <div className="panel flex min-h-48 flex-col items-center justify-center p-8 text-center"><AlertCircle className="text-danger" size={26} /><p className="mt-3 text-sm font-medium text-ink">Unable to load pipeline data</p><p className="mt-1 max-w-md text-sm text-muted">{message}</p></div>; }
export function EmptyState({ title, copy }: { title: string; copy: string }) { return <div className="flex min-h-48 flex-col items-center justify-center p-8 text-center"><Inbox className="text-muted" size={25} /><p className="mt-3 text-sm font-medium text-ink">{title}</p><p className="mt-1 text-sm text-muted">{copy}</p></div>; }
