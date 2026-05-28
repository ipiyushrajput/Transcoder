import html
import re
import math
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

FLOAT_TOLERANCE = 0.05


def parse_esam_scc_xml(xml_string: str) -> list:
    """Parse ESAM Signal Conditioning Configuration XML. Returns sorted events."""
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
    """Parse MCC XML -> {acquisitionSignalID: '#EXT-X-ASSET:...'}."""
    if not xml_string or not xml_string.strip():
        return {}

    asset_tags_map = {}
    try:
        root = ET.fromstring(xml_string)
        for manifest_response in root.findall(".//ns2:ManifestResponse", MCC_NS):
            acq_id = manifest_response.get("acquisitionSignalID")
            if not acq_id:
                continue
            asset_tag = None
            for tag_el in manifest_response.findall(".//ns2:Tag", MCC_NS):
                value = tag_el.get("value")
                if value:
                    decoded = html.unescape(value)
                    m = re.search(r"(#EXT-X-ASSET:[^\n<]*)", decoded)
                    if m:
                        asset_tag = m.group(1).strip()
                        # Strip a trailing XML-comment terminator if present.
                        if asset_tag.endswith("-->"):
                            asset_tag = asset_tag[:-3].strip()
                        break
            if asset_tag:
                asset_tags_map[acq_id] = asset_tag
            else:
                logging.warning(f"No #EXT-X-ASSET tag for acquisitionSignalID '{acq_id}'")
    except ET.ParseError as e:
        logging.error(f"Failed to parse MCC XML: {e}")
        return {}
    except Exception as e:
        logging.error(f"Unexpected error parsing MCC XML: {e}")
        return {}

    logging.info(f"Parsed {len(asset_tags_map)} asset tag(s) from MCC XML")
    return asset_tags_map


def remap_esam_events_for_merged_clips(events: list, clips_sec: list) -> list:
    """Remap ESAM NPT values from the original source timeline to the
    compacted (clipped + merged) output timeline.

    clips_sec: list of (start_orig_seconds, end_orig_seconds) in source time,
    in playback order.
    """
    if not events:
        return []
    if not clips_sec:
        return list(events)

    processed = sorted(
        [(float(s), float(e)) for s, e in clips_sec if float(e) > float(s)],
        key=lambda x: x[0],
    )
    if not processed:
        return []

    remapped = []
    for ev in events:
        npt = ev["npt"]
        offset = 0.0
        new_npt = None
        for (cs, ce) in processed:
            dur = ce - cs
            if npt < cs - FLOAT_TOLERANCE:
                new_npt = offset
                break
            if cs - FLOAT_TOLERANCE <= npt < ce + FLOAT_TOLERANCE:
                new_npt = npt - cs + offset
                break
            offset += dur
        if new_npt is None:
            new_npt = offset  # beyond all clips -> end of timeline
        ev2 = dict(ev)
        ev2["npt"] = round(new_npt, 3)
        remapped.append(ev2)

    remapped.sort(key=lambda x: x["npt"])
    logging.info(f"Remapped {len(remapped)} ESAM events to compacted timeline")
    return remapped


def parse_variant_segments(m3u8_path: Path):
    """Parse an HLS media playlist.

    Returns (lines, segments, total_duration) where each segment is
    (seg_start, seg_end, seg_uri, uri_line_index).
    """
    text = Path(m3u8_path).read_text(encoding="utf-8")
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


def _has_marker_near(lines, insert_index, prefixes, window=1):
    start = max(0, insert_index - window)
    end = min(len(lines), insert_index + window + 1)
    for k in range(start, end):
        ln = lines[k].strip()
        for p in prefixes:
            if ln.startswith(p):
                return True
    return False


def _bump_segment_lines(segments, from_line, delta=1):
    for k in range(len(segments)):
        s, e, f, ln = segments[k]
        if ln >= from_line:
            segments[k] = (s, e, f, ln + delta)


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


def _find_subtitle_playlist_paths(lines, basepath: Path) -> list:
    paths = []
    for line in lines:
        ln = line.strip()
        if "TYPE=SUBTITLES" in ln:
            m = re.search(r'URI="([^"]+)"', ln)
            if m:
                paths.append((m.group(1), (basepath / m.group(1)).resolve()))
    return paths


