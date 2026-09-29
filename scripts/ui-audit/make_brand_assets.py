"""Derive usable brand assets from the two supplied logo JPEGs.

Both sources are 2421x1417 with the artwork inset in a wide white margin, so
rendering them whole would show a mark adrift in white. This crops each to its
ink and writes ASCII-named PNGs next to the originals, which stay untouched:

  logo.png     the compact file's top element — a graphic mark, for the
                     header tile, the search row and the small avatar fallback
  brand-lockup.png   the wide file's full lockup, for the sign-in brand column
  public/logo.png    the mark padded to a square canvas, so the favicon is not
                     letterboxed inside the tab's square icon slot
"""

from pathlib import Path

from PIL import Image

ASSETS = Path("../../web/src/assets/icon")
PUBLIC = Path("../../web/public")

PAD = 0.04  # a little air around the ink, in fractions of the ink box


def ink_box(im: Image.Image) -> tuple:
    return im.convert("L").point(lambda v: 255 if v < 225 else 0).getbbox()


def crop_to_ink(im: Image.Image) -> Image.Image:
    box = ink_box(im)
    x0, y0, x1, y1 = box
    pad_x = int((x1 - x0) * PAD)
    pad_y = int((y1 - y0) * PAD)
    return im.crop(
        (
            max(0, x0 - pad_x),
            max(0, y0 - pad_y),
            min(im.width, x1 + pad_x),
            min(im.height, y1 + pad_y),
        )
    )


mark_src = Image.open(ASSETS / "芯导logo2.jpg").convert("RGB")
lockup_src = Image.open(ASSETS / "芯导logo.jpg").convert("RGB")

# The compact file stacks a mark over its wordmark lines; only the top band is the
# graphic, and that is what a 16-32px slot can actually show.
mark_band = crop_to_ink(mark_src.crop((0, 360, mark_src.width, 510)))
mark_band.save(ASSETS / "logo.png", optimize=True)

lockup = crop_to_ink(lockup_src)
lockup.save(ASSETS / "brand-lockup.png", optimize=True)

# Square favicon: the mark centred on white, which is the canvas colour it
# already sits on.
side = max(mark_band.size)
favicon = Image.new("RGB", (side, side), (255, 255, 255))
favicon.paste(
    mark_band,
    ((side - mark_band.width) // 2, (side - mark_band.height) // 2),
)
favicon.save(PUBLIC / "logo.png", optimize=True)

for path in (
    ASSETS / "logo.png",
    ASSETS / "brand-lockup.png",
    PUBLIC / "logo.png",
):
    with Image.open(path) as im:
        print(f"{path}  {im.width}x{im.height}  {path.stat().st_size / 1024:.1f} KB")
