"""Bounded provider call: timeout, retry/backoff, auth failure, budgets,
content-hash cache. All offline via `FakeProvider` and an injectable
clock/sleeper -- no network, no credentials."""
from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from buy_or_wait import model as model_module  # noqa: E402
from buy_or_wait.evidence import ProposedFact  # noqa: E402


def make_request(request_id="request_01", sources=(("message_01", "message", "hi", None),)):
    return model_module.ExtractionRequest(
        request_id=request_id, user_id="user_01", model_id="fake-extractor-1",
        sources=sources, unresolved_targets=("event_04",),
    )


class FakeClock:
    """A monotonic-looking clock that advances only when `sleeper` is called
    or `advance` is invoked explicitly, so tests are instant and deterministic."""

    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleeper(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class AnthropicProviderConstructionTests(unittest.TestCase):
    def test_missing_api_key_raises_provider_unavailable(self):
        import os
        old = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            with self.assertRaises(model_module.ProviderUnavailable):
                model_module.AnthropicProvider()
        finally:
            if old is not None:
                os.environ["ANTHROPIC_API_KEY"] = old


class BoundedCallerTests(unittest.TestCase):
    def caller(self, clock: FakeClock, **kwargs) -> model_module.BoundedCaller:
        return model_module.BoundedCaller(
            clock=clock.clock, sleeper=clock.sleeper, backoff_base_seconds=1.0, **kwargs
        )

    def test_successful_call_returns_result_and_records_usage(self):
        provider = model_module.FakeProvider(default=model_module.ExtractionResult(
            facts=(), usage=model_module.Usage(calls=1, input_tokens=5, output_tokens=2)))
        ledger = model_module.UsageLedger()
        clock = FakeClock()
        result = self.caller(clock).call(provider, make_request(), ledger)
        self.assertEqual(result.usage.input_tokens, 5)
        self.assertEqual(ledger.total.input_tokens, 5)

    def test_transient_error_is_retried_then_succeeds(self):
        good = model_module.ExtractionResult(facts=(), usage=model_module.Usage(calls=1))
        provider = model_module.FakeProvider(responses={
            "request_01": iter([model_module.TransientError("flaky"), good]).__next__
        })
        ledger = model_module.UsageLedger()
        clock = FakeClock()
        result = self.caller(clock, max_attempts_per_row=3).call(provider, make_request(), ledger)
        self.assertIs(result, good)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(len(clock.sleeps), 1)

    def test_auth_error_is_never_retried(self):
        provider = model_module.FakeProvider(default=model_module.AuthError("bad key"))
        ledger = model_module.UsageLedger()
        clock = FakeClock()
        with self.assertRaises(model_module.AuthError):
            self.caller(clock, max_attempts_per_row=5).call(provider, make_request(), ledger)
        self.assertEqual(len(provider.calls), 1)

    def test_persistent_timeout_raises_after_bounded_attempts(self):
        def timeout_forever():
            raise model_module.TransientError("timed out")
        provider = model_module.FakeProvider(default=timeout_forever)
        ledger = model_module.UsageLedger()
        clock = FakeClock()
        with self.assertRaises(model_module.TransientError):
            self.caller(clock, max_attempts_per_row=3).call(provider, make_request(), ledger)
        self.assertEqual(len(provider.calls), 3)

    def test_deadline_exceeded_stops_retrying_even_with_attempts_left(self):
        def slow():
            raise model_module.TransientError("slow")
        provider = model_module.FakeProvider(default=slow)
        ledger = model_module.UsageLedger()
        clock = FakeClock()
        caller = model_module.BoundedCaller(
            clock=clock.clock, sleeper=clock.sleeper, per_row_timeout_seconds=2.5,
            max_attempts_per_row=10, backoff_base_seconds=2.0,
        )
        with self.assertRaises(model_module.TransientError):
            caller.call(provider, make_request(), ledger)
        # Backoff grows 2s, 4s, ... capped by remaining time; deadline of 2.5s
        # must stop this long before 10 attempts happen.
        self.assertLess(len(provider.calls), 10)

    def test_per_row_token_budget_exceeded_raises(self):
        provider = model_module.FakeProvider(default=model_module.ExtractionResult(
            facts=(), usage=model_module.Usage(calls=1, input_tokens=1000, output_tokens=1000)))
        ledger = model_module.UsageLedger()
        clock = FakeClock()
        caller = self.caller(clock, per_row_token_budget=500)
        with self.assertRaises(model_module.BudgetExceeded):
            caller.call(provider, make_request(), ledger)

    def test_full_run_call_budget_exceeded_raises_on_next_call(self):
        # M4_BUDGET_REVIEW: check_budget() treats total >= budget as
        # exhausted, so a budget of 1 must reject the very first call
        # (0 calls made, budget is 1) -- there is no room for even one
        # call under a budget that low.
        provider = model_module.FakeProvider(default=model_module.ExtractionResult(
            facts=(), usage=model_module.Usage(calls=1)))
        ledger = model_module.UsageLedger(full_run_call_budget=1)
        clock = FakeClock()
        caller = self.caller(clock)
        with self.assertRaises(model_module.BudgetExceeded):
            caller.call(provider, make_request("request_01"), ledger)

    def test_call_budget_exhaustion_prevents_any_further_provider_calls(self):
        """M4 review R-M4-01 / M4_BUDGET_REVIEW: once the ledger is at or
        over budget, a subsequent row must not place a new paid call at all
        -- the check must happen *before* `provider.extract`, not only after
        it records usage, and it must reject at the limit itself (`>=`), not
        only strictly past it. `total.calls` only grows in whole calls, so
        the call that lands exactly on the budget is the last one allowed;
        every row after that must be blocked pre-call."""
        provider = model_module.FakeProvider(default=model_module.ExtractionResult(
            facts=(), usage=model_module.Usage(calls=1, input_tokens=1)))
        ledger = model_module.UsageLedger(full_run_call_budget=2)
        clock = FakeClock()
        caller = self.caller(clock)

        caller.call(provider, make_request("request_01"), ledger)  # total=1, within budget
        self.assertEqual(len(provider.calls), 1)

        with self.assertRaises(model_module.BudgetExceeded):
            caller.call(provider, make_request("request_02"), ledger)  # lands exactly on budget=2, raises after
        self.assertEqual(len(provider.calls), 2)

        for request_id in ("request_03", "request_04", "request_05"):
            with self.assertRaises(model_module.BudgetExceeded):
                caller.call(provider, make_request(request_id), ledger)
        # Every row past the budget is blocked pre-call; none reached the provider.
        self.assertEqual(len(provider.calls), 2)

    def test_token_budget_exhaustion_prevents_any_further_provider_calls(self):
        """Token usage is only known once a call returns, so the call that
        first reaches or crosses the token budget necessarily still happens
        -- but the *next* row, checked before any call, must be blocked
        outright, and the boundary itself (usage == budget) must count as
        exhausted, not just usage > budget."""
        provider = model_module.FakeProvider(default=model_module.ExtractionResult(
            facts=(), usage=model_module.Usage(calls=1, input_tokens=500)))
        ledger = model_module.UsageLedger(full_run_token_budget=1000)
        clock = FakeClock()
        caller = self.caller(clock)

        caller.call(provider, make_request("request_01"), ledger)  # 500 tokens, within budget
        self.assertEqual(len(provider.calls), 1)
        with self.assertRaises(model_module.BudgetExceeded):
            caller.call(provider, make_request("request_02"), ledger)  # lands exactly on 1000, raises after
        self.assertEqual(len(provider.calls), 2)  # this row's call still happened; usage was unknown beforehand

        with self.assertRaises(model_module.BudgetExceeded):
            caller.call(provider, make_request("request_03"), ledger)  # already at/over budget: blocked pre-call
        self.assertEqual(len(provider.calls), 2)  # request_03 never reached the provider

    def test_unclassified_exception_is_not_retried(self):
        provider = model_module.FakeProvider(default=ValueError("boom"))
        ledger = model_module.UsageLedger()
        clock = FakeClock()
        with self.assertRaises(model_module.ProviderError):
            self.caller(clock, max_attempts_per_row=5).call(provider, make_request(), ledger)
        self.assertEqual(len(provider.calls), 1)

    def test_hanging_provider_never_returns_but_call_still_bounds_wall_clock_time(self):
        """R-M2-02: a provider that never returns must not be able to block
        `call()` (or the process) past the per-row timeout. This is a real
        wall-clock wait, not `FakeClock`-driven, so it exercises the actual
        daemon-thread/queue timeout mechanism instead of the retry math."""
        never_returns = threading.Event()

        def hang():
            never_returns.wait()  # blocks forever; the test never sets this
            return model_module.ExtractionResult(facts=(), usage=model_module.Usage(calls=1))

        provider = model_module.FakeProvider(default=hang)
        ledger = model_module.UsageLedger()
        clock = FakeClock()
        caller = self.caller(clock, per_row_timeout_seconds=0.05, max_attempts_per_row=1)

        started = time.monotonic()
        with self.assertRaises(model_module.TransientError):
            caller.call(provider, make_request(), ledger)
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 2.0)


