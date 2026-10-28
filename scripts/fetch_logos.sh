#!/bin/sh
# Downloads the 30 team logos (and the four dark-mode versions that differ) into
# site/logos at 96px. Run from the repo root; only needed when a team rebrands.
set -e
mkdir -p site/logos/dark
for T in ATL BKN BOS CHA CHI CLE DAL DEN DET GSW HOU IND LAC LAL MEM MIA MIL MIN NOP NYK OKC ORL PHI PHX POR SAC SAS TOR UTA WAS; do
  case $T in GSW) e=gs;; NOP) e=no;; NYK) e=ny;; SAS) e=sa;; UTA) e=utah;; WAS) e=wsh;; *) e=$(echo $T | tr A-Z a-z);; esac
  curl -sf -o site/logos/$T.png https://a.espncdn.com/i/teamlogos/nba/500/$e.png
  curl -sf -o site/logos/dark/$T.png https://a.espncdn.com/i/teamlogos/nba/500-dark/$e.png
done
sips -Z 96 site/logos/*.png site/logos/dark/*.png >/dev/null
for f in site/logos/dark/*.png; do cmp -s "$f" "site/logos/$(basename "$f")" && rm "$f"; done
ls site/logos/dark
