"""Core data contracts shared across zing.

Everything that crosses a module boundary — config, a single API call's outcome,
a detector's findings, the scored report — is defined here as a pydantic model so
the JSON report is well-typed and detectors compose cleanly. Detector authors
should treat these types as the stable interface.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
class Status(str, Enum):
    """Outcome of a check, finding, or dimension."""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"
    NOT_RUN = "not_run"
    INFO = "info"
    ERROR = "error"


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Dimension(str, Enum):
    """Scoring dimensions. Each detector contributes to exactly one."""

    CONNECTIVITY = "connectivity"
    PROTOCOL = "protocol"
    CONTEXT_WINDOW = "context_window"
    MODEL_IDENTITY = "model_identity"
    CAPABILITY = "capability"
    STREAMING = "streaming"
    BILLING = "billing"
    RELIABILITY = "reliability"
    SECURITY = "security"
    PERFORMANCE = "performance"


class RiskLevel(str, Enum):
    """Headline 货不对板 risk classification."""

    CLEAN = "clean"          # consistent with the claimed model
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"            # strong evidence of mismatch / downgrade
    INCONCLUSIVE = "inconclusive"


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
class TargetConfig(BaseModel):
    """A relay endpoint under audit (or a trusted baseline)."""

    model_config = ConfigDict(extra="forbid")

    name: str = "target"
    kind: str = "target"  # "target" | "baseline"
    base_url: str
    api_key: str = ""
    model: str  # the model id actually sent in requests
    # The model the relay CLAIMS to serve (for KB lookup / comparison). Defaults to
    # `model`. Set it to audit an endpoint's real model id against a different claim
    # — e.g. request `doubao-...` but verify it against the `deepseek-v4-flash` profile.
    claimed_model: str | None = None
    # Wire protocol: "auto" infers from the base_url/model, or force "openai"
    # (Chat Completions) / "anthropic" (Messages API).
    api: str = "auto"

    @property
    def claimed(self) -> str:
        return self.claimed_model or self.model
    # Optional declared metadata used to pick the right knowledge-base profile and
    # to compare claims vs reality. If absent, zing infers from the model id.
    declared_provider: str | None = None
    declared_context_window: int | None = None
    declared_max_output: int | None = None
    # Base HTTP timeout. Each completion gets more on top for its prompt size and
    # output budget (and local hosts at least 300 s), see BaseHTTPClient.
    timeout_sec: float = 60.0
    # Hard ceiling for one request, however large its budget: no call runs longer.
    max_request_sec: float = 900.0
    headers: dict[str, str] = Field(default_factory=dict)
    max_retries: int = 0


class RequestSpec(BaseModel):
    """A single chat-completion request the client should issue."""

    model_config = ConfigDict(extra="forbid")

    messages: list[dict[str, Any]]
    temperature: float | None = 0.0
    max_tokens: int | None = None
    top_p: float | None = None
    stop: str | list[str] | None = None
    seed: int | None = None
    response_format: dict[str, Any] | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None
    stream: bool = False
    extra_body: dict[str, Any] = Field(default_factory=dict)
    # Client-side only (never sent): keep the redacted raw JSON response body in
    # ``CompletionOutcome.raw_body`` (non-stream calls), for envelope checks.
    capture_raw: bool = False


# --------------------------------------------------------------------------- #
# Raw call outcome
# --------------------------------------------------------------------------- #
class CompletionOutcome(BaseModel):
    """Raw evidence from one API call. Detectors interpret these."""

    model_config = ConfigDict(extra="forbid")

    ok: bool = False
    status_code: int | None = None
    content: str = ""
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None
    model_returned: str | None = None

    # Timing
    duration_ms: float | None = None
    ttft_ms: float | None = None  # time to first streamed token
    # Per-event arrival offsets (ms from request start), for fake-stream analysis.
    chunk_timings_ms: list[float] = Field(default_factory=list)
    chunk_count: int = 0

    # Transport / error evidence (redacted before it ever reaches here).
    headers: dict[str, str] = Field(default_factory=dict)
    error_type: str | None = None
    error_message: str | None = None
    raw_error: dict[str, Any] | None = None
    # The redacted raw JSON body of a successful non-stream call, only when the
    # request asked for it (RequestSpec.capture_raw).
    raw_body: dict[str, Any] | None = None

    def has_content(self) -> bool:
        return bool(self.content and self.content.strip())


# --------------------------------------------------------------------------- #
# Detector output
# --------------------------------------------------------------------------- #
class Finding(BaseModel):
    """A single evidence-bearing observation produced by a detector."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    status: Status
    severity: Severity = Severity.INFO
    summary: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)
    recommendation: str | None = None
    # Set by detectors that publish a scoring scale (DetectorResult.scoring):
    # which outcome of that scale this check hit, and the 0-100 points it
    # contributed. ``score`` None means the check was not counted (e.g. it was
    # inconclusive), so it neither raises nor lowers the detector score.
    outcome: str | None = None
    score: float | None = None
    # Scale method "deductions": the points this finding took off the detector's
    # starting 100, and the ceiling it put on the detector score (None: neither).
    deduction: float | None = None
    cap: float | None = None
    # Parametrized checks: one scale check applied to many subjects (e.g. every
    # attribute of a response). ``check`` names the scale check this finding
    # scored against (None: the finding id itself); ``subject`` what was checked.
    check: str | None = None
    subject: str | None = None

    @property
    def scale_check(self) -> str:
        """The scoring-scale check this finding belongs to."""
        return self.check or self.id


