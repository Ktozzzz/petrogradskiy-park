# -*- coding: utf-8 -*-
"""Клиент LLM: авторизация (Bearer) и работа без ключа.

Тесты не требуют базу данных и внешних сервисов — проверяется формирование
заголовков. Это ядро отличия локального Ollama (без авторизации) от
хостинговых провайдеров (Groq/Gemini/OpenRouter -- Bearer-токен).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ai.llm import LLMClient  # noqa: E402


class _Resp:
    status_code = 200

    def __init__(self, payload=None):
        self._payload = payload or {}

    def json(self):
        return self._payload


def test_headers_without_key_are_empty():
    """Без ключа авторизация не шлётся (локальный Ollama и аналоги)."""
    client = LLMClient(base_url="http://127.0.0.1:1/v1", model="m", api_key="")
    assert client._headers() is None


def test_headers_with_key_are_bearer():
    """С ключом формируется Authorization: Bearer."""
    client = LLMClient(
        base_url="http://127.0.0.1:1/v1", model="m", api_key="sk-test-123"
    )
    assert client._headers() == {"Authorization": "Bearer sk-test-123"}


def test_available_sends_auth_header(monkeypatch):
    """Проверка доступности шлёт ключ на GET /models."""
    captured = {}

    class _Stub:
        @staticmethod
        def get(url, timeout=None, headers=None):
            captured["url"] = url
            captured["headers"] = headers
            return _Resp()

        @staticmethod
        def post(*args, **kwargs):  # noqa: ANN001, ANN003
            raise AssertionError("в available() POST быть не должен")

    monkeypatch.setattr("app.ai.llm.requests", _Stub)
    client = LLMClient(
        base_url="https://api.example.com/v1", model="m", api_key="k1"
    )
    assert client.available() is True
    assert captured["url"] == "https://api.example.com/v1/models"
    assert captured["headers"] == {"Authorization": "Bearer k1"}


def test_available_false_without_key_on_secured_api(monkeypatch):
    """Провайдер без ключа отвечает 401 -> AI помечен недоступным."""
    captured = {}

    class _Resp401:
        status_code = 401

    class _Stub:
        @staticmethod
        def get(url, timeout=None, headers=None):
            captured["headers"] = headers
            return _Resp401()

    monkeypatch.setattr("app.ai.llm.requests", _Stub)
    client = LLMClient(
        base_url="https://api.example.com/v1", model="m", api_key=""
    )
    assert client.available() is False
    assert captured["headers"] is None  # ключа нет -- и AI корректно "выключен"


def test_parse_query_sends_auth_header(monkeypatch):
    """Генерация структурированного запроса шлёт ключ на /chat/completions."""
    captured = {}
    content = '{"intent": "recommend", "text": "детская площадка"}'

    class _Stub:
        @staticmethod
        def get(url, timeout=None, headers=None):
            return _Resp()

        @staticmethod
        def post(url, json=None, timeout=None, headers=None):  # noqa: A002
            captured["url"] = url
            captured["headers"] = headers
            captured["payload"] = json
            return _Resp({"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr("app.ai.llm.requests", _Stub)
    client = LLMClient(
        base_url="https://api.example.com/v1", model="m", api_key="k1"
    )
    parsed = client.parse_query("подбери парк с детской площадкой")
    assert parsed == {"intent": "recommend", "text": "детская площадка"}
    assert captured["url"] == "https://api.example.com/v1/chat/completions"
    assert captured["headers"] == {"Authorization": "Bearer k1"}
    assert captured["payload"]["model"] == "m"
