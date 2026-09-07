"""One-time font asset normalization; run with uv run --with fonttools python."""

from pathlib import Path

from fontTools.ttLib import TTFont

root = Path(__file__).resolve().parents[1] / "app" / "fonts"
for filename, style in [("NotoSansSC.ttf", "Regular"), ("NotoSansSC-Bold.ttf", "Bold")]:
    path = root / filename
    font = TTFont(path)
    names = {
        1: "Noto Sans SC",
        2: style,
        3: f"NotoSansSC-{style}",
        4: f"Noto Sans SC {style}",
        6: f"NotoSansSC-{style}",
        16: "Noto Sans SC",
        17: style,
    }
    for record in font["name"].names:
        if record.nameID in names:
            record.string = names[record.nameID].encode(record.getEncoding())
    font.save(path)
    print(filename, names[6])
