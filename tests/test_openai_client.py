import io
import json
import time
import unittest
from unittest.mock import patch

from telegram_signal_copier.adapters.openai_client import OpenAIClient


class SimpleConfig:
    def __init__(self, providers, max_rpm=60, cooldown=1, max_cool=60, cache_ttl=300):
        self.openai_model = "gpt-test"
        self.ai_providers = providers
        self.ai_max_requests_per_minute = max_rpm
        self.ai_provider_cooldown_seconds = cooldown
        self.ai_provider_max_cooldown_seconds = max_cool
        self.ai_cache_ttl_seconds = cache_ttl
        self.cloudflare_account_id = None


class FakeResp:
    def __init__(self, data_bytes: bytes):
        self._data = data_bytes

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class OpenAIClientTests(unittest.TestCase):
    def test_cache_prevents_repeated_requests(self):
        config = SimpleConfig([{"name": "primary", "api_key": "k", "base_url": "https://example.test"}])
        client = OpenAIClient(config)

        response_body = json.dumps({"choices": [{"message": {"content": json.dumps({"symbol": "EURUSD", "confidence": 0.9})}}]})

        calls = {"n": 0}

        def _urlopen(req, timeout=60):
            calls["n"] += 1
            return FakeResp(response_body.encode("utf-8"))

        with patch("urllib.request.urlopen", side_effect=_urlopen):
            first = client.parse_signal("test payload")
            self.assertEqual(first.get("symbol"), "EURUSD")
            self.assertEqual(calls["n"], 1)

            second = client.parse_signal("test payload")
            self.assertEqual(second.get("symbol"), "EURUSD")
            # no extra network call due to cache
            self.assertEqual(calls["n"], 1)

    def test_token_bucket_limits(self):
        config = SimpleConfig([{"name": "primary", "api_key": "k", "base_url": "https://example.test"}], max_rpm=1)
        client = OpenAIClient(config)
        # first token available
        self.assertTrue(client._acquire_token())
        # second immediate token not available
        self.assertFalse(client._acquire_token())

    def test_circuit_breaker_trips_provider_on_429(self):
        providers = [
            {"name": "p1", "api_key": "k1", "base_url": "https://p1.example"},
            {"name": "p2", "api_key": "k2", "base_url": "https://p2.example"},
        ]
        config = SimpleConfig(providers)
        client = OpenAIClient(config)

        # first call -> HTTPError 429 for provider 1, then success for provider 2
        from urllib import error

        def _urlopen(req, timeout=60):
            # mimic first call failing with 429, second call succeed
            if _urlopen.calls == 0:
                _urlopen.calls += 1
                fp = io.BytesIO(b'{"error":"rate limit"}')
                raise error.HTTPError(req.full_url if hasattr(req, 'full_url') else str(req), 429, "Too Many Requests", hdrs=None, fp=fp)
            return FakeResp(json.dumps({"choices": [{"message": {"content": json.dumps({"symbol": "USDJPY", "confidence": 0.8})}}]}).encode("utf-8"))

        _urlopen.calls = 0

        with patch("urllib.request.urlopen", side_effect=_urlopen):
            res = client.parse_signal("circuit test")
            self.assertEqual(res.get("symbol"), "USDJPY")
            # provider 1 should have recorded a failure and been tripped
            p1 = client.providers[0]
            self.assertGreater(p1.get("failure_count", 0), 0)
            self.assertGreater(p1.get("trip_until", 0), time.time() - 1)

    def test_cloudflare_adapter_flattens_text_only_message_content(self):
        config = SimpleConfig(
            [{"name": "cloudflare", "api_key": "k", "base_url": "https://example.test", "model": "cf-model"}]
        )
        client = OpenAIClient(config)

        response_body = json.dumps(
            {"choices": [{"message": {"content": json.dumps({"intent": "INFORMATIONAL", "confidence": 0.9})}}]}
        )
        seen_payload: dict[str, object] = {}

        def _urlopen(req, timeout=60):
            seen_payload.update(json.loads(req.data.decode("utf-8")))
            return FakeResp(response_body.encode("utf-8"))

        with patch("urllib.request.urlopen", side_effect=_urlopen):
            result = client.classify_intent("BUY GOLD")

        self.assertEqual(result.get("intent"), "INFORMATIONAL")
        self.assertIsInstance(seen_payload["messages"][1]["content"], str)
        self.assertEqual(seen_payload["messages"][1]["content"], "BUY GOLD")


if __name__ == "__main__":
    unittest.main()
