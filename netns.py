#!/usr/bin/python3
"""Create netns/veth and route the xray netns into the host xray0 TUN."""

import os
import sys
from os import system
from time import sleep

try:
    N = int(os.environ.get("NETNS_COUNT", "1"))
except ValueError:
    sys.exit("NETNS_COUNT must be an integer")
if not 1 <= N <= 255:
    sys.exit("NETNS_COUNT must be between 1 and 255")

TUN = "xray0"
TABLE = 1001
STATE = "/run/netns.state"
IPT = "/usr/bin/iptables"


def run(cmd):
    if system(cmd) != 0:
        print("Error:", cmd)
        sys.exit(1)


def sh(cmd):
    system(f"{cmd} >/dev/null 2>&1")


def ipt(chain, spec, table=None, add=True):
    base = [IPT] + (["-t", table] if table else [])
    check = base + ["-C", chain] + spec
    if add:
        if system(" ".join(check) + " >/dev/null 2>&1") == 0:
            return
        run(" ".join(base + ["-I", chain, "1"] + spec))
        return
    for _ in range(3):
        if system(" ".join(check) + " >/dev/null 2>&1") != 0:
            return
        sh(" ".join(base + ["-D", chain] + spec))


def conf(i):
    if i == 255:
        host, peer = "10.255.1.1", "10.255.1.2"
    else:
        host, peer = f"10.{i}.0.1", f"10.{i}.0.2"
    return ("xray" if i == 1 else f"netns{i}"), f"veth{i}", host, peer


def stop():
    try:
        with open(STATE) as f:
            count, old = f.read().split()
        count = int(count)
    except Exception:
        return

    sh("ip -n xray route del default via 10.1.0.1 dev veth0")
    ipt("PREROUTING", ["-i", TUN, "-j", "ACCEPT"], "raw", False)
    ipt("FORWARD", ["-i", "veth1", "-o", TUN, "-j", "ACCEPT"], add=False)
    ipt("FORWARD", ["-i", TUN, "-o", "veth1", "-j", "ACCEPT"], add=False)
    sh("ip rule del from 10.1.0.2/32 lookup 1001 priority 1000")
    sh("ip route flush table 1001")
    if old == "0":
        sh("sysctl -w net.ipv4.ip_forward=0")

    for i in range(count, 0, -1):
        netns, host, hip, peer = conf(i)
        ipt(
            "INPUT",
            ["-i", host, "-s", peer + "/32", "-d", hip + "/32",
             "-p", "udp", "--dport", "53", "-j", "ACCEPT"],
            add=False,
        )
        sh(f"ip netns del {netns}")
        sh(f"ip link del {host}")

    try:
        os.unlink(STATE)
    except FileNotFoundError:
        pass


def start():
    stop()

    for _ in range(30):
        if system(f"ip link show {TUN} >/dev/null 2>&1") == 0:
            break
        sleep(1)
    else:
        sys.exit(f"{TUN} not found; start Xray with a tun inbound named {TUN}")

    old = open("/proc/sys/net/ipv4/ip_forward").read().strip()
    with open(STATE, "w") as f:
        f.write(f"{N} {old}\n")

    run("sysctl -w net.ipv4.ip_forward=1")
    sh("ip rule del from 10.1.0.2/32 lookup 1001 priority 1000")
    run("ip rule add from 10.1.0.2/32 lookup 1001 priority 1000")
    sh("ip route flush table 1001")
    run(f"ip route add unreachable default table 1001 metric 1000")
    run(f"ip route add default dev {TUN} table 1001 metric 0")

    for i in range(1, N + 1):
        netns, host, hip, peer = conf(i)
        tmp = f"v{i}p"
        run(f"ip netns add {netns}")
        run(f"ip -n {netns} link set lo up")
        run(f"ip link add {host} type veth peer name {tmp}")
        run(f"ip link set {tmp} netns {netns}")
        run(f"ip -n {netns} link set {tmp} name veth0")
        run(f"ip addr add {hip}/30 dev {host}")
        run(f"ip link set {host} up")
        run(f"ip -n {netns} addr add {peer}/30 dev veth0")
        run(f"ip -n {netns} link set veth0 up")

        ipt(
            "INPUT",
            ["-i", host, "-s", peer + "/32", "-d", hip + "/32",
             "-p", "udp", "--dport", "53", "-j", "ACCEPT"],
        )

        # DNS is netns-local: redirect 127.0.0.1:53 to SmartDNS on the host
        # veth address, and SNAT it to this netns's veth address.
        run(
            f"ip netns exec {netns} iptables -t nat -A OUTPUT "
            f"-d 127.0.0.1 -p udp --dport 53 "
            f"-j DNAT --to-destination {hip}:53"
        )
        run(
            f"ip netns exec {netns} iptables -t nat -A POSTROUTING "
            f"-o veth0 -s 127.0.0.1 -j SNAT --to-source {peer}"
        )
        run(
            f"ip netns exec {netns} sysctl -w "
            f"net.ipv4.conf.veth0.route_localnet=1"
        )

    ipt("FORWARD", ["-i", "veth1", "-o", TUN, "-j", "ACCEPT"])
    ipt("FORWARD", ["-i", TUN, "-o", "veth1", "-j", "ACCEPT"])
    ipt("PREROUTING", ["-i", TUN, "-j", "ACCEPT"], "raw")
    run("ip -n xray route replace default via 10.1.0.1 dev veth0")
    print("Start.")


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("start", "stop"):
        sys.exit("usage: netns.py start|stop")
    {"start": start, "stop": stop}[sys.argv[1]]()


if __name__ == "__main__":
    main()
