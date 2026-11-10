#!/bin/zsh
# Launcher for games that need the DXMT/DXVK stack (32-bit DirectX 11/10, which Apple's
# D3DMetal cannot run because it is 64-bit only). Mac Game Porter hands these off to
# exe-metal, which composes the Sikarugir Wine + DXMT/DXVK engine and manages the bottle.
# 64-bit DX12/DX11 games use the native Game Porting Toolkit launcher instead (launcher.sh).
APP="${0:A:h:h}"
RES="$APP/Resources"
source "$RES/porter.conf"          # GAME_NAME GAME_SLUG GAME_EXE_PATH RUNTIME RENDERER
DATA="$HOME/Library/Application Support/$GAME_NAME"
LOG="$DATA/last-run.log"
mkdir -p "$DATA"
[[ -f "$DATA/launch.conf" ]] && source "$DATA/launch.conf"   # per-user overrides, e.g. EXTRA_ARGS="-language=int"

# exe-metal binary: an env override, else the location setup copies it to.
EXE_METAL="${EXEMETAL:-$HOME/Library/Application Support/exe-metal/bin/exe-metal}"
if [[ ! -x "$EXE_METAL" ]]; then
  msg="This game uses the DXMT path, which needs exe-metal. Install it and put its binary at: $EXE_METAL"
  echo "$msg" > "$LOG"
  osascript -e "display alert \"exe-metal not found\" message \"$msg\"" >/dev/null 2>&1
  exit 1
fi

# exe-metal probes the exe and picks the renderer (DXMT for 32-bit DX11, DXVK for DX9, ...),
# builds/reuses a bottle named after this game, and launches it. EXTRA_ARGS pass to the game.
if [[ -n "$EXTRA_ARGS" ]]; then
  exec "$EXE_METAL" play --bottle "$GAME_SLUG" "$GAME_EXE_PATH" -- ${=EXTRA_ARGS} > "$LOG" 2>&1
else
  exec "$EXE_METAL" play --bottle "$GAME_SLUG" "$GAME_EXE_PATH" > "$LOG" 2>&1
fi
