"""Unit tests for the leaf utilities: redaction, SSE parsing, stats, tokenization, YAML."""

from __future__ import annotations

import ast
import socket
import sys
from pathlib import Path

import pytest
import yaml

import zing
from zing.config import ConfigError, load_config_file
from zing.perf.recorder import RequestRecorder
from zing.utils import yamlio
from zing.utils.redact import (
    fingerprint_secret,
    mask_secret,
    redact_headers,
    redact_text,
)
from zing.utils.sse import (
    extract_content_delta,
    extract_tool_calls_delta,
    parse_sse_line,
    try_load_event,
)
from zing.utils.stats import (
    coefficient_of_variation,
    mean,
    percentile,
    stdev,
    summarize,
)
from zing.utils.tokenize import (
    estimate_messages_tokens,
    estimate_tokens,
    heuristic_token_count,
)


# --------------------------------------------------------------------------- #
# redact
# --------------------------------------------------------------------------- #
class TestRedact:
    def test_mask_secret_keeps_recognizable_suffix(self):
        assert mask_secret("sk-1234567890abcdef") == "sk-...cdef"

    def test_mask_secret_short_value_fully_masked(self):
        assert mask_secret("short") == "***"

    def test_mask_secret_empty(self):
        assert mask_secret("") == ""
        assert mask_secret(None) == ""

    def test_fingerprint_is_stable_and_non_reversible(self):
        fp1 = fingerprint_secret("sk-abc123")
        fp2 = fingerprint_secret("sk-abc123")
        assert fp1 == fp2
        assert fp1 is not None and fp1.startswith("sha256:")
        assert "sk-abc123" not in fp1
        assert fingerprint_secret("sk-different") != fp1

    def test_fingerprint_none(self):
        assert fingerprint_secret(None) is None
        assert fingerprint_secret("") is None

    def test_redact_text_scrubs_known_key_shapes(self):
        text = "Auth failed for key sk-ABCDEFGH12345678 in request"
        out = redact_text(text)
        assert "sk-ABCDEFGH12345678" not in out
        assert "«redacted»" in out

    def test_redact_text_scrubs_bearer_and_anthropic(self):
        out = redact_text("header Bearer abc.def-ghi123 and sk-ant-XYZ12345abcd here")
        assert "abc.def-ghi123" not in out
        assert "sk-ant-XYZ12345abcd" not in out

    def test_redact_text_empty(self):
        assert redact_text(None) == ""
        assert redact_text("") == ""

    def test_redact_headers_masks_sensitive_preserves_rest(self):
        headers = {
            "Authorization": "Bearer sk-secret-token-value",
            "X-Api-Key": "abc123",
            "Content-Type": "application/json",
        }
        out = redact_headers(headers)
        assert out["Authorization"] == "«redacted»"
        assert out["X-Api-Key"] == "«redacted»"
        assert out["Content-Type"] == "application/json"

    def test_redact_headers_scrubs_secrets_inside_nonsensitive_values(self):
        out = redact_headers({"X-Debug": "leaked sk-ABCDEFGH12345678 token"})
        assert "sk-ABCDEFGH12345678" not in out["X-Debug"]


