import os
from typing import Any, List, Optional

from openai import OpenAI

from llm.base import BaseLLMClient


class AzureOpenAIClient(BaseLLMClient):
    """Azure OpenAI client targeting the Responses API."""

    def __init__(
        self,
        endpoint: Optional[str] = None,
        deployment_name: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        self.endpoint = endpoint or os.getenv(
            "AZURE_OPENAI_ENDPOINT",
            "https://samjho-ai.services.ai.azure.com/openai/v1",
        )
        self.deployment_name = deployment_name or os.getenv(
            "AZURE_OPENAI_DEPLOYMENT",
            "gpt-5.6-terra",
        )
        self.api_key = api_key or os.getenv("AZURE_OPENAI_API_KEY")

        if not self.api_key:
            raise RuntimeError("AZURE_OPENAI_API_KEY is not set in .env")

        self.client = OpenAI(base_url=self.endpoint, api_key=self.api_key)

    def create_response(
        self,
        instructions: str,
        input_data: Any,
        tools: Optional[List[dict]] = None,
        previous_response_id: Optional[str] = None,
        on_text_delta: Optional[Any] = None,
    ) -> Any:
        """Call the Azure OpenAI Responses API, optionally streaming text deltas."""
        request: dict[str, Any] = {
            "model": self.deployment_name,
            "instructions": instructions,
            "input": input_data,
        }
        if tools:
            request["tools"] = tools
        if previous_response_id:
            request["previous_response_id"] = previous_response_id

        if callable(on_text_delta):
            try:
                stream_req = dict(request)
                stream_req["stream"] = True
                stream = self.client.responses.create(**stream_req)
                final_response = None
                for event in stream:
                    event_type = getattr(event, "type", "")
                    if event_type == "response.output_text.delta":
                        delta = getattr(event, "delta", "")
                        if delta:
                            on_text_delta(delta)
                    elif event_type == "response.completed":
                        final_response = getattr(event, "response", None)

                if final_response is not None:
                    return final_response
            except Exception:
                # Fall back safely to standard non-streaming request
                pass

        return self.client.responses.create(**request)
