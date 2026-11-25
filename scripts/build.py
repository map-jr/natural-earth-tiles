"""Make raster tiles of a Natural Earth raster: Web Mercator, a full pyramid from zoom 0 to --maxzoom.

    python scripts/build.py --source work/src/NE2_HR_LC_SR_W_DR.tif --out work/out

Writes, under --out:

    ofm/<name>/{z}/{x}/{y}.png    lossless, in the layout of the natural_earth asset of OpenFreeMap
    ofm/<name>/{z}/{x}/{y}.webp   lossy, the same tiles
    <name>.pmtiles                the WebP tiles as one PMTiles archive
    <name>.build.json             the settings and the versions of the tools

How the edge of the world is kept whole: the source is an image in longitude and latitude from -180 to 180. A warp to
Web Mercator that reads it as it is has nothing to read past +-180: the resampling kernel at the edge sees only one
side, and a tool can leave the last column empty (the tiles of OpenFreeMap have such a column at 180 degrees). So the
source is first padded with --pad columns from its other side (the image wraps around the world), and the warp reads
real pixels on both sides of the antimeridian. A band of 255 is warped with the image: the build stops when any pixel
of the result has less than full coverage. scripts/check.py then checks the tiles themselves.

The highest zoom is warped from the source (cubic). Each lower zoom is the average of 2 x 2 pixels of the zoom above,
over the whole world, so a tile at a lower zoom is the same as the four tiles under it, without seams.
"""

import argparse
import json
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import PIL
import rasterio
from PIL import Image
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject

# Half the width of the world in Web Mercator (EPSG:3857), in meters.
EXTENT = 20037508.342789244
MAX_LAT = math.degrees(math.atan(math.sinh(math.pi)))


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--source', required=True, help='GeoTIFF in EPSG:4326 that covers the whole world')
    p.add_argument('--out', required=True, help='output folder')
    p.add_argument('--name', default='ne2sr', help='name of the tile set (default: ne2sr)')
    p.add_argument('--title', default='Natural Earth II with Shaded Relief')
    p.add_argument('--maxzoom', type=int, default=6)
    p.add_argument('--tile-size', type=int, default=512)
    p.add_argument('--pad', type=int, default=16, help='columns of the source wrapped around each side')
    p.add_argument('--webp-quality', type=int, default=80)
    p.add_argument('--workers', type=int, default=os.cpu_count())
    return p.parse_args(argv)


def read_source(path: str, pad: int):
    """The source as (4, height, width + 2 * pad): RGB and a band of 255, wrapped by `pad` columns on each side."""
    with rasterio.open(path) as src:
        if src.count < 3:
            sys.exit(f'{path}: {src.count} bands; an RGB image is needed')
        if src.crs is None or src.crs.to_epsg() != 4326:
            sys.exit(f'{path}: the CRS is {src.crs}; EPSG:4326 is needed')
        b = src.bounds
        if abs(b.left + 180) > 1e-6 or abs(b.right - 180) > 1e-6:
            sys.exit(f'{path}: spans {b.left} to {b.right}; -180 to 180 is needed')
        rgb = src.read([1, 2, 3])
        height, width = src.height, src.width
        top, bottom = b.top, b.bottom

    # The GeoTIFFs of Natural Earth round the pixel size (0.01666666666667): use the exact size of a whole world.
    res_x = 360 / width
    res_y = (top - bottom) / height
    data = np.empty((4, height, width + 2 * pad), dtype=np.uint8)
    data[:3, :, pad : pad + width] = rgb
    data[:3, :, :pad] = rgb[:, :, width - pad :]
    data[:3, :, pad + width :] = rgb[:, :, :pad]
    data[3] = 255
    transform = from_origin(-180 - pad * res_x, top, res_x, res_y)
    return data, transform


def halve(a: np.ndarray) -> np.ndarray:
    """(h, w, 3) -> (h/2, w/2, 3): the rounded average of each 2 x 2 pixels."""
    s = a.astype(np.uint16)
    s = s[0::2, 0::2] + s[1::2, 0::2] + s[0::2, 1::2] + s[1::2, 1::2]
    return ((s + 2) >> 2).astype(np.uint8)


def write_tile(folder: str, z: int, x: int, y: int, rgb: np.ndarray, webp_quality: int) -> None:
    d = Path(folder) / str(z) / str(x)
    d.mkdir(parents=True, exist_ok=True)
    image = Image.fromarray(rgb, 'RGB')
    image.save(d / f'{y}.png', 'PNG', optimize=True)
    image.save(d / f'{y}.webp', 'WEBP', quality=webp_quality, method=6)