class CacheTests(unittest.TestCase):
    def test_miss_then_hit_after_put(self):
        cache = model_module.ExtractionCache()
        request = make_request()
        key = model_module.cache_key(request, model_id="fake-extractor-1")
        self.assertIsNone(cache.get(key))
        fact = ProposedFact(field="amount", target_event_id="event_04", target_scope="event",
                            value="100", source_ids=("message_01",))
        cache.put(key, facts=[fact], usage=model_module.Usage(calls=1), model_id="fake-extractor-1")
        hit = cache.get(key)
        self.assertIsNotNone(hit)
        self.assertEqual(hit["facts"][0]["value"], "100")

    def test_key_changes_with_source_content(self):
        r1 = make_request(sources=(("message_01", "message", "hello", None),))
        r2 = make_request(sources=(("message_01", "message", "different text", None),))
        self.assertNotEqual(
            model_module.cache_key(r1, model_id="m"), model_module.cache_key(r2, model_id="m"))

    def test_key_changes_with_model_id(self):
        request = make_request()
        self.assertNotEqual(
            model_module.cache_key(request, model_id="model-a"),
            model_module.cache_key(request, model_id="model-b"),
        )

    def test_key_changes_with_prompt_version(self):
        request = make_request()
        self.assertNotEqual(
            model_module.cache_key(request, model_id="m", prompt_version="v1"),
            model_module.cache_key(request, model_id="m", prompt_version="v2"),
        )

    def test_stored_record_under_a_different_key_is_never_served(self):
        cache = model_module.ExtractionCache()
        cache._store["some_key"] = {"cache_key": "a_different_key", "facts": [],
                                    "usage": {}, "model_id": "m"}
        self.assertIsNone(cache.get("some_key"))

    def test_persists_to_disk_and_reloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            cache = model_module.ExtractionCache(path=path)
            request = make_request()
            key = model_module.cache_key(request, model_id="m")
            cache.put(key, facts=[], usage=model_module.Usage(calls=2), model_id="m")
            cache.save()

            reloaded = model_module.ExtractionCache(path=path)
            reloaded.load()
            hit = reloaded.get(key)
            self.assertIsNotNone(hit)
            self.assertEqual(hit["usage"]["calls"], 2)


if __name__ == "__main__":
    unittest.main()
