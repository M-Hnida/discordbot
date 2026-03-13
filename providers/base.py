from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Callable, Awaitable


class LLMProvider(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        images: Optional[List[str]] = None,
        tools: Optional[List[Dict]] = None,
        tool_executor: Optional[Callable[[str, Dict], Awaitable[str]]] = None,
    ) -> Dict[str, Any]:
        """
        Sends a chat request to the LLM provider.
        Returns a dictionary with 'choices', optional 'additional_chunks', or 'error'.
        """
        pass


class TTSProvider(ABC):
    @abstractmethod
    def generate_audio(self, text: str) -> Optional[bytes]:
        """
        Generates audio from text.
        Returns bytes of audio data.
        """
        pass