def inject_markers_into_variant(m3u8_path: Path, events: list,
                                asset_tags_map: dict = None,
                                video_segments: list = None) -> int:
    """Inject Elemental-style ad markers into a media playlist.

    Markers are inserted on their own lines AFTER a segment URI (i.e. between
    two segments) — never between an #EXTINF and its URI. Events whose NPT
    aligns with a segment boundary are placed before that segment.

    For 0-duration breaks (point-in-time, the common ESAM case):
        #EXT-X-CUE-OUT:0
        #EXT-X-ASSET:...        (from MCC XML, keyed by acquisitionSignalID)
        #EXT-X-CUE-IN
    """
    if asset_tags_map is None:
        asset_tags_map = {}

    lines, segments, total = parse_variant_segments(m3u8_path)
    if not segments:
        logging.info(f"{Path(m3u8_path).name}: no segments, skipping ESAM")
        return 0

    # Use the video playlist's segment timing for alignment when provided; the
    # subtitle playlist aligns 1:1 with it so the segment index maps directly.
    ref_segments = video_segments if video_segments else segments

    plans = []  # (target_seg_index, event)  -- insert AFTER this segment's URI
    for ev in events:
        npt = round(ev.get("npt", 0.0), 3)
        target = None
        for idx, (sstart, send, _f, _l) in enumerate(ref_segments):
            sstart_n = round(sstart, 3)
            send_n = round(send, 3)
            if math.isclose(npt, sstart_n, abs_tol=FLOAT_TOLERANCE):
                # Boundary -> place before this segment == after the previous one.
                target = idx - 1
                break
            if sstart_n < npt < send_n + FLOAT_TOLERANCE:
                target = idx
                break
        if target is None:
            last_start = round(ref_segments[-1][0], 3)
            last_end = round(ref_segments[-1][1], 3)
            if npt >= last_start - FLOAT_TOLERANCE and npt <= last_end + FLOAT_TOLERANCE:
                target = len(ref_segments) - 1
            else:
                logging.info(f"{Path(m3u8_path).name}: signal {npt:.3f}s outside segments, skipping")
                continue
        plans.append((target, ev))

    if not plans:
        return 0

    # Insert from the back so earlier line indices stay valid.
    plans.sort(key=lambda p: p[0], reverse=True)

    inserted = 0
    for target_idx, ev in plans:
        if target_idx < 0:
            # Before the very first segment.
            insert_pos = max(0, segments[0][3] - 1)
        elif target_idx < len(segments):
            insert_pos = segments[target_idx][3] + 1  # after that segment's URI
        else:
            insert_pos = len(lines)

        if _has_marker_near(lines, insert_pos,
                            ["#EXT-X-CUE-OUT", "#EXT-X-CUE-OUT-CONT", "#EXT-X-CUE-IN"]):
            continue

        stype = str(ev.get("segmentTypeId") or "")
        dur = ev.get("duration") if ev.get("duration") is not None else 0.0
        dur = round(float(dur), 3)
        if dur < FLOAT_TOLERANCE:
            dur = 0.0

        if stype == "53":
            lines.insert(insert_pos, "#EXT-X-CUE-IN\n")
            _bump_segment_lines(segments, insert_pos)
            inserted += 1
            continue

        block = [f"#EXT-X-CUE-OUT:{'0' if dur == 0.0 else f'{dur:.3f}'}\n"]
        acq = ev.get("acquisitionSignalID")
        if acq and acq in asset_tags_map:
            block.append(f"{asset_tags_map[acq]}\n")
        if dur == 0.0:
            block.append("#EXT-X-CUE-IN\n")

        for off, tag in enumerate(block):
            lines.insert(insert_pos + off, tag)
        _bump_segment_lines(segments, insert_pos, delta=len(block))
        inserted += len(block)

        # Non-zero duration: emit CUE-OUT-CONT chain then CUE-IN.
        if dur > 0.0:
            anchor = round(segments[target_idx][0], 3) if 0 <= target_idx < len(segments) else 0.0
            j = target_idx + 1
            while j < len(segments):
                seg_start, _se, _sf, seg_line = segments[j]
                elapsed = round(round(seg_start, 3) - anchor, 3)
                pos = seg_line + 1
                if elapsed >= dur - FLOAT_TOLERANCE:
                    if not _has_marker_near(lines, pos, ["#EXT-X-CUE-IN"]):
                        lines.insert(pos, "#EXT-X-CUE-IN\n")
                        _bump_segment_lines(segments, pos)
                        inserted += 1
                    break
                cont = f"#EXT-X-CUE-OUT-CONT:{elapsed:.3f}/{dur:.3f}\n"
                if not _has_marker_near(lines, pos, ["#EXT-X-CUE-OUT-CONT"]):
                    lines.insert(pos, cont)
                    _bump_segment_lines(segments, pos)
                    inserted += 1
                j += 1

    Path(m3u8_path).write_text("".join(lines), encoding="utf-8")
    return inserted


def process_esam_on_output(output_dir: str, events: list,
                           subtitle_playlist_path: str = None,
                           mcc_xml: str = None,
                           video_segments: list = None) -> int:
    """Inject ESAM markers into all video variants and the subtitle playlist."""
    if not events:
        return 0

    asset_tags_map = parse_mcc_xml_asset_tags(mcc_xml) if mcc_xml else {}
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
        for uri, abs_path in _find_variant_paths(content, output_path):
            if abs_path.exists():
                cnt = inject_markers_into_variant(abs_path, events, asset_tags_map, video_segments)
                total += cnt
                logging.info(f"  ESAM: {uri}: {cnt} lines injected")
        for uri, abs_path in _find_subtitle_playlist_paths(content, output_path):
            if abs_path.exists():
                cnt = inject_markers_into_variant(abs_path, events, asset_tags_map, video_segments)
                total += cnt
                logging.info(f"  ESAM: subtitle {uri}: {cnt} lines injected")
    else:
        for m3u8 in output_path.glob("*.m3u8"):
            content = m3u8.read_text(encoding="utf-8").splitlines(keepends=True)
            if not _is_master_playlist(content):
                total += inject_markers_into_variant(m3u8, events, asset_tags_map, video_segments)

    if subtitle_playlist_path:
        sub_path = Path(subtitle_playlist_path)
        if sub_path.exists():
            already = False
            if master:
                content = master.read_text(encoding="utf-8").splitlines(keepends=True)
                done = [p for _, p in _find_subtitle_playlist_paths(content, output_path)]
                already = sub_path.resolve() in done
            if not already:
                total += inject_markers_into_variant(sub_path, events, asset_tags_map, video_segments)

    return total
