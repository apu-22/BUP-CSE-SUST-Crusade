import os
from abc import ABC, abstractmethod
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


class LLMProviderError(Exception):
    """Raised when an LLM provider encounters an error."""
    pass


class BaseLLMProvider(ABC):
    """Abstract Base Class for LLM Providers to ensure isolation."""

    @abstractmethod
    def generate_json(self, prompt: str) -> str:
        """
        Sends the prompt to the language model and returns raw JSON string.
        """
        pass


class GeminiProvider(BaseLLMProvider):
    """
    Google Gemini Provider using official `google-genai` SDK.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
        try:
            self.timeout = float(timeout or os.getenv("LLM_TIMEOUT", "10"))
        except ValueError:
            self.timeout = 10.0

        if not self.api_key:
            # We don't crash at init, but will raise when generate_json is invoked
            self.client = None
        else:
            try:
                from google import genai
                self.client = genai.Client(api_key=self.api_key)
            except Exception as e:
                raise LLMProviderError(f"Failed to initialize Google GenAI Client: {e}")

    def generate_json(self, prompt: str) -> str:
        if not self.api_key or self.client is None:
            raise LLMProviderError(
                "GEMINI_API_KEY is not set or Google GenAI Client could not be initialized."
            )

        import time
        from google.genai import types

        # Fast flash-lite primary model plus resilient fallbacks
        candidate_models = [
            self.model,
            "gemini-3.5-flash-lite",
            "gemini-3.6-flash",
            "gemini-3.5-flash",
        ]
        # Remove duplicates while preserving order
        candidate_models = list(dict.fromkeys(candidate_models))

        last_error = None

        for model_name in candidate_models:
            for attempt in range(2):
                try:
                    response = self.client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            temperature=0.0,
                        ),
                    )

                    if response and response.text:
                        return response.text.strip()
                except Exception as e:
                    last_error = e
                    if "503" in str(e) or "429" in str(e):
                        time.sleep(0.5)
                        continue
                    # For other non-transient errors, break attempt loop
                    break

        raise LLMProviderError(f"Gemini API generation error: {str(last_error)}")
