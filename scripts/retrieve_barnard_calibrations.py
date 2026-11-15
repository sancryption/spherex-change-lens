"""Retrieve official DataLink-listed candidates; do not equate links with UUID proof.

Products and original responses go under ignored data/derived. A compact manifest
is written to scientific/calibration_retrieval.json. Never rewrites real images.
"""

import json
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path

import requests
from astropy.io import fits
from change_lens.pipeline.calibration import DATALINK_ENDPOINT, observation_calibration_links

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data/derived/calibration_candidates"
OBSERVATIONS = ("2025W40_1A_0441_1", "2025W40_1A_0500_1")


def retrieve(link):
    path = CACHE / link["url"].rsplit("/", 1)[1]
    result = dict(link)
    try:
        if not path.exists():
            response = requests.get(link["url"], timeout=(10, 90), allow_redirects=False)
            if response.status_code != 200:
                raise ValueError(f"HTTP_{response.status_code}")
            if len(response.content) != link["size_bytes"]:
                raise ValueError("DATALINK_SIZE_MISMATCH")
            path.write_bytes(response.content)
        content = path.read_bytes()
        if len(content) != link["size_bytes"]:
            raise ValueError("CACHED_SIZE_MISMATCH")
        result.update(
            path=str(path.relative_to(ROOT)), sha256=sha256(content).hexdigest(), status="RETRIEVED"
        )
        identities = []
        if path.suffix == ".fits":
            with fits.open(path, memmap=False) as hdus:
                hdus.verify("exception")
                for hdu in hdus:
                    for key in ("UUID", "CALUUID", "PRODID", "PRODUCTID"):
                        if key in hdu.header:
                            identities.append(
                                {"hdu": hdu.name, "key": key, "value": str(hdu.header[key])}
                            )
        result["embedded_identity_fields"] = identities
        result["uuid_status"] = "UNVERIFIED_REQUIRES_AUTHORITATIVE_UUID_MAPPING"
        print(path.name, result["status"], flush=True)
    except (ValueError, OSError, requests.RequestException) as exc:
        result.update(status="UNAVAILABLE", error=str(exc))
        print(path.name, str(exc), flush=True)
    return result


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    links, observations, parents = {}, [], {}
    for obs in OBSERVATIONS:
        publisher = f"ivo://irsa.ipac/spherex_dr1?{obs}/D1"
        xml = CACHE / f"{obs}.xml"
        if not xml.exists():
            response = requests.get(
                DATALINK_ENDPOINT, params={"ID": publisher}, timeout=(10, 60), allow_redirects=False
            )
            if response.status_code != 200:
                raise ValueError(f"DATALINK_HTTP_{response.status_code}")
            xml.write_bytes(response.content)
        content = xml.read_bytes()
        found = observation_calibration_links(content, publisher)
        science = observation_calibration_links(content, publisher, semantics="#this")
        parents.update({item["url"]: item for item in science})
        observations.append(
            {
                "publisher_id": publisher,
                "datalink_sha256": sha256(content).hexdigest(),
                "product_urls": [item["url"] for item in found],
            }
        )
        links.update({item["url"]: item for item in found})
    with ThreadPoolExecutor(3) as executor:
        products = list(executor.map(retrieve, links.values()))
        parent_images = list(executor.map(retrieve, parents.values()))
    report = {
        "observations": observations,
        "products": products,
        "parent_images": parent_images,
        "uuid_mapping_verified": False,
        "limitations": [
            "DataLink calibration rows contain observation IDs, not calibration UUIDs",
            "initial_distortion_table and sband_mnemonics absent from returned calibration links",
        ],
    }
    (ROOT / "scientific/calibration_retrieval.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
