"""Unit tests for target-model token counting and GPT-5.x o200k mapping."""

from __future__ import annotations

import pytest

tiktoken = pytest.importorskip("tiktoken")

from slashtoken.providers.base import TiktokenCounter, model_uses_o200k_base


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gpt-5", True),
        ("gpt-5.6", True),
        ("gpt-5.6-terra", True),
        ("GPT-5.4", True),
        ("gpt-5-mini", True),
        ("gpt-4o", True),
        ("gpt-4.1", True),
        ("o3", True),
        ("o4-mini", True),
        ("ft:gpt-5.6", True),
        ("claude-opus-4", False),
        ("composer-2", False),
        ("deepseek-ai/deepseek-v4-flash", False),
    ],
)
def test_model_uses_o200k_base(model: str, expected: bool) -> None:
    assert model_uses_o200k_base(model) is expected


@pytest.mark.parametrize(
    "model",
    ["gpt-5", "gpt-5.6", "gpt-5.6-terra", "gpt-5.4", "gpt-4o"],
)
def test_tiktoken_counter_uses_o200k_for_gpt5_family(model: str) -> None:
    counter = TiktokenCounter()
    text = "你好，请写一份关于机器学习的简要说明。"
    result = counter.count(text, model)

    assert result.exact is True
    assert result.tokenizer == "tiktoken:o200k_base"
    assert result.tokens == len(tiktoken.get_encoding("o200k_base").encode(text))


def test_tiktoken_counter_falls_back_for_unknown_families() -> None:
    counter = TiktokenCounter()
    text = "你好，请写一份关于机器学习的简要说明。"
    result = counter.count(text, "claude-opus-4")

    assert result.exact is False
    assert result.tokenizer.startswith("approximate-utf8:")
    assert result.tokens >= 1


def test_gpt5_family_matches_direct_o200k_encoding() -> None:
    """Dotted GPT-5.x IDs must match the website-equivalent o200k counts."""
    counter = TiktokenCounter()
    encoding = tiktoken.get_encoding("o200k_base")
    original = (
        "请根据以下需求编写一份完整的技术方案：我们需要构建一个多语言大模型网关，"
        "能够在不损失用户意图的前提下降低API成本。"
    )
    english = (
        "Write a complete technical proposal: build a multilingual LLM gateway "
        "that reduces API cost without losing user intent."
    )

    original_count = counter.count(original, "gpt-5.6-terra")
    english_count = counter.count(english, "gpt-5.6-terra")

    assert original_count.tokens == len(encoding.encode(original))
    assert english_count.tokens == len(encoding.encode(english))
    assert original_count.tokens > english_count.tokens
