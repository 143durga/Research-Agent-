"""
Factory that picks the active LLMProvider from the LLM_PROVIDER env var.
This is the ONLY place that needs to change to add a new provider.
"""
import os
from .anthropic_provider import AnthropicProvider
from .openai_provider import OpenAIProvider

_PROVIDERS = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
}


def get_llm_provider():
    provider_name = os.environ.get("LLM_PROVIDER", "anthropic").lower()
    cls = _PROVIDERS.get(provider_name, AnthropicProvider)
    return cls()
