from llm.base import LLMProvider


def get_llm() -> LLMProvider:
    import config

    if config.LLM_PROVIDER == "claude":
        from llm.claude import ClaudeProvider
        return ClaudeProvider(api_key=config.ANTHROPIC_API_KEY, model=config.LLM_MODEL)

    if config.LLM_PROVIDER == "grok":
        from llm.grok import GrokProvider
        return GrokProvider(api_key=config.XAI_API_KEY)

    if config.LLM_PROVIDER == "gemini":
        from llm.gemini import GeminiProvider
        return GeminiProvider(api_key=config.GEMINI_API_KEY, model=config.LLM_MODEL)

    raise ValueError(f"Unknown LLM_PROVIDER: {config.LLM_PROVIDER!r}. Supported: claude, grok, gemini")