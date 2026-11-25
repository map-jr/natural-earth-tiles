"""Build tiles of a small synthetic world and check them. Run with: python -m unittest discover tests"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.transform import from_origin

ROOT = Path(__file__).resolve().parent.parent
WIDTH, HEIGHT = 720, 360


def world(path: Path) -> None:
    """An RGB image of the world in EPSG:4326 whose colors wrap around: the same on both sides of 180 degrees."""
    lon = np.radians(np.linspace(-180, 180, WIDTH, endpoint=False) + 180 / WIDTH)
    lat = np.radians(np.linspace(90, -90, HEIGHT, endpoint=False) - 90 / HEIGHT)
    lon, lat = np.meshgrid(lon, lat)
    bands = np.stack(
        [
            128 + 100 * np.sin(lon),
            128 + 100 * np.cos(2 * lat),
            128 + 60 * np.sin(3 * lon) * np.cos(lat),
        ]
    ).round().astype(np.uint8)
    with rasterio.open(
        path, 'w', driver='GTiff', width=WIDTH, height=HEIGHT, count=3, dtype='uint8', crs='EPSG:4326',
        transform=from_origin(-180, 90, 360 / WIDTH, 180 / HEIGHT),
    ) as dst:
        dst.write(bands)


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True)


class Pipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        world(cls.dir / 'world.tif')
        cls.out = cls.dir / 'out'
        cls.build = run('scripts/build.py', '--source', str(cls.dir / 'world.tif'), '--out', str(cls.out),
                        '--maxzoom', '2', '--tile-size', '256', '--workers', '2')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def check(self, *extra: str) -> subprocess.CompletedProcess:
        return run('scripts/check.py', '--out', str(self.out), '--tile-size', '256', *extra)

    def test_build_and_check(self):
        self.assertEqual(self.build.returncode, 0, self.build.stderr)
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('21 .png tiles', result.stderr)
        self.assertIn('21 .webp tiles', result.stderr)

    def test_no_seam_at_180_degrees(self):
        # The synthetic world has no seam at 180 degrees, so the tiles must have none: the last column of the last tile
        # of a row and the first column of its first tile differ no more than the columns next to them. (The rasters of
        # Natural Earth have seams of their own at 180 degrees, so this is a test of the build, not a check of a release.)
        for z in range(3):
            n = 1 << z
            for y in range(n):
                tile = lambda x: np.asarray(Image.open(self.out / 'ofm/ne2sr' / str(z) / str(x) / f'{y}.png')).astype(int)
                last, first = tile(n - 1), tile(0)
                across = np.abs(last[:, -1] - first[:, 0]).mean()
                beside = max(np.abs(last[:, -1] - last[:, -2]).mean(), np.abs(first[:, 1] - first[:, 0]).mean())
                self.assertLess(across, 2 * beside + 1, f'zoom {z}, row {y}')

    def test_check_finds_a_clear_column(self):
        # A tile with a transparent last column, as in the tiles of OpenFreeMap: the check must fail.
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for z in range(2):
                for x in range(1 << z):
                    for y in range(1 << z):
                        tile = folder / str(z) / str(x)
                        tile.mkdir(parents=True, exist_ok=True)
                        rgba = np.full((256, 256, 4), 200, dtype=np.uint8)
                        rgba[:, :, 3] = 255
                        if x == (1 << z) - 1:
                            rgba[:, -1, 3] = 0
                        Image.fromarray(rgba, 'RGBA').save(tile / f'{y}.png')
            result = run('scripts/check.py', '--folder', str(folder), '--maxzoom', '1', '--tile-size', '256',
                         '--ext', 'png')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('0/0/0.png: 256 pixels are not opaque (rows 0 to 255, column 255)', result.stderr)


if __name__ == '__main__':
    unittest.main()
