"""Check a build of scripts/build.py, or any folder of tiles in its layout.

    python scripts/check.py --out work/out
    python scripts/check.py --folder some/ne2sr --maxzoom 6 --no-pmtiles

Fails when:

- a tile of zoom 0 to --maxzoom is missing, or is not a square image of --tile-size pixels;
- any pixel of a tile is less than opaque (a tile with an alpha band must have 255 everywhere): the fault of the tiles
  of OpenFreeMap, which have a transparent column at 180 degrees and a transparent row at the bottom;
- a PNG tile does not have the pixels of its WebP tile (the PNG tiles are the WebP tiles decoded);
- the PMTiles archive does not hold exactly the WebP tiles of the folder, with the zooms and type it should have.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def load(path: Path, tile_size: int, errors: list) -> np.ndarray | None:
    if not path.is_file():
        errors.append(f'{path}: missing')
        return None
    with Image.open(path) as image:
        image.load()
        if image.size != (tile_size, tile_size):
            errors.append(f'{path}: {image.size[0]} x {image.size[1]} pixels, not {tile_size} x {tile_size}')
        if 'A' in image.getbands() or 'transparency' in image.info:
            alpha = np.asarray(image.convert('RGBA'))[:, :, 3]
            clear = int(np.count_nonzero(alpha != 255))
            if clear:
                rows, cols = (sorted(set(i.tolist())) for i in np.nonzero(alpha != 255))
                span = lambda what, v: f'{what} {v[0]}' if len(v) == 1 else f'{what}s {v[0]} to {v[-1]}'
                errors.append(f'{path}: {clear} pixels are not opaque ({span("row", rows)}, {span("column", cols)})')
        return np.asarray(image.convert('RGB')).astype(np.int16)


def check_folder(folder: Path, maxzoom: int, tile_size: int, ext: str, errors: list) -> int:
    count = 0
    for z in range(maxzoom + 1):
        n = 1 << z
        for x in range(n):
            for y in range(n):
                load(folder / str(z) / str(x) / f'{y}.{ext}', tile_size, errors)
                count += 1
    return count


def check_same_pixels(folder: Path, maxzoom: int, errors: list) -> None:
    for z in range(maxzoom + 1):
        for x in range(1 << z):
            for y in range(1 << z):
                png, webp = (folder / str(z) / str(x) / f'{y}.{ext}' for ext in ('png', 'webp'))
                if not (png.is_file() and webp.is_file()):
                    continue
                with Image.open(png) as a, Image.open(webp) as b:
                    if not np.array_equal(np.asarray(a.convert('RGB')), np.asarray(b.convert('RGB'))):
                        errors.append(f'{png}: not the pixels of {webp.name}')


def check_pmtiles(path: Path, folder: Path, maxzoom: int, errors: list) -> None:
    from pmtiles.reader import MmapSource, Reader
    from pmtiles.tile import TileType

    with open(path, 'rb') as f:
        reader = Reader(MmapSource(f))
        header = reader.header()
        if header['tile_type'] != TileType.WEBP:
            errors.append(f'{path}: tile type {header["tile_type"]}, not WebP')
        if (header['min_zoom'], header['max_zoom']) != (0, maxzoom):
            errors.append(f'{path}: zooms {header["min_zoom"]} to {header["max_zoom"]}, not 0 to {maxzoom}')
        expected = sum(4**z for z in range(maxzoom + 1))
        if header['addressed_tiles_count'] != expected:
            errors.append(f'{path}: {header["addressed_tiles_count"]} tiles, not {expected}')
        for z in range(maxzoom + 1):
            for x in range(1 << z):
                for y in range(1 << z):
                    tile = folder / str(z) / str(x) / f'{y}.webp'
                    if tile.is_file() and reader.get(z, x, y) != tile.read_bytes():
                        errors.append(f'{path}: tile {z}/{x}/{y} is not {tile}')


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--out', help='output folder of scripts/build.py')
    p.add_argument('--name', default='ne2sr')
    p.add_argument('--folder', help='a folder of {z}/{x}/{y} tiles, in place of --out')
    p.add_argument('--maxzoom', type=int)
    p.add_argument('--tile-size', type=int, default=512)
    p.add_argument('--ext', action='append', help='png, webp (default: both)')
    p.add_argument('--no-pmtiles', action='store_true')
    p.add_argument('--lossless-png', action='store_true', help='a build with --lossless-png: the PNG and WebP tiles differ')
    args = p.parse_args(argv)

    if args.out:
        out = Path(args.out)
        folder = out / 'ofm' / args.name
        if args.maxzoom is None:
            import json

            args.maxzoom = json.loads((out / f'{args.name}.build.json').read_text())['maxzoom']
    elif args.folder:
        folder = Path(args.folder)
        args.no_pmtiles = True
    else:
        p.error('give --out or --folder')
    if args.maxzoom is None:
        p.error('give --maxzoom')

    errors: list[str] = []
    for ext in args.ext or ['png', 'webp']:
        count = check_folder(folder, args.maxzoom, args.tile_size, ext, errors)
        print(f'{folder}: {count} .{ext} tiles, zooms 0 to {args.maxzoom}', file=sys.stderr)
    if not args.ext and not args.lossless_png:
        check_same_pixels(folder, args.maxzoom, errors)
    if not args.no_pmtiles:
        check_pmtiles(Path(args.out) / f'{args.name}.pmtiles', folder, args.maxzoom, errors)

    if errors:
        for e in errors[:50]:
            print(f'error: {e}', file=sys.stderr)
        if len(errors) > 50:
            print(f'... and {len(errors) - 50} more', file=sys.stderr)
        sys.exit(f'{len(errors)} errors')
    print('All checks passed', file=sys.stderr)


if __name__ == '__main__':
    main()
