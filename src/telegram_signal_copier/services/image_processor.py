from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from telegram_signal_copier.adapters.openai_client import OpenAIClient


@dataclass(slots=True)
class ImageProcessingResult:
    extracted_text: str
    notes: list[str]
    ai_payload: dict | None = None


class ImageProcessor:
    def __init__(self, ai_client: OpenAIClient | None) -> None:
        self.ai_client = ai_client
        # detect optional local OCR availability (pytesseract + PIL)
        try:
            import pytesseract  # type: ignore
            from PIL import Image  # type: ignore

            self._ocr_available = True
            self._pytesseract = pytesseract
            self._PILImage = Image
        except Exception:
            self._ocr_available = False
            self._pytesseract = None
            self._PILImage = None

    def extract_signal_context(self, image_path: str | None, existing_text: str = "") -> ImageProcessingResult:
        if not image_path:
            return ImageProcessingResult(extracted_text="", notes=[])

        notes: list[str] = []

        # If existing text already contains trading markers, skip image analysis
        if existing_text:
            upper = existing_text.upper()
            markers = ("SL", "TP", "BUY", "SELL", "ENTRY", "STOP LOSS")
            if any(m in upper for m in markers):
                notes.append("Existing text contains trading fields; skipped image analysis")
                return ImageProcessingResult(extracted_text="", notes=notes)

        # Try AI vision first (if configured)
        if self.ai_client:
            try:
                response = self.ai_client.parse_signal(
                    "Extract visible trading text from this image. Preserve buy or sell, entry, stop loss, take profits, and whether it is a fresh new trade.",
                    image_path=image_path,
                )
                extracted_text = self._payload_to_text(response)
                notes.append("Image analyzed with AI vision")
                return ImageProcessingResult(extracted_text=extracted_text, notes=notes, ai_payload=response)
            except Exception as exc:  # handle provider or network errors gracefully
                notes.append(f"AI vision failed: {exc}")

        # Fallback to local OCR if available
        if self._ocr_available and self._PILImage is not None and self._pytesseract is not None:
            try:
                img = self._PILImage.open(image_path)
                text = self._pytesseract.image_to_string(img)
                if text and text.strip():
                    notes.append("Image OCR extracted text locally")
                    return ImageProcessingResult(extracted_text=text.strip(), notes=notes)
                notes.append("Local OCR ran but returned no text")
                return ImageProcessingResult(extracted_text="", notes=notes)
            except Exception as exc:
                notes.append(f"Local OCR failed: {exc}")
                return ImageProcessingResult(extracted_text="", notes=notes)

        # No AI vision or OCR succeeded
        if not self.ai_client:
            notes.append("Image present but AI vision client not configured and no local OCR available")
        else:
            notes.append("Image present; AI vision failed and no local OCR available")
        return ImageProcessingResult(extracted_text="", notes=notes)

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