from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
import logging
import os

from telegram_signal_copier.adapters.openai_client import OpenAIClient

_NUMERIC_SL = re.compile(r"(?:SL|STOP\s*LOSS)\s*[:=@-]?\s*\d{3,}", re.IGNORECASE)
_NUMERIC_TP = re.compile(r"(?:TP\d*|TAKE\s*PROFIT)\s*[:=@-]?\s*\d{3,}", re.IGNORECASE)

logger = logging.getLogger(__name__)


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
            # If tesseract binary not on PATH, try common Windows install locations
            try:
                # quick probe
                self._pytesseract.get_tesseract_version()
            except Exception:
                # try typical install locations on Windows
                for candidate in (
                    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                ):
                    try:
                        if os.path.exists(candidate):
                            self._pytesseract.pytesseract.tesseract_cmd = candidate
                            # re-probe
                            self._pytesseract.get_tesseract_version()
                            logging.getLogger(__name__).info("Found tesseract binary at %s", candidate)
                            break
                    except Exception:
                        # ignore and try next candidate
                        pass
        except Exception:
            self._ocr_available = False
            self._pytesseract = None
            self._PILImage = None

    def extract_signal_context(
        self,
        image_path: str | None,
        existing_text: str = "",
        all_image_paths: list[str] | None = None,
    ) -> ImageProcessingResult:
        # Collect all available images; primary first
        images: list[str] = []
        if image_path:
            images.append(image_path)
        if all_image_paths:
            for p in all_image_paths:
                if p and p not in images:
                    images.append(p)

        if not images:
            return ImageProcessingResult(extracted_text="", notes=[])

        notes: list[str] = []

        # Only skip image analysis when text is COMPLETE: has BOTH an explicit numeric SL AND numeric TP.
        # A caption with just "BUY" or "XAUUSD BUY" is NOT complete — we still need the chart.
        if existing_text and _NUMERIC_SL.search(existing_text) and _NUMERIC_TP.search(existing_text):
            notes.append("Text already contains explicit numeric SL+TP; skipped image analysis")
            return ImageProcessingResult(extracted_text="", notes=notes)

        logger.info(
            "Analyzing %d image(s) with AI vision (primary: %s)",
            len(images),
            images[0],
        )

        # Try AI vision first (if configured)
        if self.ai_client:
            try:
                response = self.ai_client.parse_signal(
                    (
                        "Extract the trading signal from this chart image. "
                        "Look for colored rectangular zones: GREEN zones are take-profit/buy-target areas, "
                        "RED/PINK zones are stop-loss areas. Read price levels from the Y-axis scale. "
                        "Also note direction from candlestick patterns and any text overlays."
                    ),
                    image_path=images[0],
                    all_image_paths=images[1:] if len(images) > 1 else None,
                )
                extracted_text = self._payload_to_text(response)
                notes.append(f"Image(s) analyzed with AI vision ({len(images)} chart{'s' if len(images) > 1 else ''})")
                logger.info("AI vision extracted from image: %s", extracted_text[:200])
                return ImageProcessingResult(extracted_text=extracted_text, notes=notes, ai_payload=response)
            except Exception as exc:
                notes.append(f"AI vision failed: {exc}")
                logger.warning("AI vision failed for %s: %s", images[0], exc)

        # Fallback to local OCR if available (first image only)
        if self._ocr_available and self._PILImage is not None and self._pytesseract is not None:
            try:
                img = self._PILImage.open(images[0])
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