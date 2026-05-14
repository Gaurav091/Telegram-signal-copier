from telegram_signal_copier.services.image_processor import ImageProcessor

ip = ImageProcessor(None)
print('ocr_available=', getattr(ip, '_ocr_available', False))
if getattr(ip, '_pytesseract', None):
    try:
        print('tesseract_cmd=', ip._pytesseract.pytesseract.tesseract_cmd)
        print('tesseract_version=', ip._pytesseract.get_tesseract_version())
    except Exception as e:
        import traceback
        traceback.print_exc()
        print('tesseract probe failed:', e)
else:
    print('pytesseract not available')
