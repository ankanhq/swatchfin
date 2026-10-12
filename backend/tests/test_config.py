"""Tests for the settings: API keys pasted with spaces, line breaks or quotes still work."""

from pathlib import Path

import pytest

from app.config import Settings

KEYS = ("TINYFISH_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY")


@pytest.mark.parametrize(
    "pasted",
    [
        "sk-test-123",
        " sk-test-123",
        "sk-test-123\n",
        "sk-test-123\r\n",
        "\tsk-test-123 ",
        '"sk-test-123"',
        "'sk-test-123'",
        "“sk-test-123”",
        "`sk-test-123`",
        "sk-test-123\u00a0",  # a no-break space
        "\ufeffsk-test-123\u200b",  # a byte-order mark and a zero-width space
        "sk-test-\n123",  # a line break in the middle, from a wrapped paste
    ],
)
def test_keys_lose_whitespace_and_quotes(pasted: str, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in KEYS:
        monkeypatch.setenv(name, pasted)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    for key in (
        settings.tinyfish_api_key,
        settings.anthropic_api_key,
        settings.gemini_api_key,
        settings.groq_api_key,
    ):
        assert key is not None
        assert key.get_secret_value() == "sk-test-123"


def test_keys_from_the_env_file_are_cleaned(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text('TINYFISH_API_KEY = " tf-abc " \nANTHROPIC_API_KEY=sk-ant-xyz\t\n', encoding="utf-8")
    settings = Settings(_env_file=env_file)  # type: ignore[call-arg]
    assert settings.tinyfish_api_key is not None
    assert settings.tinyfish_api_key.get_secret_value() == "tf-abc"
    assert settings.anthropic_api_key is not None
    assert settings.anthropic_api_key.get_secret_value() == "sk-ant-xyz"


@pytest.mark.parametrize("pasted", ['""', "  ", "\n", "''"])
def test_a_key_of_only_spaces_or_quotes_is_not_set(pasted: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TINYFISH_API_KEY", pasted)
    assert Settings(_env_file=None).tinyfish_api_key is None  # type: ignore[call-arg]


def test_keys_passed_directly_are_cleaned() -> None:
    settings = Settings(_env_file=None, groq_api_key=" gsk_1 \n")  # type: ignore[call-arg]
    assert settings.groq_api_key is not None
    assert settings.groq_api_key.get_secret_value() == "gsk_1"
    assert "gsk_1" not in repr(settings)
