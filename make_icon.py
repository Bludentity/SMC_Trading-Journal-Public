from PIL import Image
import os

src = "WhatsApp Image 2026-06-16 at 12.13.23.jpeg"
if not os.path.exists(src):
	print(f"Source image '{src}' not found — skipping icon creation")
else:
	img = Image.open(src).convert("RGBA")
	img.save("icon.ico", format="ICO", sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)])
	print("icon.ico created successfully")
