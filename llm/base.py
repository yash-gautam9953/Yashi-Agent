from abc import ABC, abstractmethod
from typing import Any, List, Optional


class BaseLLMClient(ABC):
    """Abstract base class for LLM client implementations."""

    @abstractmethod
    def create_response(
        self,
        instructions: str,
        input_data: Any,
        tools: Optional[List[dict]] = None,
        previous_response_id: Optional[str] = None,
        on_text_delta: Optional[Any] = None,
    ) -> Any:
        """Create a model response.

        Args:
            instructions: System / agent instructions for this turn.
            input_data: User input string or list of tool outputs.
            tools: List of function schemas available to the model.
            previous_response_id: Prior response ID to maintain conversation context.
            on_text_delta: Optional callback invoked with streamed text chunks.

        Returns:
            The raw response object from the LLM provider.
        """
        pass
