"""Independent IRSA product provenance. Never synthesize a CALVER header.

UUID agreement between observations is not verification. Verification requires
HTTPS bytes from IRSA, a matching embedded UUID, and a retained SHA-256 digest.
No filename/version-to-UUID mapping is inferred.
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

import requests
from astropy.io import fits


@dataclass(frozen=True)
class CalibrationReference:
    role: str
    uuid: str


@dataclass(frozen=True)
class VerifiedCalibration:
    reference: CalibrationReference
    url: str
    product_id: str
    sha256: str
    size_bytes: int
    identity_evidence: tuple[str, ...]
    datalink_xml: str | None = None

    def to_dict(self):
        return asdict(self)


def history_calibrations(history) -> tuple[CalibrationReference, ...]:
    """Preserve distinct dependencies, reject malformed CALIB entries."""
    if isinstance(history, str):
        history = [history]
    result = []
    for line in history or ():
        if "[CALIB]" not in line:
            continue
        match = re.fullmatch(r"\s*\[CALIB\]\s+(\w+)\s+([\da-fA-F-]{36})\s*", line)
        if not match:
            raise ValueError("MALFORMED_CALIBRATION_HISTORY")
        ref = CalibrationReference(match[1], str(UUID(match[2])))
        if ref not in result:
            result.append(ref)
    return tuple(result)


def require_irsa_url(url: str):
    parsed = urlparse(url)
    official_path = (
        parsed.hostname == "irsa.ipac.caltech.edu"
        and parsed.path.startswith("/ibe/data/spherex/dr1/")
    ) or (
        parsed.hostname
        in ("nasa-irsa-spherex.s3.amazonaws.com", "nasa-irsa-spherex.s3.us-east-1.amazonaws.com")
        and parsed.path.startswith("/dr1/")
    )
    if (
        parsed.scheme != "https"
        or not official_path
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("AUTHORITATIVE_DR1_PRODUCT_URL_REQUIRED")


S3_ROOT = "https://nasa-irsa-spherex.s3.amazonaws.com/"
DATALINK_ENDPOINT = "https://irsa.ipac.caltech.edu/datalink/links/spherex"


def list_s3_candidates(role: str, detector: int):
    """List official DR1 keys anonymously, including pagination; not verification."""
    if not re.fullmatch(r"[a-z][a-z0-9_]*", role) or detector not in range(1, 7):
        raise ValueError("INVALID_CALIBRATION_QUERY")
    prefix = f"dr1/{role}/"
    params = {"list-type": "2", "prefix": prefix}
    keys, seen = [], set()
    ns = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
    while True:
        response = requests.get(S3_ROOT, params=params, timeout=(10, 60), allow_redirects=False)
        if response.status_code != 200:
            raise ValueError(f"CALIBRATION_LIST_UNAVAILABLE:HTTP_{response.status_code}")
        root = ET.fromstring(response.content)
        if root.findtext("s:Name", namespaces=ns) != "nasa-irsa-spherex":
            raise ValueError("UNEXPECTED_CALIBRATION_BUCKET")
        for entry in root.findall("s:Contents", ns):
            key = entry.findtext("s:Key", namespaces=ns)
            if (
                key
                and key.startswith(prefix)
                and (f"_D{detector}_" in key or role == "gain_factors")
            ):
                keys.append(
                    {
                        "url": S3_ROOT + key,
                        "size_bytes": int(entry.findtext("s:Size", namespaces=ns)),
                        "etag": entry.findtext("s:ETag", namespaces=ns),
                        "uuid_verified": False,
                    }
                )
        if root.findtext("s:IsTruncated", namespaces=ns) != "true":
            return keys
        token = root.findtext("s:NextContinuationToken", namespaces=ns)
        if not token or token in seen:
            raise ValueError("INVALID_S3_PAGINATION")
        seen.add(token)
        params["continuation-token"] = token


def parse_datalink_calibration(content: bytes, ref: CalibrationReference):
    """Require exact calibration UUID in DataLink ID, never infer from a filename.

    Observation-level links without the calibration's own ID are discovery only.
    The response hash permits retention/audit of the authoritative association.
    This parser does not by itself mark downloaded calibration bytes verified.
    """
    from astropy.io.votable import parse_single_table

    root = ET.fromstring(content)
    for element in root.iter():
        if (
            element.tag.rsplit("}", 1)[-1] == "INFO"
            and element.get("name") == "QUERY_STATUS"
            and element.get("value") != "OK"
        ):
            raise ValueError("DATALINK_QUERY_ERROR:" + (element.text or ""))
    try:
        table = parse_single_table(BytesIO(content)).to_table(use_names_over_ids=True)
    except (IndexError, ValueError) as exc:
        raise ValueError("INVALID_DATALINK_SCHEMA") from exc
    if "id" in table.colnames and "ID" not in table.colnames:
        table.rename_column("id", "ID")
    required = {"ID", "access_url", "semantics"}
    if not required.issubset(table.colnames):
        raise ValueError("INVALID_DATALINK_SCHEMA")
    matches = []
    for row in table:
        identifier = str(row["ID"])
        if identifier not in (ref.uuid, f"ivo://irsa.ipac/spherex_dr1_cal?{ref.uuid}"):
            continue
        if (
            "error_message" in table.colnames
            and not getattr(row["error_message"], "mask", False)
            and str(row["error_message"]).strip()
        ):
            continue
        if str(row["semantics"]) not in ("#this", "http://www.ivoa.net/rdf/datalink/core#this"):
            continue
        url = str(row["access_url"])
        require_irsa_url(url)
        if not Path(urlparse(url).path).name.startswith(ref.role + "_"):
            raise ValueError("CALIBRATION_ROLE_MISMATCH")
        matches.append(url)
    if len(set(matches)) != 1:
        raise ValueError("CALIBRATION_DATALINK_ID_UNVERIFIED")
    return {
        "reference": asdict(ref),
        "url": matches[0],
        "response_sha256": sha256(content).hexdigest(),
        "identity_method": "exact-calibration-ID-and-this-link",
    }


def query_datalink_calibration(ref: CalibrationReference, identifier: str):
    """Query an actual publisher ID obtained from SIA, not an invented UUID URL."""
    response = requests.get(
        DATALINK_ENDPOINT, params={"ID": identifier}, timeout=(10, 60), allow_redirects=False
    )
    if response.status_code != 200:
        raise ValueError(f"CALIBRATION_DATALINK_UNAVAILABLE:HTTP_{response.status_code}")
    return parse_datalink_calibration(response.content, ref), response.content


def observation_calibration_links(
    content: bytes, publisher_id: str, *, semantics: str = "#calibration"
):
    """Discover links tied to one observation; this alone does not resolve UUIDs."""
    import json

    from astropy.io.votable import parse_single_table

    table = parse_single_table(BytesIO(content)).to_table(use_names_over_ids=True)
    if "id" in table.colnames and "ID" not in table.colnames:
        table.rename_column("id", "ID")
    links = []
    for row in table:
        if str(row["ID"]) != publisher_id or str(row["semantics"]) != semantics:
            continue
        url = str(row["access_url"])
        require_irsa_url(url)
        cloud = json.loads(str(row["cloud_access"]))["aws"]
        if cloud["bucket_name"] != "nasa-irsa-spherex" or cloud["region"] != "us-east-1":
            raise ValueError("UNEXPECTED_CALIBRATION_BUCKET")
        s3_url = S3_ROOT + cloud["key"]
        require_irsa_url(s3_url)
        if urlparse(url).path.removeprefix("/ibe/data/spherex/") != cloud["key"]:
            raise ValueError("DATALINK_MIRROR_KEY_MISMATCH")
        links.append(
            {
                "url": s3_url,
                "irsa_url": url,
                "product_id": str(row["description"]),
                "size_bytes": int(row["content_length"]),
                "publisher_id": publisher_id,
                "datalink_sha256": sha256(content).hexdigest(),
                "uuid_verified": False,
            }
        )
    return links


def _verify_bytes(
    ref: CalibrationReference, url: str, content: bytes, datalink_xml: str | None = None
):
    require_irsa_url(url)
    name = Path(urlparse(url).path).name
    if not name.startswith(ref.role + "_"):
        raise ValueError("CALIBRATION_ROLE_MISMATCH")
    evidence = []
    if datalink_xml is not None:
        association = parse_datalink_calibration(datalink_xml.encode("utf-8"), ref)

        def product_key(value):
            return urlparse(value).path.removeprefix("/ibe/data/spherex").lstrip("/")

        if product_key(association["url"]) != product_key(url):
            raise ValueError("CALIBRATION_DATALINK_PRODUCT_MISMATCH")
        evidence.append("DataLink:exact-ID:" + association["response_sha256"])
    if name.endswith(".fits"):
        with fits.open(BytesIO(content), memmap=False) as hdus:
            hdus.verify("exception")
            # Only identity fields count; a dependency in HISTORY does not.
            for hdu in hdus:
                for key in ("UUID", "CALUUID", "PRODID", "PRODUCTID"):
                    if str(hdu.header.get(key, "")).strip().lower() == ref.uuid:
                        evidence.append(f"{hdu.name}:{key}={ref.uuid}")
    elif datalink_xml is None:
        # Unknown text schemas must acquire a dedicated parser, not a UUID grep.
        raise ValueError("UNSUPPORTED_CALIBRATION_IDENTITY_SCHEMA")
    if not evidence:
        raise ValueError("CALIBRATION_UUID_NOT_VERIFIED")
    return VerifiedCalibration(
        ref, url, name, sha256(content).hexdigest(), len(content), tuple(evidence), datalink_xml
    )


def fetch_calibration(
    ref: CalibrationReference, url: str, destination: Path, *, datalink_xml: str | None = None
):
    """Download a specified official product; write only verified bytes.

    Caller supplies URLs from IRSA directory/catalogue evidence. Redirects are
    refused so provenance cannot silently cross hosts. Local FITS remain ignored.
    """
    require_irsa_url(url)
    response = requests.get(url, timeout=(10, 60), allow_redirects=False)
    if response.status_code != 200:
        raise ValueError(f"CALIBRATION_PRODUCT_UNAVAILABLE:HTTP_{response.status_code}")
    verified = _verify_bytes(ref, url, response.content, datalink_xml)
    destination = Path(destination)
    if destination.suffix.lower() not in (".fits", ".yaml", ".ecsv"):
        raise ValueError("SUPPORTED_CALIBRATION_DESTINATION_REQUIRED")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and sha256(destination.read_bytes()).hexdigest() != verified.sha256:
        raise ValueError("CALIBRATION_CACHE_CONFLICT")
    destination.write_bytes(response.content)
    return verified


def check_cached_product(product: VerifiedCalibration, path: Path):
    """Recheck bytes and embedded identity before scientific consumption."""
    checked = _verify_bytes(
        product.reference, product.url, Path(path).read_bytes(), product.datalink_xml
    )
    if checked != product:
        raise ValueError("CALIBRATION_CONTENT_MISMATCH")
    return checked


def calibration_reasons(history, products: tuple[VerifiedCalibration, ...]):
    try:
        refs = history_calibrations(history)
    except (ValueError, TypeError):
        return ("CALIBRATION_HISTORY_MALFORMED",)
    if not refs:
        return ("CALIBRATION_HISTORY_MISSING",)
    return tuple(
        f"CALIBRATION_UNVERIFIED:{r.role}:{r.uuid}"
        for r in refs
        if not any(p.reference == r for p in products)
    )
