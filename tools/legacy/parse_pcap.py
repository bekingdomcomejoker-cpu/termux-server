#!/usr/bin/env python3
"""
parse_pcap.py
Scapy-based PCAP host extractor.
Extracts TLS SNI and plaintext HTTP hosts from packet captures.
"""

import argparse
import sys
from collections import defaultdict

try:
    from scapy.all import rdpcap, TCP, IP
    from scapy.layers.tls.handshake import TLSClientHello
except ImportError:
    print("Error: scapy not installed. Run: pip install scapy")
    sys.exit(1)


def extract_hosts(pcap_path: str) -> dict:
    packets = rdpcap(pcap_path)
    hosts = defaultdict(int)
    sni_hosts = set()

    for pkt in packets:
        if IP in pkt:
            # Check for TLS ClientHello SNI
            if TCP in pkt and pkt[TCP].dport == 443 or pkt[TCP].sport == 443:
                try:
                    if TLSClientHello in pkt:
                        sni = pkt[TLSClientHello].server_names[0].servername.decode("utf-8", errors="ignore")
                        if sni:
                            sni_hosts.add(sni)
                            hosts[sni] += 1
                except Exception:
                    pass

            # Check for plaintext HTTP Host header
            if TCP in pkt and pkt.haslayer("Raw"):
                try:
                    payload = pkt["Raw"].load.decode("utf-8", errors="ignore")
                    if "Host:" in payload:
                        for line in payload.split("\r\n"):
                            if line.startswith("Host:"):
                                host = line.split(":", 1)[1].strip()
                                hosts[host] += 1
                                break
                except Exception:
                    pass

    return dict(hosts), sni_hosts


def main():
    parser = argparse.ArgumentParser(description="Extract hosts from PCAP")
    parser.add_argument("pcap", help="Path to .pcap file")
    args = parser.parse_args()

    hosts, sni = extract_hosts(args.pcap)

    print("=== Extracted Hosts ===")
    for host, count in sorted(hosts.items(), key=lambda x: -x[1]):
        marker = " [SNI]" if host in sni else ""
        print(f"  {host}: {count} packets{marker}")

    if not hosts:
        print("  No hosts found. Traffic may be fully encrypted without SNI extraction.")


if __name__ == "__main__":
    main()