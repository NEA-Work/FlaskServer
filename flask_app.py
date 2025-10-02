from flask import Flask, request, send_file, abort
import requests
import rasterio
from rasterio.io import MemoryFile
from rasterio.windows import from_bounds
from rasterio.warp import reproject, Resampling
import os

app = Flask(__name__)

WORLDCOVER_URL = (
    "https://esa-worldcover.s3.eu-central-1.amazonaws.com/"
    "v100/2020/ESA_WorldCover_10m_2020_v100_Map_AWS.vrt"
)

OPENTOPO_API_KEY = "b99aaa40b90b255e5d138d8174f9f029"


@app.route("/stack")
def get_stack():
    bbox_str = request.args.get("bbox")
    if not bbox_str:
        abort(400, "bbox parameter required: west,south,east,north")
    bbox = [float(x) for x in bbox_str.split(",")]
    if len(bbox) != 4:
        abort(400, "bbox must be west,south,east,north")

    west, south, east, north = bbox
    demtype = request.args.get("demtype", "SRTMGL1")

    with rasterio.Env(AWS_NO_SIGN_REQUEST="YES"):
        with rasterio.open(WORLDCOVER_URL) as ref:
            window = from_bounds(west, south, east, north, transform=ref.transform)
            landcover = ref.read(1, window=window)
            ref_transform = ref.window_transform(window)
            ref_crs = ref.crs
            ref_width = int(window.width)
            ref_height = int(window.height)
            ref_profile = ref.profile.copy()
            ref_profile.update({
                "height": ref_height,
                "width": ref_width,
                "transform": ref_transform,
                "crs": ref_crs,
                "count": 2
            })

    url = (
        "https://portal.opentopography.org/API/globaldem"
        f"?demtype={demtype}"
        f"&south={south}&north={north}"
        f"&west={west}&east={east}"
        f"&outputFormat=GTiff"
    )
    if OPENTOPO_API_KEY:
        url += f"&API_Key={OPENTOPO_API_KEY}"

    r = requests.get(url)
    r.raise_for_status()

    src_mem = MemoryFile(r.content)
    with src_mem.open() as dem_src:
        mem_out = MemoryFile()
        with mem_out.open(**ref_profile) as dst:
            # b1 is dem
            reproject(
                source=rasterio.band(dem_src, 1),
                destination=rasterio.band(dst, 1),
                src_transform=dem_src.transform,
                src_crs=dem_src.crs,
                dst_transform=ref_transform,
                dst_crs=ref_crs,
                resampling=Resampling.bilinear
            )
            # band 2 is the landover
            dst.write(landcover, 2)

        return send_file(mem_out, mimetype="image/tiff",
                         as_attachment=False, download_name=f"stack_{demtype}.tif")


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")
