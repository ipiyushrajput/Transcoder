import html
import re
import xml.etree.ElementTree as ET
import logging
from pathlib import Path


ESAM_NS = {
    "esam": "urn:cablelabs:iptvservices:esam:xsd:signal:1",
    "sig": "urn:cablelabs:md:xsd:signaling:3.0",
    "common": "urn:cablelabs:iptvservices:esam:xsd:common:1",
}

MCC_NS = {
    "ns2": "http://www.cablelabs.com/namespaces/metadata/xsd/confirmation/2",
    "ns3": "http://www.cablelabs.com/namespaces/metadata/xsd/signaling/2",
}


def parse_esam_scc_xml(xml_string: str) -> list:
    """Parse ESAM Signal Conditioning Configuration XML. Returns sorted list of events."""
    if not xml_string or not xml_string.strip():
        return []
    try:
        root = ET.fromstring(xml_string)
    except ET.ParseError as e:
        logging.error(f"Failed to parse ESAM SCC XML: {e}")
        return []

    events = []
    for rs in root.findall(".//esam:ResponseSignal", ESAM_NS):
        point = rs.find("sig:NPTPoint", ESAM_NS)
        seginfo = rs.find("sig:SCTE35PointDescriptor/sig:SegmentationDescriptorInfo", ESAM_NS)
        if point is None:
            continue
        try:
            npt = float(point.get("nptPoint"))
        except (ValueError, TypeError):
            continue

        ev = {
            "npt": npt,
            "duration": None,
            "segmentTypeId": None,
            "segmentEventId": None,
            "acquisitionSignalID": rs.get("acquisitionSignalID"),
        }

        if seginfo is not None:
            dur_str = seginfo.get("duration") or seginfo.get("Duration")
            if dur_str and dur_str.startswith("PT") and dur_str.endswith("S"):
                try:
                    ev["duration"] = float(dur_str[2:-1])
                except ValueError:
                    pass
            ev["segmentTypeId"] = seginfo.get("segmentTypeId")
            ev["segmentEventId"] = seginfo.get("segmentEventId")

        events.append(ev)

    events.sort(key=lambda x: x["npt"])
    logging.info(f"Parsed {len(events)} ESAM events from SCC XML")
    return events


def parse_mcc_xml_asset_tags(xml_string: str) -> dict:
    """
    Parse ESAM Manifest Confirm Condition XML.
    Returns {acquisitionSignalID: '#EXT-X-ASSET:...'} map.
    """
    if not xml_string or not xml_string.strip():
        logging.warning("MCC XML is empty, returning empty asset tags map")
        return {}

    asset_tags_map = {}
    try:
        root = ET.fromstring(xml_string)
        for manifest_response in root.findall(".//ns2:ManifestResponse", MCC_NS):
            acq_id = manifest_response.get("acquisitionSignalID")
            if not acq_id:
                logging.warning("MCC ManifestResponse missing acquisitionSignalID, skipping")
                continue

            asset_tag = None
            for tag_el in manifest_response.findall(".//ns2:Tag", MCC_NS):
                value = tag_el.get("value")
                if value:
                    decoded = html.unescape(value)
                    m = re.search(r"(#EXT-X-ASSET:[^\n<]*)", decoded)
                    if m:
                        asset_tag = m.group(1).strip().rstrip("-->").strip()
                        break

            if asset_tag:
                asset_tags_map[acq_id] = asset_tag
                logging.debug(f"MCC asset tag for {acq_id}: {asset_tag}")
            else:
                logging.warning(f"No #EXT-X-ASSET tag found for acquisitionSignalID '{acq_id}'")

    except ET.ParseError as e:
        logging.error(f"Failed to parse MCC XML: {e}")
        return {}
    except Exception as e:
        logging.error(f"Unexpected error parsing MCC XML: {e}")
        return {}

    logging.info(f"Parsed {len(asset_tags_map)} asset tag(s) from MCC XML")
    return asset_tags_map


def parse_variant_segments(m3u8_path: Path):
    """Parse an HLS variant playlist. Returns (lines, segments, total_duration)."""
    text = m3u8_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    segments = []
    total = 0.0
    i = 0
    while i < len(lines):
        ln = lines[i].strip()
        if ln.startswith("#EXTINF:"):
            try:
                dur = float(ln.split(":", 1)[1].split(",", 1)[0])
            except (ValueError, IndexError):
                dur = 0.0
            if i + 1 < len(lines):
                seg_file = lines[i + 1].strip()
                segments.append((total, total + dur, seg_file, i + 1))
            total += dur
            i += 2
        else:
            i += 1
    return lines, segments, total


def _has_marker_near(lines, insert_index, prefixes):
    start = max(0, insert_index - 3)
    end = min(len(lines), insert_index + 2)
    for k in range(start, end):
        ln = lines[k].strip()
        for p in prefixes:
            if ln.startswith(p):
                return True
    return False


def _is_master_playlist(lines) -> bool:
    return any(ln.strip().startswith("#EXT-X-STREAM-INF") for ln in lines)


def _find_variant_paths(lines, basepath: Path) -> list:
    variants = []
    i = 0
    while i < len(lines):
        ln = lines[i].strip()
        if ln.startswith("#EXT-X-STREAM-INF"):
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines):
                uri = lines[j].strip()
                variants.append((uri, (basepath / uri).resolve()))
            i = j
        else:
            i += 1
    return variants


