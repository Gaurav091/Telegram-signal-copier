from PIL import Image, ImageDraw, ImageFont

img = Image.new('RGB', (900, 200), 'white')
from PIL import Image
from PIL import ImageDraw

draw = ImageDraw.Draw(img)
text = 'EURUSD BUY 1.0800 SL 1.0750 TP 1.0900'
draw.text((10, 10), text, fill='black')
img_path = 'tools/sample_signal.png'
img.save(img_path)
print('Wrote', img_path)
