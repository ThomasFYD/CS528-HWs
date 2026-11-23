#!/usr/bin/env bash
# Prints the two commands and their complete responses as a terminal transcript.
set -eu
ip=${1:?Usage: ./curl-demo.sh EXTERNAL_IP}
python3 -c 'import ipaddress,sys; ipaddress.IPv4Address(sys.argv[1])' "$ip"
printf '$ curl -si --max-time 30 http://%s/data/hw9-missing.html\n' "$ip"
curl -si --max-time 30 "http://$ip/data/hw9-missing.html"
printf '\n$ curl -si --max-time 30 -X PUT http://%s/data/0.html\n' "$ip"
curl -si --max-time 30 -X PUT "http://$ip/data/0.html"