def inject_markers_into_variant(m3u8_path: Path, events: list, asset_tags_map: dict = None) -> int:
    """
    Inject ESAM ad markers into a variant playlist using Elemental-style format:
      #EXT-X-CUE-OUT:0
      #EXT-X-ASSET:CAID=...,... (from MCC XML)
      #EXT-X-CUE-IN
    Returns count of marker lines inserted.
    """
    if asset_tags_map is None:
        asset_tags_map = {}

    lines, segments, total = parse_variant_segments(m3u8_path)
    if not segments:
        logging.info(f"{m3u8_path.name}: no segments found, skipping ESAM injection")
        return 0

    # Map each event to a segment index
    plans = []
    for ev in events:
        npt = ev["npt"]
        matched = False
        for idx, (sstart, send, sfile, sline) in enumerate(segments):
            if sstart <= npt < send:
                plans.append((idx, ev))
                matched = True
                break
        if not matched:
            if npt <= total:
                plans.append((len(segments) - 1, ev))

    if not plans:
        return 0

    plans.sort(key=lambda x: x[0], reverse=True)

    inserted = 0
    for idx, ev in plans:
        sstart, send, sfile, sline = segments[idx]
        insert_pos = sline  # Insert before the segment URI line
        stype = str(ev.get("segmentTypeId", ""))

        marker_prefixes = ["#EXT-X-CUE-OUT", "#EXT-X-CUE-IN", "#EXT-X-ASSET"]
        if _has_marker_near(lines, insert_pos, marker_prefixes):
            logging.info(f"{m3u8_path.name}: marker already near {sfile}, skipping")
            continue

        if stype == "53":
            lines.insert(insert_pos, "#EXT-X-CUE-IN\n")
            inserted += 1
            logging.info(f"{m3u8_path.name}: CUE-IN before {sfile} at {ev['npt']:.3f}s")
            continue

        # Elemental-style: CUE-OUT:0 + optional ASSET tag + CUE-IN (point-in-time)
        acq_id = ev.get("acquisitionSignalID")
        lines_to_insert = ["#EXT-X-CUE-OUT:0\n"]
        if acq_id and acq_id in asset_tags_map:
            lines_to_insert.append(f"{asset_tags_map[acq_id]}\n")
        lines_to_insert.append("#EXT-X-CUE-IN\n")

        for offset, tag in enumerate(lines_to_insert):
            lines.insert(insert_pos + offset, tag)
        inserted += len(lines_to_insert)
        logging.info(f"{m3u8_path.name}: CUE-OUT:0 + CUE-IN before {sfile} at {ev['npt']:.3f}s (acq={acq_id})")

    m3u8_path.write_text("".join(lines), encoding="utf-8")
    return inserted


def _find_subtitle_playlist_paths(lines, basepath: Path) -> list:
    """Extract subtitle playlist paths from #EXT-X-MEDIA:TYPE=SUBTITLES lines."""
    paths = []
    for line in lines:
        ln = line.strip()
        if "TYPE=SUBTITLES" in ln:
            m = re.search(r'URI="([^"]+)"', ln)
            if m:
                uri = m.group(1)
                paths.append((uri, (basepath / uri).resolve()))
    return paths


def process_esam_on_output(
    output_dir: str,
    events: list,
    subtitle_playlist_path: str = None,
    mcc_xml: str = None,
) -> int:
    """Inject ESAM markers into all variant playlists (and subtitle playlist if present)."""
    if not events:
        return 0

    asset_tags_map = {}
    if mcc_xml:
        asset_tags_map = parse_mcc_xml_asset_tags(mcc_xml)

    output_path = Path(output_dir)
    total = 0

    master = None
    for candidate in output_path.glob("*.m3u8"):
        content = candidate.read_text(encoding="utf-8").splitlines(keepends=True)
        if _is_master_playlist(content):
            master = candidate
            break

    if master:
        content = master.read_text(encoding="utf-8").splitlines(keepends=True)
        variants = _find_variant_paths(content, output_path)
        logging.info(f"ESAM: {len(variants)} video variant(s) from {master.name}")
        for uri, abs_path in variants:
            if abs_path.exists():
                cnt = inject_markers_into_variant(abs_path, events, asset_tags_map)
                total += cnt
                logging.info(f"  {uri}: {cnt} markers injected")
            else:
                logging.warning(f"  Variant not found: {abs_path}")

        sub_paths = _find_subtitle_playlist_paths(content, output_path)
        for uri, abs_path in sub_paths:
            if abs_path.exists():
                cnt = inject_markers_into_variant(abs_path, events, asset_tags_map)
                total += cnt
                logging.info(f"  subtitle {uri}: {cnt} markers injected")
    else:
        for m3u8 in output_path.glob("*.m3u8"):
            content = m3u8.read_text(encoding="utf-8").splitlines(keepends=True)
            if not _is_master_playlist(content):
                cnt = inject_markers_into_variant(m3u8, events, asset_tags_map)
                total += cnt

    if subtitle_playlist_path:
        sub_path = Path(subtitle_playlist_path)
        if sub_path.exists():
            already_done = False
            if master:
                content = master.read_text(encoding="utf-8").splitlines(keepends=True)
                done = [p for _, p in _find_subtitle_playlist_paths(content, output_path)]
                already_done = sub_path.resolve() in done
            if not already_done:
                cnt = inject_markers_into_variant(sub_path, events, asset_tags_map)
                total += cnt
                logging.info(f"  subtitle {sub_path.name}: {cnt} markers injected (explicit)")

    return total