# --------------------------------------------------------------------------- #
# sse
# --------------------------------------------------------------------------- #
class TestSSE:
    def test_parse_data_line(self):
        assert parse_sse_line('data: {"a": 1}') == '{"a": 1}'

    def test_parse_done_sentinel(self):
        assert parse_sse_line("data: [DONE]") == "[DONE]"

    def test_parse_skips_comments_and_blanks(self):
        assert parse_sse_line(": keep-alive") is None
        assert parse_sse_line("") is None
        assert parse_sse_line("   ") is None

    def test_parse_skips_non_data_lines(self):
        assert parse_sse_line("event: message") is None

    def test_parse_empty_data_payload(self):
        assert parse_sse_line("data: ") is None

    def test_extract_content_delta_string(self):
        event = {"choices": [{"delta": {"content": "hello"}}]}
        assert extract_content_delta(event) == "hello"

    def test_extract_content_delta_list_parts(self):
        event = {"choices": [{"delta": {"content": [{"text": "a"}, {"text": "b"}]}}]}
        assert extract_content_delta(event) == "ab"

    def test_extract_content_delta_missing(self):
        assert extract_content_delta({"choices": [{"delta": {}}]}) == ""
        assert extract_content_delta({"choices": []}) == ""
        assert extract_content_delta({}) == ""

    def test_extract_tool_calls_delta(self):
        event = {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1"}]}}]}
        tools = extract_tool_calls_delta(event)
        assert tools == [{"index": 0, "id": "call_1"}]

    def test_extract_tool_calls_delta_absent(self):
        assert extract_tool_calls_delta({"choices": [{"delta": {}}]}) == []

    def test_try_load_event_valid_and_invalid(self):
        assert try_load_event('{"x": 1}') == {"x": 1}
        assert try_load_event("not json") is None
        assert try_load_event("[1, 2, 3]") is None  # not a dict


# --------------------------------------------------------------------------- #
# stats
# --------------------------------------------------------------------------- #
class TestStats:
    def test_percentile_empty(self):
        assert percentile([], 50) is None

    def test_percentile_single(self):
        assert percentile([42.0], 95) == 42.0

    def test_percentile_median(self):
        assert percentile([1, 2, 3], 50) == 2.0

    def test_percentile_interpolation(self):
        # rank for p25 over [0,10,20,30] = 0.75 -> 0*0.25 + 10*0.75 = 7.5
        assert percentile([0, 10, 20, 30], 25) == pytest.approx(7.5)

    def test_percentile_extremes(self):
        data = [10, 20, 30, 40]
        assert percentile(data, 0) == 10.0
        assert percentile(data, 100) == 40.0

    def test_mean(self):
        assert mean([2, 4, 6]) == pytest.approx(4.0)
        assert mean([]) is None

    def test_stdev_needs_two_samples(self):
        assert stdev([5.0]) is None
        assert stdev([]) is None

    def test_stdev_population(self):
        # population stdev of [2,4] = 1.0
        assert stdev([2, 4]) == pytest.approx(1.0)

    def test_coefficient_of_variation(self):
        # mean 3, pop stdev 1 -> cv 1/3
        assert coefficient_of_variation([2, 4]) == pytest.approx(1 / 3)

    def test_coefficient_of_variation_degenerate(self):
        assert coefficient_of_variation([5.0]) is None       # too few samples
        assert coefficient_of_variation([0, 0]) is None       # mean zero

    def test_summarize_empty(self):
        s = summarize([])
        assert s["count"] == 0
        assert s["mean"] is None and s["p95"] is None

    def test_summarize_populated(self):
        s = summarize([1, 2, 3, 4, 5])
        assert s["count"] == 5
        assert s["min"] == 1.0
        assert s["max"] == 5.0
        assert s["mean"] == pytest.approx(3.0)
        assert s["p50"] == pytest.approx(3.0)


# --------------------------------------------------------------------------- #
# tokenize
# --------------------------------------------------------------------------- #
class TestTokenize:
    def test_estimate_tokens_empty(self):
        assert estimate_tokens("") == 0

    def test_heuristic_counts_words_and_punctuation(self):
        assert heuristic_token_count("") == 0
        # three word-ish tokens + one punctuation token
        assert heuristic_token_count("hello world foo!") == 4

    def test_heuristic_counts_cjk_per_char(self):
        # four CJK chars ~ four tokens
        assert heuristic_token_count("你好世界") == 4

    def test_heuristic_mixed_cjk_and_latin(self):
        count = heuristic_token_count("hello 世界")
        # "hello" -> 1, two CJK chars -> 2
        assert count == 3

    def test_estimate_tokens_falls_back_to_heuristic(self):
        # unknown tokenizer hint must not crash; equals heuristic
        text = "the quick brown fox"
        assert estimate_tokens(text, tokenizer="nonexistent-encoding") == heuristic_token_count(text)

    def test_estimate_tokens_scales_with_length(self):
        short = estimate_tokens("one two")
        longer = estimate_tokens("one two three four five six")
        assert longer > short

    def test_estimate_messages_tokens_accounts_for_overhead(self):
        messages = [
            {"role": "system", "content": "be terse"},
            {"role": "user", "content": "hello there"},
        ]
        total = estimate_messages_tokens(messages)
        bare = sum(heuristic_token_count(m["content"]) for m in messages)
        # per-message overhead + priming + role tokens make it strictly larger
        assert total > bare

    def test_estimate_messages_tokens_handles_list_content(self):
        messages = [
            {"role": "user", "content": [{"type": "text", "text": "describe this"}]},
        ]
        total = estimate_messages_tokens(messages)
        assert total > 0

    def test_estimate_messages_tokens_empty(self):
        # only the trailing priming constant
        assert estimate_messages_tokens([]) == 3

    def test_tokenizer_hint_does_not_change_the_count(self):
        # Every family uses the heuristic: no hint selects an exact encoding.
        text = "Summarize this paragraph, please. 你好世界"
        for hint in (None, "o200k_base", "cl100k_base", "o200k", "cl100k", "claude"):
            assert estimate_tokens(text, hint) == heuristic_token_count(text)

    def test_no_zing_module_imports_tiktoken(self):
        # zing must run in restricted environments: no tokenizer library (tiktoken
        # downloads its BPE files on first use) may be imported anywhere.
        root = Path(zing.__file__).parent
        offenders = []
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text("utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                if any(n.split(".")[0] == "tiktoken" for n in names):
                    offenders.append(f"{path.relative_to(root)}:{node.lineno}")
        assert offenders == []

    def test_estimating_needs_no_network_or_tokenizer(self, monkeypatch):
        def refuse(*args, **kwargs):
            raise AssertionError("token estimation must not open a connection")

        monkeypatch.setattr(socket.socket, "connect", refuse)
        monkeypatch.setattr(socket, "create_connection", refuse)
        messages = [{"role": "user", "content": "hello there 世界"}]
        for hint in (None, "o200k_base", "cl100k_base"):
            assert estimate_tokens("hello there", hint) > 0
            assert estimate_messages_tokens(messages, hint) > 0
        RequestRecorder("o200k_base")  # used to resolve an encoding up front
        assert "tiktoken" not in sys.modules


# --------------------------------------------------------------------------- #
# yamlio (libyaml loader choice) and config files
# --------------------------------------------------------------------------- #
class TestYamlio:
    def test_prefers_libyaml(self):
        assert yamlio.SAFE_LOADER is getattr(yaml, "CSafeLoader", yaml.SafeLoader)

    def test_loads_like_safe_load(self):
        text = "a: 1\nb: [x, 2.5, null, true]\nc: 2001-12-14\n"
        assert yamlio.safe_load(text) == yaml.safe_load(text)
        assert list(yamlio.safe_load_all("a: 1\n---\nb: 2\n")) == [{"a": 1}, {"b": 2}]
        with pytest.raises(yaml.YAMLError, match="constructor for the tag"):
            yamlio.safe_load("x: !!python/object/apply:os.system [ls]")

    def test_detailed_error_uses_the_pure_python_message(self):
        text = "a:\n\tb: 1"
        with pytest.raises(yaml.YAMLError) as info:
            yamlio.safe_load(text)
        detailed = yamlio.detailed_error(info.value, lambda loader: yamlio.safe_load(text, loader))
        assert "found character '\\t' that cannot start any token" in str(detailed)

    def test_detailed_error_retries_with_the_pure_python_loader(self, monkeypatch):
        # Runs the retry logic whether or not PyYAML has libyaml.
        class Terse(yaml.SafeLoader):
            pass

        monkeypatch.setattr(yamlio, "SAFE_LOADER", Terse)
        used = []

        def retry(loader):
            used.append(loader)
            yamlio.safe_load("a:\n\tb: 1", loader)

        detailed = yamlio.detailed_error(yaml.YAMLError("terse"), retry)
        assert used == [yaml.SafeLoader]
        assert "found character '\\t'" in str(detailed)

    def test_detailed_error_keeps_the_original_when_the_retry_does_not_fail_alike(
        self, monkeypatch
    ):
        class Terse(yaml.SafeLoader):
            pass

        monkeypatch.setattr(yamlio, "SAFE_LOADER", Terse)
        original = yaml.YAMLError("original")

        def recursion(_loader):
            raise RecursionError

        def fail(_loader):
            raise AssertionError("constructor errors are not retried")

        assert yamlio.detailed_error(original, lambda loader: None) is original
        assert yamlio.detailed_error(original, recursion) is original
        tag_error = yaml.constructor.ConstructorError(problem="unknown tag")
        assert yamlio.detailed_error(tag_error, fail) is tag_error


    @pytest.mark.parametrize("loader", sorted({yaml.SafeLoader, yamlio.SAFE_LOADER}, key=str))
    @pytest.mark.parametrize(
        ("text", "message"),
        [
            ("a: !!int abc", "cannot read 'abc' as int: invalid literal"),
            ("a: !!float nope", "cannot read 'nope' as float: could not convert"),
            ("a: !!bool maybe", "cannot read 'maybe' as bool"),
            ("a:\n  b: !!timestamp 2026-99-99", "cannot read '2026-99-99' as timestamp: month"),
        ],
    )
    def test_unreadable_typed_scalar_is_a_yaml_error(self, loader, text, message):
        # PyYAML's constructor raises a bare ValueError/KeyError here, which
        # escaped every caller that handles yaml.YAMLError (a 500 on import).
        with pytest.raises(yaml.constructor.ConstructorError) as info:
            yamlio.safe_load(text, loader)
        assert message in str(info.value)
        mark = info.value.problem_mark
        assert mark is not None and mark.line == text.count("\n")  # at the bad scalar
        with pytest.raises(yaml.YAMLError):
            list(yamlio.safe_load_all("ok: 1\n---\n" + text, loader))

    @pytest.mark.parametrize("loader", sorted({yaml.SafeLoader, yamlio.SAFE_LOADER}, key=str))
    def test_typed_scalars_still_load(self, loader):
        text = "i: !!int 0x1f\nf: !!float 1e3\nb: !!bool yes\nt: !!timestamp 2026-10-06\nn: [1, {x: 2.5}]\n"
        assert yamlio.safe_load(text, loader) == yaml.safe_load(text)


class TestConfigFile:
    def test_loads_a_mapping(self, tmp_path):
        path = tmp_path / "zing.yaml"
        path.write_text("target:\n  base_url: https://relay.test/v1\n", encoding="utf-8")
        assert load_config_file(path) == {"target": {"base_url": "https://relay.test/v1"}}
        path.write_text("", encoding="utf-8")
        assert load_config_file(path) == {}

    def test_invalid_yaml_names_the_problem(self, tmp_path):
        path = tmp_path / "zing.yaml"
        path.write_text("target:\n\tbase_url: x\n", encoding="utf-8")
        with pytest.raises(ConfigError) as info:
            load_config_file(path)
        message = str(info.value)
        assert message.startswith(f"Invalid YAML in {path}: ")
        assert "found character '\\t' that cannot start any token" in message
        assert "line 2, column 1" in message

    def test_unreadable_typed_value_is_a_config_error(self, tmp_path):
        path = tmp_path / "zing.yaml"
        path.write_text("target:\n  timeout: !!float soon\n", encoding="utf-8")
        with pytest.raises(ConfigError, match=r"(?s)cannot read 'soon' as float.*line 2, column 12"):
            load_config_file(path)

    def test_non_mapping_is_refused(self, tmp_path):
        path = tmp_path / "zing.yaml"
        path.write_text("- a\n- b\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="mapping at the top level"):
            load_config_file(path)
