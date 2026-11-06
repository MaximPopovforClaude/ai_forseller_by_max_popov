export type ReportPending = {
  started: number;
  before: Record<string, string>;
  expected?: string[];
  idleSince?: number;
  requestPending?: boolean;
  retry?: boolean;
};

type ReportStatus = {
  building?: boolean;
  expected_sections?: string[];
  sections: { section: string; created_at: string }[];
};

/** A lost HTTP response is not evidence that a server-side build stopped. */
export function reportUncertain(job: ReportPending): ReportPending {
  return { ...job, requestPending: false, idleSince: undefined, retry: false };
}

/** Only observed server idleness may enable an explicit retry; never retry here. */
export function reportProgress(job: ReportPending, report: ReportStatus, now: number): { state: "waiting" | "done" | "retry"; job: ReportPending } {
  const expected = job.expected?.length ? job.expected : report.expected_sections || [];
  const next = { ...job, expected, retry: false };
  if (report.building !== false) return { state: "waiting", job: { ...next, idleSince: undefined } };
  const fresh = expected.length > 0 && expected.every((key) => report.sections.some((section) => {
    if (section.section !== key) return false;
    const stamp = Date.parse(section.created_at), before = job.before[key];
    return Number.isFinite(stamp) && (!before || stamp > Date.parse(before));
  }));
  // Allow the initial POST time to dispatch before interpreting an idle GET.
  const posting = job.requestPending && now - job.started < 60_000;
  if (fresh && !posting) return { state: "done", job: next };
  const idleSince = job.idleSince ?? now;
  const retry = !posting && now - idleSince >= 60_000;
  return { state: retry ? "retry" : "waiting", job: { ...next, idleSince, retry } };
}
