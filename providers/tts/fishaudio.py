import os
import requests
from typing import Optional
from providers.base import TTSProvider


class FishAudioProvider(TTSProvider):
    def __init__(self, api_key: Optional[str] = None, voice_id: Optional[str] = None, **kwargs):
        self.api_key = api_key or os.getenv("FISHAUDIO_API_KEY")
        self.voice_id = voice_id or os.getenv("FISHAUDIO_VOICE_ID", "")
        self.extra_kwargs = kwargs

        if not self.api_key:
            print("Warning: FISHAUDIO_API_KEY missing.")

    def generate_audio(self, text: str) -> Optional[bytes]:
        if not self.api_key:
            return None

        url = "https://api.fish.audio/v1/tts"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "text": text,
            "format": "mp3",
        }
        
        if self.voice_id:
            payload["reference_id"] = self.voice_id
            
        payload.update(self.extra_kwargs)

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            return response.content
        except Exception as e:
            print(f"FishAudio TTS Error: {e}")
            if hasattr(e, "response") and e.response is not None:
                print(f"Response details: {e.response.text}")
            return None
