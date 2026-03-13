from .llm.openrouter import OpenRouterProvider
from .llm.gemini import GeminiProvider
from .tts.fishaudio import FishAudioProvider

LLM_PROVIDERS = {
    "openrouter": OpenRouterProvider,
    "gemini": GeminiProvider,
}

TTS_PROVIDERS = {"fishaudio": FishAudioProvider}


def get_llm_provider(name: str = "openrouter", **kwargs):
    provider_class = LLM_PROVIDERS.get(name.lower())
    if provider_class:
        return provider_class(**kwargs)
    raise ValueError(f"Unknown LLM provider: {name}")


def get_tts_provider(name: str = "fishaudio", **kwargs):
    provider_class = TTS_PROVIDERS.get(name.lower())
    if provider_class:
        return provider_class(**kwargs)
    raise ValueError(f"Unknown TTS provider: {name}")
