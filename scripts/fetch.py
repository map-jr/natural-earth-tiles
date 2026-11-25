"""Download a Natural Earth raster named in sources.json, check its SHA-256, and unzip it.

    python scripts/fetch.py ne2sr work/src

Prints the path of the GeoTIFF. Stops when the file on the server differs from the one in sources.json: Natural Earth
has published a new version, and sources.json needs the new hash (and a new release of the tiles).
"""

import hashlib
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main(name: str, out_dir: str) -> None:
    source = json.loads((ROOT / 'sources.json').read_text())[name]
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    archive = out / Path(source['url']).name

    if not archive.is_file() or archive.stat().st_size != source['size']:
        print(f'Downloading {source["url"]}', file=sys.stderr)
        request = urllib.request.Request(source['url'], headers={'User-Agent': 'natural-earth-tiles'})
        with urllib.request.urlopen(request) as response, open(archive, 'wb') as f:
            while chunk := response.read(1 << 20):
                f.write(chunk)

    digest = hashlib.sha256()
    with open(archive, 'rb') as f:
        while chunk := f.read(1 << 20):
            digest.update(chunk)
    if digest.hexdigest() != source['sha256']:
        sys.exit(
            f'{archive.name}: SHA-256 is {digest.hexdigest()}, and sources.json has {source["sha256"]}. '
            'Natural Earth has changed the file: check it, then update sources.json.'
        )

    tif = out / source['tif']
    if not tif.is_file():
        with zipfile.ZipFile(archive) as z:
            z.extract(source['tif'], out)
    print(tif)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
