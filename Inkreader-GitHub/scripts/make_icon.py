from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "assets" / "app.ico"
OUTPUT.parent.mkdir(parents=True, exist_ok=True)

size = 512
image = Image.new("RGBA", (size, size), "#efe8d8")
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((48, 48, 464, 464), radius=108, fill="#8c2f39")
draw.rounded_rectangle((72, 72, 440, 440), radius=88, outline="#f6f1e6", width=8)

font_candidates = [
    Path(r"C:\Windows\Fonts\simkai.ttf"),
    Path(r"C:\Windows\Fonts\simfang.ttf"),
    Path(r"C:\Windows\Fonts\simsun.ttc"),
]
font_path = next((path for path in font_candidates if path.is_file()), None)
font = ImageFont.truetype(str(font_path), 248) if font_path else ImageFont.load_default()
text = "砚"
box = draw.textbbox((0, 0), text, font=font)
width, height = box[2] - box[0], box[3] - box[1]
draw.text(
    ((size - width) / 2, (size - height) / 2 - box[1] - 4),
    text,
    font=font,
    fill="#f6f1e6",
)
draw.ellipse((377, 374, 409, 406), fill="#a8842f")
image.save(OUTPUT, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print(OUTPUT)
