#!/usr/bin/env bash
# Asks for the instance the way a stranger would and fails if it answers. Run
# it from a machine that is NOT on the tailnet: the last job of the deploy
# workflow, or a phone on mobile data with Tailscale switched off. From inside
# the tailnet it proves nothing.
#
#   APP_HOSTNAME=<name>.<tailnet>.ts.net SERVER_PUBLIC_IP=<address> deploy/verify-not-public.sh
#
# The instance is served by a Tailscale sidecar under a MagicDNS name, with no
# Traefik router and no published port, so there should be no route to find.
# From outside the tailnet the name must not even resolve:
#   - it resolves to a tailnet address  -> this machine is on the tailnet; the test proves nothing
#   - it resolves to a public address   -> something publishes it, Funnel being the likely cause
#   - it does not resolve               -> as intended; carry on and try the doors anyway
#
# The doors tried: the server's public address on 443 and 80 with the hostname
# presented, which is how a router listening on every interface is reached by
# someone who knows the name; and the two application ports, in case either was
# ever published. Set SERVER_PUBLIC_IPV6 if the server has one.
set -euo pipefail

: "${APP_HOSTNAME:?the hostname the instance is served under}"
: "${SERVER_PUBLIC_IP:?the public address of the server}"

resolved=$(getent ahosts "$APP_HOSTNAME" | awk '{ print $1 }' | sort -u || true)
for address in $resolved; do
  case "$address" in
    100.6[4-9].* | 100.[7-9][0-9].* | 100.1[01][0-9].* | 100.12[0-7].* | fd7a:115c:a1e0:*)
      echo "$APP_HOSTNAME resolves to the tailnet address $address, so this machine is on the" >&2
      echo "tailnet and the test would prove nothing. Run it from somewhere else." >&2
      exit 1
      ;;
    *)
      echo "$APP_HOSTNAME resolves publicly to $address. A MagicDNS name should not resolve off" >&2
      echo "the tailnet; something is publishing it. Check whether Funnel is enabled." >&2
      exit 1
      ;;
  esac
done

echo "shut (no DNS)  $APP_HOSTNAME does not resolve from here"

exposed=0

answers() {
  local label=$1
  shift
  local status
  status=$(curl --silent --insecure --max-time 10 --output /dev/null --write-out '%{http_code}' "$@" || true)
  # /api/health is asked for because the application never answers it with a
  # 404, so a 404 can only be a router's. A shut door is no connection at all
  # (000), an allow-list refusing (403), or a router that does not know the
  # name (404). Anything else came through a route: the application's own
  # answer, healthy or not, or the 502 of a route that is open onto an
  # application still starting.
  case "$status" in
    000 | 403 | 404) echo "shut ($status)     $label" ;;
    *)
      echo "EXPOSED ($status)  $label"
      exposed=1
      ;;
  esac
}

probe() {
  local address=$1 bracketed=$2
  answers "https://$APP_HOSTNAME at $address" \
    --resolve "$APP_HOSTNAME:443:$bracketed" "https://$APP_HOSTNAME/api/health"
  answers "http://$APP_HOSTNAME at $address" --location \
    --resolve "$APP_HOSTNAME:80:$bracketed" --resolve "$APP_HOSTNAME:443:$bracketed" \
    "http://$APP_HOSTNAME/api/health"
  answers "http://$bracketed:8000" "http://$bracketed:8000/api/health"
  answers "http://$bracketed:8080" "http://$bracketed:8080/api/health"
}

probe "$SERVER_PUBLIC_IP" "$SERVER_PUBLIC_IP"
if [ -n "${SERVER_PUBLIC_IPV6:-}" ]; then
  probe "$SERVER_PUBLIC_IPV6" "[$SERVER_PUBLIC_IPV6]"
fi

if [ "$exposed" -ne 0 ]; then
  echo "The instance is reachable from the public internet." >&2
  exit 1
fi