def write_tiles(pool, folder, z, row0, image, tile_size, webp_quality):
    """Write each tile of `image`, a band of rows of zoom z whose first tile row is row0."""
    futures = []
    for ty in range(image.shape[0] // tile_size):
        for tx in range(image.shape[1] // tile_size):
            tile = image[ty * tile_size : (ty + 1) * tile_size, tx * tile_size : (tx + 1) * tile_size]
            futures.append(pool.submit(write_tile, folder, z, tx, row0 + ty, np.ascontiguousarray(tile), webp_quality))
    for f in futures:
        f.result()


def build(args) -> None:
    out = Path(args.out)
    folder = out / 'ofm' / args.name
    ts = args.tile_size
    size = ts << args.maxzoom
    res = 2 * EXTENT / size

    print(f'Reading {args.source}', file=sys.stderr)
    src, src_transform = read_source(args.source, args.pad)

    # The zooms below the highest, filled band by band as the highest is warped.
    lower = {z: np.empty((ts << z, ts << z, 3), dtype=np.uint8) for z in range(args.maxzoom)}

    # Bands of rows, each a whole number of tile rows of every zoom down to the one that has a single row.
    band_rows = ts
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for row0 in range(0, size, band_rows):
            dst = np.zeros((4, band_rows, size), dtype=np.uint8)
            reproject(
                source=src,
                src_transform=src_transform,
                src_crs='EPSG:4326',
                destination=dst,
                dst_transform=from_origin(-EXTENT, EXTENT - row0 * res, res, res),
                dst_crs='EPSG:3857',
                resampling=Resampling.cubic,
                num_threads=args.workers,
            )
            uncovered = int(np.count_nonzero(dst[3] != 255))
            if uncovered:
                sys.exit(f'Rows {row0} to {row0 + band_rows} of zoom {args.maxzoom}: {uncovered} pixels are not covered by the source')

            image = np.ascontiguousarray(np.moveaxis(dst[:3], 0, -1))
            write_tiles(pool, folder, args.maxzoom, row0 // ts, image, ts, args.webp_quality)

            z, r = args.maxzoom, row0
            while z > 0:
                image = halve(image)
                z, r = z - 1, r // 2
                lower[z][r : r + image.shape[0]] = image
            print(f'  zoom {args.maxzoom}: tile row {row0 // ts + 1} of {size // ts}', file=sys.stderr)

        for z in range(args.maxzoom - 1, -1, -1):
            print(f'  zoom {z}', file=sys.stderr)
            write_tiles(pool, folder, z, 0, lower.pop(z), ts, args.webp_quality)

    write_pmtiles(args, folder, out / f'{args.name}.pmtiles')

    (out / f'{args.name}.build.json').write_text(
        json.dumps(
            {
                'name': args.name,
                'source': Path(args.source).name,
                'minzoom': 0,
                'maxzoom': args.maxzoom,
                'tile_size': ts,
                'pad': args.pad,
                'resampling': 'cubic warp to the highest zoom, 2x2 average for each lower zoom',
                'webp_quality': args.webp_quality,
                'tools': {
                    'rasterio': rasterio.__version__,
                    'gdal': rasterio.__gdal_version__,
                    'pillow': PIL.__version__,
                    'numpy': np.__version__,
                },
            },
            indent=2,
        )
        + '\n'
    )


def write_pmtiles(args, folder: Path, path: Path) -> None:
    from pmtiles.tile import Compression, TileType, zxy_to_tileid
    from pmtiles.writer import Writer

    print(f'Writing {path}', file=sys.stderr)
    tiles = sorted(
        (zxy_to_tileid(z, x, y), z, x, y) for z in range(args.maxzoom + 1) for x in range(1 << z) for y in range(1 << z)
    )
    with open(path, 'wb') as f:
        writer = Writer(f)
        for tile_id, z, x, y in tiles:
            writer.write_tile(tile_id, (folder / str(z) / str(x) / f'{y}.webp').read_bytes())
        writer.finalize(
            {
                'tile_type': TileType.WEBP,
                'tile_compression': Compression.NONE,
                'min_lon_e7': -1800000000,
                'min_lat_e7': int(-MAX_LAT * 1e7),
                'max_lon_e7': 1800000000,
                'max_lat_e7': int(MAX_LAT * 1e7),
                'center_zoom': 0,
                'center_lon_e7': 0,
                'center_lat_e7': 0,
            },
            {
                'name': args.title,
                'description': f'{args.title}, 1:10m, from Natural Earth. Tiles of {args.tile_size} pixels.',
                'attribution': '<a href="https://www.naturalearthdata.com/">Natural Earth</a>',
                'type': 'baselayer',
                'format': 'webp',
                'tileSize': args.tile_size,
            },
        )


if __name__ == '__main__':
    build(parse_args())
