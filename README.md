# natural-earth-tiles

The shaded relief of [Natural Earth](https://www.naturalearthdata.com/) as Web Mercator raster tiles, whole at the
antimeridian, built and checked by a GitHub Action and published as GitHub releases:

- **`ne2sr.pmtiles`**: one [PMTiles](https://github.com/protomaps/PMTiles) archive of WebP tiles, to host yourself.
- **`ne2sr-ofm.tar.gz`**: the same tiles as files, as PNG and WebP, in the layout of the `natural_earth` asset of
  [OpenFreeMap](https://openfreemap.org/), so that it can take the place of that asset as it is.

The tiles of OpenFreeMap (`https://tiles.openfreemap.org/natural_earth/ne2sr/{z}/{x}/{y}.png`) have a column of
transparent pixels at 180 degrees, at zooms 0, 1, 3 and 5, and a transparent last row at about 85° S at zooms 4 and 6.
These tiles are made from the source again, and a check (`scripts/check.py`) stops a release that has such pixels.

## Download

The files of the latest release:

| File | What it is |
|---|---|
| [`ne2sr.pmtiles`](https://github.com/map-jr/natural-earth-tiles/releases/latest/download/ne2sr.pmtiles) | The WebP tiles in one PMTiles archive |
| [`ne2sr-ofm.tar.gz`](https://github.com/map-jr/natural-earth-tiles/releases/latest/download/ne2sr-ofm.tar.gz) | `ofm/ne2sr/{z}/{x}/{y}.png` and `.webp` |
| [`ne2sr.build.json`](https://github.com/map-jr/natural-earth-tiles/releases/latest/download/ne2sr.build.json) | The settings of the build and the versions of the tools |
| [`SHA256SUMS`](https://github.com/map-jr/natural-earth-tiles/releases/latest/download/SHA256SUMS) | The SHA-256 of each file |

A release is a file to download, not a tile server: host the files where a map can read them (a bucket, a static web
server or a PMTiles server).

## The tiles

| | |
|---|---|
| Source | [Natural Earth II with Shaded Relief](https://www.naturalearthdata.com/downloads/10m-raster-data/10m-natural-earth-2/), 1:10m (`NE2_HR_LC_SR.tif`, 21,600 x 10,800 pixels, version 2.0.0). Land cover and relief; the water is white, for a map that draws its own water on top. |
| Projection | Web Mercator (EPSG:3857), 85.0511° N to 85.0511° S, the usual XYZ tile scheme |
| Zooms | 0 to 6: 5,461 tiles |
| Tile size | 512 x 512 pixels |
| PNG | Lossless RGB |
| WebP | Lossy RGB, quality 80 |
| PMTiles | The WebP tiles |
| Sizes | `ne2sr.pmtiles` 25 MB (WebP); `ne2sr-ofm.tar.gz` 653 MB (627 MB of PNG, 26 MB of WebP) |

Zoom 6 is warped from the source with cubic resampling. At 512 pixels a tile of zoom 6 has about 1.2 km per pixel at
the equator, a little finer than the source (about 1.85 km), so a higher zoom would add no detail: a map draws zoom 6
larger above it. Each lower zoom is the average of 2 x 2 pixels of the zoom above.

## Use

### MapLibre GL JS with PMTiles

```js
import {Protocol} from 'pmtiles';
maplibregl.addProtocol('pmtiles', new Protocol().tile);
```

```json
"natural_earth_shaded_relief": {
  "type": "raster",
  "url": "pmtiles://https://example.com/ne2sr.pmtiles",
  "tileSize": 256
}
```

A `tileSize` of 256 draws the 512-pixel tiles at twice the pixel density of an ordinary screen, as the styles of
OpenFreeMap do. With 512, the map loads a tile one zoom lower for each place, and draws it at the density of the
screen.

### In place of the asset of OpenFreeMap

`ne2sr-ofm.tar.gz` has the paths of `https://assets.openfreemap.com/natural_earth/ofm.tar.gz`: `ofm/ne2sr/{z}/{x}/{y}.png`
and `.webp`, the same zooms and tile size. A server of OpenFreeMap downloads that archive in
`linux_host/linux_host_lib/assets.py` and serves the folder at `/natural_earth/`; this archive can be put in its place,
or that script can download it from a release here.

## Build

With Python 3.13 and GDAL in the wheels of rasterio:

```bash
pip install -r requirements.txt
```

```bash
python scripts/fetch.py ne2sr work/src
```

```bash
python scripts/build.py --source work/src/NE2_HR_LC_SR.tif --out work/out
```

```bash
python scripts/check.py --out work/out
```

`fetch.py` downloads the zip of Natural Earth, stops when its SHA-256 is not the one in `sources.json`, and unzips the
GeoTIFF. `build.py` writes `work/out/ofm/ne2sr/`, `ne2sr.pmtiles` and `ne2sr.build.json`; it takes about 15 minutes
on 4 cores, most of it in encoding the tiles. `check.py` checks every tile: each is there, is 512 x 512 pixels and
opaque, and the PMTiles archive holds the WebP tiles. It also checks any folder of tiles in the same layout:

```bash
python scripts/check.py --folder path/to/ofm/ne2sr --maxzoom 6 --no-pmtiles
```

The tests build tiles of a small synthetic world, check them, and test that they have no seam at 180 degrees:

```bash
python -m unittest discover tests -v
```

### How the edge of the world is kept whole

The source spans -180 to 180 degrees. Before the warp, `build.py` adds 16 columns from each side of the source to the
other side, so the resampling at 180 degrees reads the pixels that are really there and not only one side. A band of
255 is warped with the image, and the build stops when any pixel of zoom 6 is not covered by the source. The lower
zooms are made from zoom 6 over the whole world at once, so they have no edges of their own.

The source itself is not seamless at 180 degrees: its two sides differ at about 72° N, 10° to 20° S (around Fiji,
where the land east of 180 degrees is in coarse blocks) and 83° S. The tiles keep those differences, as the tiles of
OpenFreeMap do.

## Release

Run the workflow **Release** from the Actions tab, on `main`, with a version such as `1.0.0`. It tests, downloads the
source, builds, checks, and makes the release `v<version>` with the files above. A new version is for a new source, a
change of the tiles, or a fix.

Natural Earth has not changed its rasters in years, so the tiles are not built on a schedule. The workflow **Check
source** runs once a month: it downloads the source and fails when its SHA-256 is no longer the one in
`sources.json`. Then check the new file, update `sources.json`, and make a release.

## License

The code is under the MIT license ([LICENSE](LICENSE)). Natural Earth is in the public domain, and so are the tiles;
a credit to Natural Earth is welcome.