class ScoringOutcome(BaseModel):
    """One row of a detector's scoring scale: a possible outcome of one check."""

    model_config = ConfigDict(extra="forbid")

    check: str  # the finding id of the check
    outcome: str  # stable key, unique within the check
    score: float | None = None  # None: the outcome is not counted
    # Method "deductions" (instead of ``score``): a fixed deduction from 100, or
    # one that varies per finding up to ``max_deduction``; and/or a score cap.
    deduction: float | None = None
    max_deduction: float | None = None
    cap: float | None = None
    status: Status
    severity: Severity = Severity.INFO
    label: str = ""  # English, one line: when this outcome applies


class DetectorScoring(BaseModel):
    """How a detector turns its checks into its score, with the full scale of
    possible outcomes so a report shows what each check could have scored."""

    model_config = ConfigDict(extra="forbid")

    # "mean_of_checks": the plain average of the counted checks' scores.
    # "deductions": start at 100, subtract every finding's deduction, then apply
    # the lowest cap any finding set (clamped to 0-100).
    method: str = "mean_of_checks"
    outcomes: list[ScoringOutcome] = Field(default_factory=list)
    # English display titles of parametrized checks (check -> title): a report
    # lists their subjects under one row with this title.
    titles: dict[str, str] = Field(default_factory=dict)


class DetectorResult(BaseModel):
    """The result of running one detector."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    dimension: Dimension
    status: Status = Status.NOT_RUN
    # 0-100 quality/health score for this detector, or None if not scorable.
    score: float | None = None
    findings: list[Finding] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    duration_ms: float | None = None
    error: str | None = None
    # True when this detector required an LLM judge to produce its verdict.
    used_judge: bool = False
    # How ``score`` was derived; None for detectors that do not publish it yet.
    scoring: DetectorScoring | None = None

    def worst_severity(self) -> Severity:
        order = [Severity.INFO, Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]
        worst = Severity.INFO
        for finding in self.findings:
            if order.index(finding.severity) > order.index(worst):
                worst = finding.severity
        return worst


# --------------------------------------------------------------------------- #
# Scoring & verdict
# --------------------------------------------------------------------------- #
class DimensionContribution(BaseModel):
    """One detector's share in a dimension score."""

    model_config = ConfigDict(extra="forbid")

    detector: str  # DetectorResult.id
    score: float | None = None
    status: Status = Status.NOT_RUN
    counted: bool = False  # False: no numeric score, left out of the mean


class StatusOverride(BaseModel):
    """Why a dimension's status differs from what its detectors concluded."""

    model_config = ConfigDict(extra="forbid")

    from_status: Status
    to_status: Status
    severity: Severity  # the finding severity that forced the change
    findings: list[str] = Field(default_factory=list)  # ids of those findings


class DimensionBreakdown(BaseModel):
    """How a dimension's score and status were derived from its detectors."""

    model_config = ConfigDict(extra="forbid")

    # "mean_of_detectors": equal-weight average of the counted detector scores.
    method: str = "mean_of_detectors"
    detectors: list[DimensionContribution] = Field(default_factory=list)
    # Worst status the detectors concluded, before any severity override.
    detector_status: Status = Status.NOT_RUN
    status_override: StatusOverride | None = None


class DimensionScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension: Dimension
    score: float | None = None
    weight: float = 0.0
    status: Status = Status.NOT_RUN
    reason: str = ""
    breakdown: DimensionBreakdown | None = None


class ReliabilitySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requests: int = 0
    successes: int = 0
    success_rate: float = 0.0
    # HTTP 429s — the relay correctly throttling a concurrency burst, an honest
    # behavior. Tracked apart from `errors` so it doesn't tank the success rate.
    rate_limited: int = 0
    latency_ms: dict[str, float | None] = Field(default_factory=dict)
    errors: dict[str, int] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Performance
# --------------------------------------------------------------------------- #
class RequestRecord(BaseModel):
    """Timing and token evidence for one API call made during an audit.

    Numbers only — never prompt or response text. ``phase`` says why the call was
    made: ``passive`` (an ordinary detector request), ``probe`` / ``probe_concurrent``
    (the dedicated performance probe), ``warmup`` (the probe's cold-start request,
    kept out of the stats) or ``ping`` (a ``GET /models`` round-trip measurement).
    """

    model_config = ConfigDict(extra="forbid")

    seq: int
    endpoint: str = "target"  # "target" | "baseline"
    detector: str | None = None
    phase: str = "passive"
    op: str = "complete"  # "complete" | "list_models"
    stream: bool = False
    start_ms: float = 0.0  # offset from the start of the audit

    ok: bool = False
    status_code: int | None = None
    error_type: str | None = None
    timeout: bool = False
    rate_limited: bool = False

    duration_ms: float | None = None
    ttft_ms: float | None = None
    chunk_count: int = 0
    # Gaps between streamed content chunks (a chunk may carry several tokens).
    itl_mean_ms: float | None = None
    itl_p50_ms: float | None = None
    itl_p95_ms: float | None = None
    itl_jitter_ms: float | None = None  # stdev of the gaps

    input_tokens_reported: int | None = None
    output_tokens_reported: int | None = None
    input_tokens_local: int | None = None
    output_tokens_local: int | None = None
    tokens_exact: bool = False  # kept for report compatibility; counts are always estimates
    reasoning_tokens: int | None = None
    cached_input_tokens: int | None = None

    # Output tokens per second: decode = after the first token, e2e = whole call.
    decode_tps_reported: float | None = None
    decode_tps_local: float | None = None
    e2e_tps_reported: float | None = None
    e2e_tps_local: float | None = None

    # Transport breakdown from httpx trace hooks (None on a reused connection).
    connect_ms: float | None = None  # TCP connect, including DNS
    tls_ms: float | None = None
    headers_ms: float | None = None  # request start -> response headers
    # Request fully sent -> response headers (a stream: -> first token).
    server_ms: float | None = None
    # Upstream processing time a relay reports in its own headers (untrusted).
    relay_processing_ms: float | None = None

    # A cache served (part of) this request; it is excluded from the stats.
    cached: bool = False


class PerfStats(BaseModel):
    """Distribution of one metric. A percentile is None below its sample floor."""

    model_config = ConfigDict(extra="forbid")

    count: int = 0
    min: float | None = None
    mean: float | None = None
    p50: float | None = None
    p75: float | None = None
    p90: float | None = None
    p95: float | None = None
    p99: float | None = None
    max: float | None = None
    stdev: float | None = None


class ConcurrencyPerformance(BaseModel):
    """The probe's burst at the configured concurrency."""

    model_config = ConfigDict(extra="forbid")

    concurrency: int = 0
    requests: int = 0
    successes: int = 0
    wall_ms: float | None = None
    # Summed output tokens of all successful requests / wall-clock time.
    aggregate_tps_reported: float | None = None
    aggregate_tps_local: float | None = None
    latency_ms: PerfStats = Field(default_factory=PerfStats)
    ttft_ms: PerfStats = Field(default_factory=PerfStats)


class InputSizeBucket(BaseModel):
    """TTFT / latency for requests of a given prompt size (local token count)."""

    model_config = ConfigDict(extra="forbid")

    label: str
    min_tokens: int
    max_tokens: int | None = None
    count: int = 0
    ttft_p50_ms: float | None = None
    latency_p50_ms: float | None = None


