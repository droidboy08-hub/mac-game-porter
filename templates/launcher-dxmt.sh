#!/bin/zsh
# Native DXMT launcher: Sikarugir Wine 11 (wine32on64, DXMT built in) for 32-bit DirectX
# 11/10 games that Apple's D3DMetal (64-bit only) cannot run. No exe-metal needed — this app
# carries its own Wine and the frameworks it links against. 64-bit DX12/DX11 games use the
# Game Porting Toolkit launcher (launcher.sh) instead.
APP="${0:A:h:h}"
RES="$APP/Resources"
source "$RES/porter.conf"                    # GAME_NAME GAME_SLUG GAME_EXE ENGINE RENDERER [GAME_DIR]
GAME_DIR="${GAME_DIR:-$RES/game}"            # DMG builds embed the game; local installs point outside
DATA="$HOME/Library/Application Support/$GAME_NAME"
PREFIX="$DATA/prefix"
LOG="$DATA/last-run.log"
mkdir -p "$DATA"
[[ -f "$DATA/launch.conf" ]] && source "$DATA/launch.conf"   # per-user overrides, e.g. EXTRA_ARGS="-language=int"

WINE="$RES/wine"            # the Sikarugir wswine.bundle
FW="$RES/frameworks"        # FreeType, GStreamer and the dylibs the Wine links against

# This CrossOver-sourced Wine silently exits unless SikarugirAppWine11 is set, and it must find
# its frameworks on the dyld path or it fails at startup / renders no text. msync is its cheap
# synchronisation; the prefix must be created and run under the same settings.
export SikarugirAppWine11=1
export CX_ROOT="$WINE"
export WINEPREFIX="$PREFIX"
export WINEMSYNC=1
export WINEDEBUG="${WINEDEBUG:--all}"
export WINEDLLPATH="$WINE/lib/x86_64-windows:$WINE/lib/i386-windows:$WINE/lib/x86_64-unix"
export DYLD_FALLBACK_LIBRARY_PATH="$WINE/lib:$WINE/lib64:$FW:$FW/GStreamer.framework/Versions/1.0/lib:/usr/lib"
export ROSETTA_ADVERTISE_AVX=1               # many modern games require AVX; Rosetta exposes it on request
export D3DM_ENABLE_METALFX=1
export MTL_HUD_ENABLED="${MTL_HUD_ENABLED:-0}"
# DXMT's d3d11/dxgi/d3d10core ship as builtins in this Wine; leave them builtin (don't force native).
export WINEDLLOVERRIDES="winemenubuilder.exe=d;mscoree,mshtml="

# First launch: create the Windows prefix (a WoW64 prefix that runs 32-bit via wine32on64).
if [[ ! -f "$PREFIX/system.reg" ]]; then
  "$WINE/bin/wine" wineboot -i >/dev/null 2>&1
  "$WINE/bin/wineserver" -w
fi
mkdir -p "$PREFIX/drive_c/Games"
ln -sfn "$GAME_DIR" "$PREFIX/drive_c/Games/$GAME_SLUG"      # refreshed in case the app moved

EXE_DIR="$GAME_DIR/${GAME_EXE:h}"
cd "$EXE_DIR"
WIN_EXE="C:\\Games\\$GAME_SLUG\\${GAME_EXE//\//\\}"
if [[ -n "$EXTRA_ARGS" ]]; then
  exec "$WINE/bin/wine" "$WIN_EXE" ${=EXTRA_ARGS} "$@" > "$LOG" 2>&1
else
  exec "$WINE/bin/wine" "$WIN_EXE" "$@" > "$LOG" 2>&1
fi
