"""This module defines utility functions for working and converting PCAP files."""

import io
import re
import subprocess

from distutils.version import LooseVersion
from pathlib import Path
from typing import (
    Any,
    Optional,
)

import ujson

from pyshark.tshark.tshark import (
    get_process_path,
    get_tshark_version,
)


def __pcap_ecs_remove_filtered(el: Any, canary: object) -> Any:
    if isinstance(el, dict):
        # if its an empty dict return as is
        if len(el) == 0:
            return el
        # a filtered entry is a single element dict with the key filtered
        elif len(el) == 1 and "filtered" in el:
            return canary

        # normal dicts must be checked recursively
        for key in list(el.keys()):
            val = __pcap_ecs_remove_filtered(el[key], canary)
            # delete from dict if filtered otherwise update key
            # otherwise update value in case something got replaced down the recursion tree
            if val == canary:
                del el[key]
            else:
                el[key] = val
        return el if len(el) > 0 else canary
    elif isinstance(el, list):
        if len(el) == 0:
            return el
        return [
            sub_el
            for sub_el in el
            if __pcap_ecs_remove_filtered(sub_el, canary) != canary
        ]
    return el


def pcap_ecs_remove_filtered(line: str) -> str:
    """Removes any useless filtered keys from a `ek` JSON line.

    Depending on the used display and read filters the tshark
    conversion process adds `filtered` keys to fields that have
    are beeing filter through read or display filters. These markers
    do not add any value and even break the PCAP field mapping.
    As such we check for them and remove any we find.

    Args:
        line: The `ek` JSON line

    Returns:
        The modified JSON line
    """
    data = ujson.loads(line)
    # we need to re-add the line break that gets lost due to json load
    return ujson.dumps(__pcap_ecs_remove_filtered(data, object())) + "\n"


def convert_pcap_to_ecs(
    pcap: Path,
    dest: Path,
    tls_keylog: Optional[Path] = None,
    tshark_bin: Optional[Path] = None,
    remove_index_messages: bool = False,
    remove_filtered: bool = False,
    packet_summary: bool = False,
    packet_details: bool = True,
    read_filter: Optional[str] = None,
    protocol_match_filter: Optional[str] = None,
    protocol_match_filter_parent: Optional[str] = None,
):
    """Converts the given pcap file into elasticsearch compatbile format.

    Calling `convert_pcap_to_ecs(pcap, dest)` is equivalent to
    ```
    tshark -r pcap -T ek > dest
    ```

    !!! Note
        See https://www.wireshark.org/docs/man-pages/tshark.html#j-protocol-match-filter
        for details on the match filters and other options.

    Args:
        pcap: The pcap file to convert
        dest: The destination file
        tls_keylog: TLS keylog file to decrypt TLS on the fly.
        tshark_bin: Path to your tshark binary (searches in common paths if not supplied)
        remove_index_messages: If the elasticsearch bulk API index messages should be stripped from the output file.
                               Useful when using logstash or similar instead of the bulk API.
        remove_filtered: Remove filtered fields from the event dicts.
        packet_summary: If the packet summaries should be included (-P option).
        packet_details: If the packet details should be included, when packet_summary=False then details are always included (-V option).
        read_filter: The read filter to use when reading the pcap file useful to reduce the number of packets (-Y option)
        protocol_match_filter: Display filter for protocols and their fields (-J option).
                               Parent and child nodes are included for all matches lower level protocols must be added explicitly.
        protocol_match_filter_parent: Display filter for protocols and their fields. Only partent nodes are included (-j option).
    """
    # set path to tshark bin use argument or search in common paths
    tshark_path = (
        tshark_bin.absolute() if tshark_bin is not None else get_process_path()
    )
    tshark_version = get_tshark_version(tshark_path)
    args = [tshark_path, "-r", str(pcap.absolute()), "-T", "ek"]

    # configure tls keylog file for decryption
    if tls_keylog is not None:
        keylog_pref = (
            "tls.keylog_file"
            # all ssl prefs were renamed to tls with wireshark 3.0
            if tshark_version >= LooseVersion("3.0")
            else "ssl.keylog_file"
        )
        args.extend(["-o", f"{keylog_pref}:{tls_keylog.absolute()}"])

    if packet_summary:
        args.append("-P")

    if packet_details:
        args.append("-V")

    if read_filter is not None:
        args.extend(["-Y", read_filter])

    if protocol_match_filter is not None:
        args.extend(["-J", protocol_match_filter])

    if protocol_match_filter_parent is not None:
        args.extend(["-j", protocol_match_filter_parent])

    proc = subprocess.Popen(args, stdout=subprocess.PIPE)
    # regex used to skip all index lines from the bulk format
    index_regex = re.compile(r'{"index":{"_index":".*","_type":".*"}}')
    with open(dest, "w") as dest_file:
        assert proc.stdout is not None, "TShark process stdout should be available"
        for line in io.TextIOWrapper(proc.stdout, encoding="utf-8", errors='replace'):
            # when remove index is true discard all index lines
            if not remove_index_messages or not index_regex.match(line):
                if remove_filtered:
                    line = pcap_ecs_remove_filtered(line)
                dest_file.write(line)
    # ensure tshark process has finished
    proc.wait()