class EndpointPerformance(BaseModel):
    """Headline performance of one endpoint (target or baseline)."""

    model_config = ConfigDict(extra="forbid")

    endpoint: str = "target"
    source: str = "passive"  # "probe" | "passive" — where the headline stats come from
    requests: int = 0
    successes: int = 0
    errors: int = 0
    timeouts: int = 0
    rate_limited: int = 0
    cached_excluded: int = 0
    error_rate: float | None = None
    timeout_rate: float | None = None
    rate_limited_rate: float | None = None

    latency_ms: PerfStats = Field(default_factory=PerfStats)
    ttft_ms: PerfStats = Field(default_factory=PerfStats)
    decode_tps_reported: PerfStats = Field(default_factory=PerfStats)
    decode_tps_local: PerfStats = Field(default_factory=PerfStats)
    e2e_tps_reported: PerfStats = Field(default_factory=PerfStats)
    e2e_tps_local: PerfStats = Field(default_factory=PerfStats)
    itl_ms: PerfStats = Field(default_factory=PerfStats)
    itl_jitter_ms: PerfStats = Field(default_factory=PerfStats)
    connect_ms: PerfStats = Field(default_factory=PerfStats)
    tls_ms: PerfStats = Field(default_factory=PerfStats)
    server_ms: PerfStats = Field(default_factory=PerfStats)
    relay_processing_ms: PerfStats = Field(default_factory=PerfStats)
    network_rtt_ms: PerfStats = Field(default_factory=PerfStats)  # GET /models pings

    cold_start_ms: float | None = None
    cold_start_ttft_ms: float | None = None
    concurrency: ConcurrencyPerformance | None = None
    ttft_by_input: list[InputSizeBucket] = Field(default_factory=list)
    reasoning_tokens_seen: bool = False


class PerformanceComparison(BaseModel):
    """One target-vs-baseline metric (compare mode)."""

    model_config = ConfigDict(extra="forbid")

    metric: str
    unit: str
    target: float | None = None
    baseline: float | None = None
    delta: float | None = None  # target - baseline
    ratio: float | None = None  # target / baseline
    higher_is_better: bool = False  # e.g. tokens/s; latencies and error rates are lower-is-better

    @property
    def target_better(self) -> bool | None:
        """True / False when the target is better / worse than the baseline;
        None when they are within 2% of each other or a side is missing."""
        if self.delta is None or self.target is None or self.baseline is None:
            return None
        scale = max(abs(self.target), abs(self.baseline))
        if scale == 0 or abs(self.delta) / scale < 0.02:
            return None
        return (self.delta > 0) == self.higher_is_better


class PerformanceModeReport(BaseModel):
    """Probe results for a second request mode (the full suite measures both
    streaming and non-streaming)."""

    model_config = ConfigDict(extra="forbid")

    mode: str  # "stream" | "non_stream"
    target: EndpointPerformance = Field(default_factory=EndpointPerformance)
    baseline: EndpointPerformance | None = None
    comparison: list[PerformanceComparison] = Field(default_factory=list)


class ProbeCost(BaseModel):
    """What the dedicated performance probe cost (tokens summed over endpoints)."""

    model_config = ConfigDict(extra="forbid")

    requests: int = 0
    input_tokens_reported: int = 0
    output_tokens_reported: int = 0
    input_tokens_local: int = 0
    output_tokens_local: int = 0


class PerformanceReport(BaseModel):
    """Latency / TTFT / throughput of the audited endpoint(s). The performance
    detector scores the probe's consistency in its own dimension; these stats
    themselves never move the verdict's risk level."""

    model_config = ConfigDict(extra="forbid")

    source: str = "passive"  # "probe" | "passive"
    # Request mode of the headline stats: "stream" / "non_stream" (probe) or
    # "mixed" (passive). ``modes`` holds any further probed mode.
    mode: str = "mixed"
    probe_requests: int = 0  # per endpoint and mode; 0 when the probe did not run
    probe_max_tokens: int | None = None
    tokenizer: str | None = None
    tokens_exact: bool = False
    target: EndpointPerformance = Field(default_factory=EndpointPerformance)
    baseline: EndpointPerformance | None = None
    comparison: list[PerformanceComparison] = Field(default_factory=list)
    modes: list[PerformanceModeReport] = Field(default_factory=list)
    probe_cost: ProbeCost | None = None
    requests: list[RequestRecord] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class Verdict(BaseModel):
    """The headline judgement a user reads first."""

    model_config = ConfigDict(extra="forbid")

    overall_score: float | None = None
    rating: str | None = None  # A-F
    risk_level: RiskLevel = RiskLevel.INCONCLUSIVE
    headline: str = ""
    confidence: str = "low"  # low | medium | high
    summary: str = ""
    key_findings: list[str] = Field(default_factory=list)


class RedactedTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    kind: str
    base_url: str
    model: str
    claimed_model: str | None = None
    declared_provider: str | None = None
    api_key_fingerprint: str | None = None
    # Wire protocol the run spoke: "openai" (Chat Completions), "anthropic"
    # (Messages) or "responses" (OpenAI Responses), and whether it was
    # auto-detected from the base_url/model (False: set by hand). None in
    # reports from before this was recorded.
    api: str | None = None
    api_auto: bool | None = None


class KnowledgeEntryRef(BaseModel):
    """A user knowledge-base entry (kb.db) that shaped the audited profile."""

    model_config = ConfigDict(extra="forbid")

    id: int
    kind: str  # "provider" | "model"
    provider: str
    model_id: str | None = None
    updated_ts: float | None = None
    origin: str | None = None


class KnowledgeUsage(BaseModel):
    """Which knowledge-base profile a run audited against — and where it came from.

    ``profile`` is the full resolved profile (provider-level fields plus the one
    matched model) exactly as used, and ``profile_hash`` its content hash, so a
    report stays verifiable after the knowledge base changes. How the requested
    id matched (``match_confidence``) is a result of the run, not part of the
    profile.
    """

    model_config = ConfigDict(extra="forbid")

    requested_model: str
    matched: bool = False
    match_confidence: str | None = None  # exact | alias | fuzzy
    provider: str | None = None
    model_id: str | None = None
    # packaged:<file> | kb_dir:<path> | kb.db:entry/<id>
    provider_source: str | None = None
    model_source: str | None = None
    # The source a user entry replaced (a packaged or ZING_KB_DIR model).
    shadows: str | None = None
    user_entries: list[KnowledgeEntryRef] = Field(default_factory=list)
    # False when the run left the user's kb.db out (--no-user-kb).
    user_kb: bool = True
    # True when the profile is a watch's pinned snapshot, not the live KB.
    pinned: bool = False
    pinned_at: float | None = None
    profile_hash: str | None = None
    profile: dict[str, Any] | None = None
    # kb.db entries skipped while loading (invalid, unknown provider, ...).
    warnings: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Top-level report
# --------------------------------------------------------------------------- #
class AuditReport(BaseModel):
    """The serializable artifact zing produces. JSON form is the LLM-facing API."""

    model_config = ConfigDict(extra="forbid")

    tool_version: str
    mode: str  # "check" | "compare"
    generated_at: str | None = None  # ISO timestamp, stamped by the runner
    command: str | None = None
    suite: str
    # The dimensions a ``custom`` suite ran (None for the fixed suites).
    dimensions_selected: list[str] | None = None
    # Request mode the performance probe was configured with: "stream",
    # "non_stream" or "both" (the full suite). The streaming-authenticity
    # detector always streams. None in reports from before this was recorded.
    stream_mode: str | None = None

    target: RedactedTarget
    baseline: RedactedTarget | None = None

    verdict: Verdict
    dimensions: list[DimensionScore] = Field(default_factory=list)
    detectors: list[DetectorResult] = Field(default_factory=list)
    baseline_detectors: list[DetectorResult] = Field(default_factory=list)
    reliability: ReliabilitySummary | None = None
    performance: PerformanceReport | None = None

    judge_used: bool = False
    judge_model: str | None = None

    notes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    # Languages of the prompts sent to the audited endpoint: the English prompt
    # library (zing/prompts/en.json) plus any language-bound knowledge-base
    # fingerprints (e.g. "zh" for the Chinese fluency probes of China-native
    # models). Independent of the UI and alert language.
    prompt_languages: list[str] = Field(default_factory=list)
    # The knowledge-base profile the target was audited against, its sources
    # and a full snapshot of it (None in reports from before this existed).
    knowledge: KnowledgeUsage | None = None
