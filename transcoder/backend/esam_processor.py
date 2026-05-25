import xml.etree.ElementTree as ET
import logging
from pathlib import Path


ESAM_NS = {
    "esam": "urn:cablelabs:iptvservices:esam:xsd:signal:1",
    "sig": "urn:cablelabs:md:xsd:signaling:3.0",
    "common": "urn:cablelabs:iptvservices:esam:xsd:common:1",
}


def parse_esam_scc_xml(xml_string: str) -> list:
    """Parse ESAM Signal Conditioning Configuration XML. Returns list of events."""
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
    logging.info(f"Parsed {len(events)} ESAM events")
    return events


def _parse_variant_segments(m3u8_path: Path):
    """Parse an HLS variant playlist and return (lines, segments, total_duration)."""
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
    for ln in lines:
        if ln.strip().startswith("#EXT-X-STREAM-INF"):
            return True
    return False


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
                abs_path = (basepath / uri).resolve()
                variants.append((uri, abs_path))
            i = j
        else:
            i += 1
    return variants


def inject_markers_into_variant(m3u8_path: Path, events: list) -> int:
    """Inject CUE-OUT/CUE-IN/CUE-OUT-CONT markers into a variant playlist. Returns count injected."""
    lines, segments, total = _parse_variant_segments(m3u8_path)
    if not segments:
        logging.info(f"{m3u8_path.name}: no segments found, skipping")
        return 0

    # Map each event to the segment it falls in
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
            else:
                logging.info(f"{m3u8_path.name}: skipping signal at {npt:.2f}s (beyond {total:.2f}s)")

    if not plans:
        return 0

    # Insert from back to front to preserve indices
    plans.sort(key=lambda x: x[0], reverse=True)

    inserted = 0
    for idx, ev in plans:
        sstart, send, sfile, sline = segments[idx]
        insert_pos = sline
        stype = ev.get("segmentTypeId")
        duration = ev.get("duration") or 30.0

        if _has_marker_near(lines, insert_pos, ["#EXT-X-CUE-OUT", "#EXT-X-CUE-IN", "#EXT-X-CUE-OUT-CONT"]):
            logging.info(f"{m3u8_path.name}: marker already exists near {sfile}")
            continue

        if stype == "53":
            lines.insert(insert_pos, "#EXT-X-CUE-IN\n")
            inserted += 1
            logging.info(f"{m3u8_path.name}: CUE-IN before {sfile} at {ev['npt']:.2f}s")
            continue

        # CUE-OUT start
        cueout_tag = f"#EXT-X-CUE-OUT:{duration:.3f}\n"
        lines.insert(insert_pos, cueout_tag)
        inserted += 1
        logging.info(f"{m3u8_path.name}: CUE-OUT({duration}) before {sfile} at {ev['npt']:.2f}s")

        # Add CUE-OUT-CONT for subsequent segments
        j = idx + 1
        while j < len(segments):
            seg_start, seg_end, seg_file, seg_line = segments[j]
            elapsed = seg_start - sstart
            if elapsed >= duration:
                if not _has_marker_near(lines, seg_line, ["#EXT-X-CUE-IN"]):
                    lines.insert(seg_line, "#EXT-X-CUE-IN\n")
                    inserted += 1
                    logging.info(f"{m3u8_path.name}: CUE-IN at elapsed {elapsed:.2f}s")
                break
            cont_tag = f"#EXT-X-CUE-OUT-CONT:{elapsed:.3f}/{int(duration)}\n"
            if not _has_marker_near(lines, seg_line, ["#EXT-X-CUE-OUT-CONT"]):
                lines.insert(seg_line, cont_tag)
                inserted += 1
            j += 1
        else:
            last_line = segments[-1][3]
            if not _has_marker_near(lines, last_line + 1, ["#EXT-X-CUE-IN"]):
                lines.insert(last_line + 1, "#EXT-X-CUE-IN\n")
                inserted += 1

    m3u8_path.write_text("".join(lines), encoding="utf-8")
    return inserted


def _find_subtitle_playlist_paths(lines, basepath: Path) -> list:
    """Find subtitle playlist URIs from #EXT-X-MEDIA:TYPE=SUBTITLES tags."""
    paths = []
    for line in lines:
        ln = line.strip()
        if ln.startswith("#EXT-X-MEDIA:TYPE=SUBTITLES") or "TYPE=SUBTITLES" in ln:
            # Extract URI="..." value
            import re
            m = re.search(r'URI="([^"]+)"', ln)
            if m:
                uri = m.group(1)
                abs_path = (basepath / uri).resolve()
                paths.append((uri, abs_path))
    return paths


def process_esam_on_output(output_dir: str, events: list, subtitle_playlist_path: str = None) -> int:
    """Process ESAM markers on all variant playlists and optionally the subtitle playlist."""
    if not events:
        return 0

    output_path = Path(output_dir)
    total = 0

    # Find master playlist
    master_candidates = list(output_path.glob("*.m3u8"))
    master = None
    for candidate in master_candidates:
        content = candidate.read_text(encoding="utf-8").splitlines(keepends=True)
        if _is_master_playlist(content):
            master = candidate
            break

    if master:
        content = master.read_text(encoding="utf-8").splitlines(keepends=True)
        variants = _find_variant_paths(content, output_path)
        logging.info(f"ESAM: processing {len(variants)} video variant(s) from master {master.name}")
        for uri, abs_path in variants:
            if abs_path.exists():
                cnt = inject_markers_into_variant(abs_path, events)
                total += cnt
                logging.info(f"  Injected {cnt} markers into {uri}")
            else:
                logging.warning(f"  Variant not found: {abs_path}")

        # Also inject into subtitle playlists referenced by #EXT-X-MEDIA
        sub_paths = _find_subtitle_playlist_paths(content, output_path)
        for uri, abs_path in sub_paths:
            if abs_path.exists():
                cnt = inject_markers_into_variant(abs_path, events)
                total += cnt
                logging.info(f"  Injected {cnt} ESAM markers into subtitle playlist {uri}")
    else:
        # No master found; process all non-master m3u8 files
        for m3u8 in master_candidates:
            content = m3u8.read_text(encoding="utf-8").splitlines(keepends=True)
            if not _is_master_playlist(content):
                cnt = inject_markers_into_variant(m3u8, events)
                total += cnt

    # Explicit subtitle playlist path (if not referenced in master yet)
    if subtitle_playlist_path:
        sub_path = Path(subtitle_playlist_path)
        if sub_path.exists():
            already_done = False
            if master:
                content = master.read_text(encoding="utf-8").splitlines(keepends=True)
                done_paths = [p for _, p in _find_subtitle_playlist_paths(content, output_path)]
                already_done = sub_path.resolve() in done_paths
            if not already_done:
                cnt = inject_markers_into_variant(sub_path, events)
                total += cnt
                logging.info(f"  Injected {cnt} ESAM markers into subtitle playlist {sub_path.name}")

    return total
