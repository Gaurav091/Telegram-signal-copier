"""Image processor — OCR and AI-based trade signal extraction from chart screenshots."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
import logging
import os

from telegram_signal_copier.adapters.openai_client import OpenAIClient

_NUMERIC_SL = re.compile(r"(?:\bSL\b|\bS\s*/\s*L\b|STOP\s*LOSS)\s*[:=@-]?\s*\d{3,}", re.IGNORECASE)
_NUMERIC_TP = re.compile(r"(?:\bTP\d*\b|\bT\s*/\s*P\d*\b|TAKE\s*PROFIT)\s*[:=@-]?\s*\d{3,}", re.IGNORECASE)
_OCR_KEYWORD_RE = re.compile(
    r"\b(BUY|SELL|SL|S\s*/\s*L|STOP\s*LOSS|TP\d*|T\s*/\s*P\d*|TAKE\s*PROFIT|XAUUSD|EURUSD|GBPUSD|USDJPY|BTCUSD|ETHUSD)\b",
    re.IGNORECASE,
)
_OCR_PRICE_RE = re.compile(r"\b\d{3,6}(?:\.\d{1,5})?\b")

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
            from PIL import Image, ImageFilter, ImageOps  # type: ignore

            self._ocr_available = True
            self._pytesseract = pytesseract
            self._PILImage = Image
            self._PILImageOps = ImageOps
            self._PILImageFilter = ImageFilter
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
            self._PILImageOps = None
            self._PILImageFilter = None

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
                if extracted_text.strip():
                    notes.append(f"Image(s) analyzed with AI vision ({len(images)} chart{'s' if len(images) > 1 else ''})")
                    logger.info("AI vision extracted from image: %s", extracted_text[:200])
                    return ImageProcessingResult(extracted_text=extracted_text, notes=notes, ai_payload=response)
                notes.append("AI vision returned no usable text; trying local OCR fallback")
                logger.warning("AI vision returned empty payload text for %s; trying local OCR", images[0])
            except Exception as exc:
                notes.append(f"AI vision failed: {exc}")
                logger.warning("AI vision failed for %s: %s", images[0], exc)

        # Fallback to local OCR if available
        if (
            self._ocr_available
            and self._PILImage is not None
            and self._PILImageOps is not None
            and self._PILImageFilter is not None
            and self._pytesseract is not None
        ):
            try:
                text, source = self._run_local_ocr(images)
                if text and text.strip():
                    if source:
                        notes.append(f"Image OCR extracted text locally ({source})")
                    else:
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

    def _run_local_ocr(self, image_paths: list[str]) -> tuple[str, str | None]:
        best_text = ""
        best_score = -1
        best_source: str | None = None
        for image_path in image_paths:
            for variant_name, variant in self._iter_ocr_variants(image_path):
                for psm in (6, 11):
                    config = f"--oem 3 --psm {psm}"
                    try:
                        text = self._pytesseract.image_to_string(variant, config=config)
                    except Exception:
                        continue
                    score = self._score_ocr_text(text)
                    if score > best_score:
                        best_score = score
                        best_text = text or ""
                        best_source = f"{os.path.basename(image_path)}:{variant_name}:psm{psm}"
        return best_text.strip(), best_source

    def _iter_ocr_variants(self, image_path: str) -> list[tuple[str, object]]:
        with self._PILImage.open(image_path) as raw:
            rgb = raw.convert("RGB")
        gray = self._PILImageOps.grayscale(rgb)
        auto = self._PILImageOps.autocontrast(gray)
        sharpen = auto.filter(self._PILImageFilter.SHARPEN)
        binary = auto.point(lambda p: 255 if p > 160 else 0)
        return [
            ("gray", gray),
            ("auto", auto),
            ("sharpen", sharpen),
            ("binary", binary),
        ]

    @staticmethod
    def _score_ocr_text(text: str) -> int:
        if not text or not text.strip():
            return -1
        text_u = text.upper()
        keyword_hits = len(_OCR_KEYWORD_RE.findall(text_u))
        price_hits = len(_OCR_PRICE_RE.findall(text_u))
        return keyword_hits * 5 + min(price_hits, 12)

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