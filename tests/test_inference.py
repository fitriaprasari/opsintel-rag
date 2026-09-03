"""
Unit tests for the LLM inference layer.
All external HTTP calls are mocked — no real LLM required.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.inference.base import LLMProvider, LLMResponse
from app.inference.mock import MockLLMProvider
from app.inference.openai_compat import LlamaCppProvider, VLLMProvider, get_llm_provider


def _make_provider(**kwargs) -> LlamaCppProvider:
    defaults = {
        "base_url": "http://localhost:8080/v1",
        "api_key": "test-key",
        "model_name": "test-model",
        "max_tokens": 512,
        "temperature": 0.1,
        "timeout": 30,
    }
    defaults.update(kwargs)
    return LlamaCppProvider(**defaults)


MOCK_OPENAI_RESPONSE = {
    "id": "chatcmpl-test",
    "object": "chat.completion",
    "model": "test-model",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": '{"incident_summary": "DB pool exhausted."}'},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
}


class TestOpenAICompatibleProvider:
    @pytest.mark.asyncio
    async def test_complete_returns_llm_response(self):
        provider = _make_provider()
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_OPENAI_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_resp.status_code = 200

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            result = await provider.complete("system prompt", "user message")

        assert isinstance(result, LLMResponse)
        assert result.content == '{"incident_summary": "DB pool exhausted."}'
        assert result.total_tokens == 150

    @pytest.mark.asyncio
    async def test_complete_passes_temperature(self):
        provider = _make_provider(temperature=0.5)
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_OPENAI_RESPONSE
        mock_resp.raise_for_status = MagicMock()

        captured_payload = {}

        async def mock_post(url, json, headers, **kwargs):
            captured_payload.update(json)
            return mock_resp

        with patch("httpx.AsyncClient.post", side_effect=mock_post):
            await provider.complete("sys", "user")

        assert captured_payload["temperature"] == 0.5

    @pytest.mark.asyncio
    async def test_complete_overrides_temperature(self):
        provider = _make_provider(temperature=0.1)
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_OPENAI_RESPONSE
        mock_resp.raise_for_status = MagicMock()

        captured_payload = {}

        async def mock_post(url, json, headers, **kwargs):
            captured_payload.update(json)
            return mock_resp

        with patch("httpx.AsyncClient.post", side_effect=mock_post):
            await provider.complete("sys", "user", temperature=0.9)

        assert captured_payload["temperature"] == 0.9

    def test_model_name_property(self):
        provider = _make_provider(model_name="mistral-7b")
        assert provider.model_name == "mistral-7b"

    def test_llamacpp_and_vllm_are_separate_types(self):
        llamacpp = _make_provider()
        vllm = VLLMProvider(
            base_url="http://vllm:8000/v1",
            api_key="key",
            model_name="model",
            max_tokens=512,
            temperature=0.1,
            timeout=30,
        )
        assert isinstance(llamacpp, LlamaCppProvider)
        assert isinstance(vllm, VLLMProvider)
        assert isinstance(llamacpp, LLMProvider)
        assert isinstance(vllm, LLMProvider)


class TestMockLLMProvider:
    @pytest.mark.asyncio
    async def test_returns_llm_response(self):
        provider = MockLLMProvider()
        result = await provider.complete("sys", "user")
        assert isinstance(result, LLMResponse)
        assert result.model == "mock-llm"
        assert result.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_content_is_valid_json(self):
        import json
        provider = MockLLMProvider()
        result = await provider.complete("sys", "user")
        data = json.loads(result.content)
        assert "incident_summary" in data
        assert "root_cause_hypotheses" in data
        assert "recommended_checks" in data

    def test_model_name(self):
        assert MockLLMProvider().model_name == "mock-llm"

    def test_get_llm_provider_returns_mock_when_configured(self):
        """get_llm_provider() should return MockLLMProvider when LLM_PROVIDER=mock."""
        # conftest already sets LLM_PROVIDER=mock; we must clear the cache to pick it up
        from functools import lru_cache
        import app.config as cfg_module
        # Clear settings cache so env vars are re-read
        cfg_module.get_settings.cache_clear()
        provider = get_llm_provider()
        assert isinstance(provider, MockLLMProvider)




class TestContextBuilderPrompt:
    def test_build_system_prompt_contains_constraints(self):
        from app.agents.context_builder import build_system_prompt
        prompt = build_system_prompt()
        assert "FACT" in prompt
        assert "INFERENCE" in prompt
        assert "HYPOTHESIS" in prompt
        assert "RECOMMENDATION" in prompt
        assert "prompt injection" in prompt.lower() or "instructions" in prompt.lower()

    def test_build_user_message_includes_query(self):
        from datetime import datetime, timezone
        from app.agents.context_builder import build_user_message
        from app.models.domain import IncidentContext
        ctx = IncidentContext(
            incident_id="INC-001",
            timestamp=datetime.now(timezone.utc),
            query="Why is the checkout timing out?",
            environment="production",
        )
        msg = build_user_message(ctx)
        assert "Why is the checkout timing out?" in msg
        assert "INC-001" in msg

    def test_build_user_message_is_valid_json(self):
        import json
        from datetime import datetime, timezone
        from app.agents.context_builder import build_user_message
        from app.models.domain import IncidentContext
        ctx = IncidentContext(
            incident_id="INC-001",
            timestamp=datetime.now(timezone.utc),
            query="test",
            environment="production",
        )
        msg = build_user_message(ctx)
        data = json.loads(msg)
        assert "query" in data
        assert "incident_id" in data
