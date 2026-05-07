from __future__ import annotations

from dataclasses import dataclass

from telegram_signal_copier.adapters.openai_client import OpenAIClient


@dataclass(slots=True)
class ImageProcessingResult:
    extracted_text: str
    notes: list[str]


class ImageProcessor:
    def __init__(self, ai_client: OpenAIClient | None) -> None:
        self.ai_client = ai_client

    def extract_signal_context(self, image_path: str | None) -> ImageProcessingResult:
        if not image_path:
            return ImageProcessingResult(extracted_text="", notes=[])
        if not self.ai_client:
            return ImageProcessingResult(
                extracted_text="",
                notes=["Image present but AI vision client not configured"],
            )
        response = self.ai_client.parse_signal(
            "Extract visible trading text from this image. Preserve buy or sell, entry, stop loss, take profits, and whether it is a fresh new trade.",
            image_path=image_path,
        )
        extracted_text = self._payload_to_text(response)
        return ImageProcessingResult(extracted_text=extracted_text, notes=["Image analyzed with AI vision"])

    @staticmethod
    def _payload_to_text(payload: dict[str, object]) -> str:
        lines: list[str] = []
        symbol = payload.get("symbol")
        side = payload.get("side")
        order_type = payload.get("order_type")
        if symbol:
            lines.append(str(symbol))
        if side:
            lines.append(str(side))
        if order_type and str(order_type).upper() != "MARKET":
            lines.append(str(order_type))

        entry_price = payload.get("entry_price")
        if entry_price not in (None, ""):
            lines.append(f"ENTRY {entry_price}")

        entry_low = payload.get("entry_range_low")
        entry_high = payload.get("entry_range_high")
        if entry_low not in (None, "") and entry_high not in (None, ""):
            lines.append(f"ENTRY RANGE {entry_low}-{entry_high}")

        stop_loss = payload.get("stop_loss")
        if stop_loss not in (None, ""):
            lines.append(f"SL {stop_loss}")

        take_profits = payload.get("take_profits")
        if isinstance(take_profits, list):
            for index, value in enumerate(take_profits, start=1):
                if value in (None, ""):
                    continue
                lines.append(f"TP{index} {value}")

        notes = payload.get("notes")
        if isinstance(notes, str) and notes.strip():
            lines.append(notes.strip())
        elif isinstance(notes, list):
            for note in notes:
                if note not in (None, ""):
                    lines.append(str(note).strip())

        return "\n".join(line for line in lines if line)