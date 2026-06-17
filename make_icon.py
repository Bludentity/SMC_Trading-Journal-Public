from PIL import Image
img = Image.open("WhatsApp Image 2026-06-16 at 12.13.23.jpeg").convert("RGBA")
img.save("icon.ico", format="ICO", sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)])
print("icon.ico created successfully")
