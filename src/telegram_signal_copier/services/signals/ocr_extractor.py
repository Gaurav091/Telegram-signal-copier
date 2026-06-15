"""Local OCR-based signal extraction — no AI API dependency.

Uses Tesseract OCR + OpenCV preprocessing to extract trading signals from chart images.
Falls back to heuristic text parsing if image processing fails.

Capabilities:
- Image preprocessing (grayscale, thresholding, deskewing)
- Multi-mode OCR (PSM 3, 6, 11) for best text extraction
- Pattern-based SL/TP/Entry detection from OCR text
- Symbol detection from chart labels
- Side detection from arrow annotations or text
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

try:
    import cv2
    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False

from telegram_signal_copier.config import AppConfig
from telegram_signal_copier.constants import SYMBOL_PRICE_RANGES
from telegram_signal_copier.models import ParsedSignal, TelegramSignalMessage
from telegram_signal_copier.services.signals.ocr_runtime import bundled_tesseract_path, configure_pytesseract, tesseract_path
from telegram_signal_copier.services.signals.patterns import (
    ENTRY_PATTERN,
    PRICE_PATTERN,
    SL_PATTERN,
    TP_PATTERN,
)
from telegram_signal_copier.services.signals.normalizers import (
    detect_symbol_in_text,
    normalize_ocr_spaced_numbers,
    normalize_side,
)
from telegram_signal_copier.services.signals.crypto import (
    recover_crypto_entry_from_text,
)

try:
    import pytesseract
    configured_tesseract = configure_pytesseract(pytesseract)
    HAS_TESSERACT = configured_tesseract is not None
except ImportError:
    HAS_TESSERACT = False


def preprocess_image(image_path: str) -> Any | None:
    """Preprocess image for better OCR accuracy on trading charts."""
    if not HAS_OPENCV:
        return None
    
    try:
        img = cv2.imread(image_path)
        if img is None:
            return None
        
        # Upscale image 2x for better text recognition (charts often have tiny text)
        h, w = img.shape[:2]
        scale = 2.0
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)
        
        # Convert to grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Apply CLAHE (Contrast Limited Adaptive Histogram Equalization) for better contrast
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)
        
        # Apply bilateral filter to reduce noise while preserving edges
        gray = cv2.bilateralFilter(gray, 11, 75, 75)
        
        # Apply adaptive thresholding for better text separation
        thresh = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 10
        )
        
        # Morphological operations to clean up small artifacts
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
        
        return thresh
    except Exception:
        return None


def ocr_extract_text(image_path: str) -> str:
    """Extract text from image using Tesseract with multiple PSM modes."""
    if not HAS_TESSERACT:
        return ""
    
    preprocessed = preprocess_image(image_path)
    texts = []
    
    # Try different PSM modes for best results
    psm_modes = [3, 6, 11]  # Fully automatic, uniform block, sparse text
    
    for psm in psm_modes:
        try:
            config = f"--psm {psm} -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz./-:#@ "
            if preprocessed is not None:
                text = pytesseract.image_to_string(preprocessed, config=config)
            else:
                text = pytesseract.image_to_string(image_path, config=config)
            texts.append(text.strip())
        except Exception:
            continue
    
    # Return the longest non-empty result (usually most accurate)
    valid_texts = [t for t in texts if t]
    return max(valid_texts, key=len) if valid_texts else ""


def parse_ocr_signal(
    config: AppConfig,
    message: TelegramSignalMessage,
    ocr_text: str,
) -> ParsedSignal:
    """Parse trading signal from OCR-extracted text."""
    # Normalize OCR spaced numbers FIRST (e.g., "77 645.45" → "77645.45")
    normalized_ocr = normalize_ocr_spaced_numbers(ocr_text)
    combined_text = normalized_ocr.upper()
    
    # Detect symbol — ONLY accept if it matches allowed whitelist (strict mode for OCR)
    symbol = detect_symbol_in_text(combined_text, config.merged_allowed_symbols, strict=True)
    
    # If no valid symbol found in whitelist, reject entire extraction
    # (prevents garbage like "804150" from being accepted)
    if not symbol:
        return ParsedSignal(
            source_group=message.source_group,
            message_id=message.message_id,
            symbol=None,
            side=None,
            order_type="MARKET",
            entry_price=None,
            entry_range_low=None,
            entry_range_high=None,
            stop_loss=None,
            take_profits=[],
            confidence=0.0,
            raw_text=ocr_text,
            image_used=True,
            parser_name="ocr_extractor",
            notes=["OCR extracted no valid symbol from whitelist — rejecting"],
        )
    
    # Detect side
    side = None
    if re.search(r"\b(BUY|LONG|CALL|BULLISH)\b", combined_text) or re.search(r"buy", combined_text, re.IGNORECASE):
        side = "BUY"
    elif re.search(r"\b(SELL|SHORT|PUT|BEARISH)\b", combined_text) or re.search(r"sell", combined_text, re.IGNORECASE):
        side = "SELL"
    
    # Detect entry price
    entry_price = None
    entry_matches = ENTRY_PATTERN.findall(combined_text)
    for m in entry_matches:
        try:
            val = float(m)
            if val >= 100:  # Filter out small numbers
                entry_price = val
                break
        except ValueError:
            continue
    
    # Detect stop loss
    stop_loss = None
    # Handle OCR artifacts: S/L:, S/kL:, SL:, STOP LOSS
    sl_match = re.search(r"(?:S[/\\]?[kK]?L|STOP\s*LOSS)[:\s]*(\d{3,7}(?:\.\d{1,5})?)", combined_text)
    if sl_match:
        try:
            stop_loss = float(sl_match.group(1))
        except ValueError:
            pass
    
    # Detect take profits
    take_profits = []
    # Handle OCR artifacts: T/P:, T/kP:, TP:, TAKE PROFIT
    tp_matches = re.findall(r"(?:T[/\\]?[kK]?P|TAKE\s*PROFIT)[:\s]*(\d{3,7}(?:\.\d{1,5})?)", combined_text)
    for tp in tp_matches:
        try:
            tp_val = float(tp)
            if tp_val >= 100 and tp_val not in take_profits:
                take_profits.append(tp_val)
        except ValueError:
            continue
    
    # If no explicit TP found, try to find prices after "TP" or "TARGET"
    if not take_profits:
        tp_section = re.search(r"(?:TP|TARGET|TAKE.?PROFIT)[:\s]*(.+?)(?:SL|STOP|$)", combined_text, re.DOTALL)
        if tp_section:
            prices = PRICE_PATTERN.findall(tp_section.group(1))
            for p in prices:
                try:
                    tp_val = float(p)
                    if tp_val >= 100 and tp_val not in take_profits:
                        take_profits.append(tp_val)
                except ValueError:
                    continue
    
    # Crypto entry recovery: try to recover entry price from OCR text when missing or suspicious
    recovery_notes = []
    if entry_price is None or entry_price < 5000:  # BTC min is 5000, ETH min is 100
        recovered = recover_crypto_entry_from_text(symbol, side, normalized_ocr, stop_loss, take_profits)
        if recovered is not None:
            entry_price = recovered
            recovery_notes.append("Recovered crypto entry price from OCR text")
    
    # Calculate confidence based on fields found
    fields_found = sum(
        1 for v in [symbol, side, entry_price, stop_loss, take_profits[0] if take_profits else None]
        if v is not None
    )
    confidence = min(0.90, 0.20 + fields_found * 0.14)
    
    notes = [
        "OCR-based extraction (no AI vision)",
        f"Tesseract PSM modes attempted: 3, 6, 11",
    ] + recovery_notes
    if not HAS_OPENCV:
        notes.append("OpenCV not available — skipped preprocessing")
    if not HAS_TESSERACT:
        notes.append("Tesseract not available — OCR extraction failed")
    
    return ParsedSignal(
        source_group=message.source_group,
        message_id=message.message_id,
        symbol=symbol,
        side=side,
        order_type="MARKET",
        entry_price=entry_price,
        entry_range_low=None,
        entry_range_high=None,
        stop_loss=stop_loss,
        take_profits=take_profits,
        confidence=confidence,
        raw_text=ocr_text,
        image_used=True,
        parser_name="ocr_extractor",
        notes=notes,
    )


def extract_signal_from_image(
    config: AppConfig,
    message: TelegramSignalMessage,
) -> ParsedSignal:
    """Main entry point: extract signal from image using local OCR."""
    if not message.image_path or not os.path.exists(message.image_path):
        return ParsedSignal(
            source_group=message.source_group,
            message_id=message.message_id,
            symbol=None,
            side=None,
            order_type="MARKET",
            entry_price=None,
            entry_range_low=None,
            entry_range_high=None,
            stop_loss=None,
            take_profits=[],
            confidence=0.0,
            raw_text="No image provided",
            image_used=False,
            parser_name="ocr_extractor",
            notes=["No image path provided"],
        )
    
    ocr_text = ocr_extract_text(message.image_path)
    
    if not ocr_text.strip():
        return ParsedSignal(
            source_group=message.source_group,
            message_id=message.message_id,
            symbol=None,
            side=None,
            order_type="MARKET",
            entry_price=None,
            entry_range_low=None,
            entry_range_high=None,
            stop_loss=None,
            take_profits=[],
            confidence=0.0,
            raw_text="",
            image_used=True,
            parser_name="ocr_extractor",
            notes=["OCR extraction returned empty text"],
        )
    
    return parse_ocr_signal(config, message, ocr_text)
