#!/usr/bin/env bash
# droplet.sh — one-shot lifecycle for the paperflow MI300X droplet.
#
#   ./scripts/droplet.sh status              show droplet + tunnel + cost
#   ./scripts/droplet.sh sleep               snapshot then destroy
#   ./scripts/droplet.sh wake                restore from newest snapshot
#   ./scripts/droplet.sh tunnel              (re-)open the ssh port-forward
#   ./scripts/droplet.sh tunnel-stop         close the port-forward
#
# The MI300X droplet costs ~$2.50/hr, so leaving it up between demos
# burns real money. Sleep+wake round-trips take ~5 min and cost $0.20
# in snapshot storage.
#
# Requires: doctl (installed via brew) + a DO API token in $DO_TOKEN or
# on disk at ~/.config/paperflow/do_token. First run prompts to install
# doctl and stash the token; subsequent runs are silent.

set -euo pipefail

# ---- config ----------------------------------------------------------
DROPLET_NAME="${PAPERFLOW_DROPLET:-snapshots-gpu-mi300x1-192gb-devcloud-atl1}"
DROPLET_SIZE="${PAPERFLOW_DROPLET_SIZE:-gpu-mi300x1-192gb-devcloud}"
DROPLET_REGION="${PAPERFLOW_DROPLET_REGION:-atl1}"
DROPLET_IMAGE_SLUG="${PAPERFLOW_DROPLET_IMAGE:-gpu-h100x1-80gb}"   # fallback if no snapshot yet
SSH_KEY="${PAPERFLOW_SSH_KEY:-$HOME/.ssh/amd_hackathon}"
SSH_KEY_NAME="${PAPERFLOW_SSH_KEY_NAME:-macbook-amd-hackathon}"
TUNNEL_LOCAL_PORT="${PAPERFLOW_TUNNEL_PORT:-8000}"
TUNNEL_REMOTE_PORT="${PAPERFLOW_REMOTE_PORT:-8000}"
COST_PER_HOUR_USD="${PAPERFLOW_HOURLY:-2.50}"

CONFIG_DIR="$HOME/.config/paperflow"
TOKEN_FILE="$CONFIG_DIR/do_token"

# Short-circuit help / no-command before we touch doctl or the token
# store — no reason to install anything just to print usage.
case "${1:-}" in
    ""|-h|--help)
        cat <<EOF
Usage: $0 <command>

  status         Show droplet, snapshot, tunnel state and running cost
  sleep          Snapshot the droplet then destroy it (cost stops)
  wake           Restore from newest snapshot (cost starts)
  tunnel         Open the localhost:$TUNNEL_LOCAL_PORT SSH port-forward
  tunnel-stop    Close the SSH port-forward

Config via env vars: PAPERFLOW_DROPLET, PAPERFLOW_DROPLET_SIZE,
PAPERFLOW_DROPLET_REGION, PAPERFLOW_SSH_KEY, PAPERFLOW_SSH_KEY_NAME,
PAPERFLOW_TUNNEL_PORT, PAPERFLOW_HOURLY.

Token: DO_TOKEN env var, or $TOKEN_FILE.
EOF
        exit 0 ;;
esac

# ---- doctl bootstrap -------------------------------------------------
if ! command -v doctl >/dev/null 2>&1; then
    echo "doctl not found. Installing via brew..."
    if ! command -v brew >/dev/null 2>&1; then
        echo "Homebrew is required. Install from https://brew.sh then rerun." >&2
        exit 1
    fi
    brew install doctl
fi

# ---- API token -------------------------------------------------------
if [ -z "${DO_TOKEN:-}" ]; then
    if [ -r "$TOKEN_FILE" ]; then
        DO_TOKEN=$(<"$TOKEN_FILE")
    else
        echo "No DO API token found."
        echo "  Create one at https://cloud.digitalocean.com/account/api/tokens"
        printf "  Paste it here (or ^C and export DO_TOKEN): "
        read -r DO_TOKEN
        mkdir -p "$CONFIG_DIR" && chmod 700 "$CONFIG_DIR"
        printf '%s' "$DO_TOKEN" > "$TOKEN_FILE"
        chmod 600 "$TOKEN_FILE"
        echo "  Stashed at $TOKEN_FILE (mode 600)."
    fi
fi
export DIGITALOCEAN_ACCESS_TOKEN="$DO_TOKEN"

# ---- helpers ---------------------------------------------------------
droplet_id() {
    doctl compute droplet list --format ID,Name --no-header \
        | awk -v n="$DROPLET_NAME" '$2 == n { print $1; exit }'
}

droplet_ip() {
    local id="$1"
    doctl compute droplet get "$id" --format PublicIPv4 --no-header
}

droplet_uptime_seconds() {
    local id="$1"
    local created ; created=$(doctl compute droplet get "$id" --format Created --no-header)
    # ISO 8601 -> epoch (BSD date on macOS is fussy; try GNU first)
    local secs=""
    if command -v gdate >/dev/null 2>&1; then
        secs=$(gdate -d "$created" +%s)
    else
        secs=$(date -j -f "%Y-%m-%dT%H:%M:%SZ" "$created" +%s 2>/dev/null || echo "")
    fi
    if [ -z "$secs" ]; then echo 0; return; fi
    echo $(( $(date +%s) - secs ))
}

latest_snapshot_id() {
    # Snapshots are name-prefixed with the droplet name by the sleep flow.
    doctl compute snapshot list --resource droplet --format ID,Name,CreatedAt --no-header \
        | awk -v n="$DROPLET_NAME" '$2 ~ n { print $1 }' | tail -1
}

# ---- subcommands -----------------------------------------------------
cmd_status() {
    local id
    id=$(droplet_id || true)
    if [ -z "$id" ]; then
        echo "Droplet: DESTROYED (no droplet named $DROPLET_NAME)"
    else
        local ip up hrs cost
        ip=$(droplet_ip "$id")
        up=$(droplet_uptime_seconds "$id")
        hrs=$(awk -v s="$up" 'BEGIN { printf "%.2f", s/3600 }')
        cost=$(awk -v h="$hrs" -v r="$COST_PER_HOUR_USD" 'BEGIN { printf "%.2f", h*r }')
        echo "Droplet: $DROPLET_NAME ($id) at $ip"
        echo "Uptime : ${hrs}h (~\$${cost} at \$${COST_PER_HOUR_USD}/hr)"
    fi
    local snap ; snap=$(latest_snapshot_id || true)
    if [ -n "$snap" ]; then
        echo "Newest snapshot: $snap"
    else
        echo "Newest snapshot: none (first sleep will create one)"
    fi
    # Tunnel status: any local ssh process forwarding TUNNEL_LOCAL_PORT?
    if pgrep -f "ssh.*-L $TUNNEL_LOCAL_PORT:localhost:$TUNNEL_REMOTE_PORT" >/dev/null; then
        echo "Tunnel : UP on localhost:$TUNNEL_LOCAL_PORT"
    else
        echo "Tunnel : DOWN"
    fi
}

cmd_sleep() {
    local id
    id=$(droplet_id || true)
    if [ -z "$id" ]; then
        echo "Nothing to sleep — droplet already destroyed."
        exit 0
    fi
    local ts snap_name
    ts=$(date +%Y-%m-%d-%H%M)
    snap_name="${DROPLET_NAME}-${ts}"
    echo "Snapshotting droplet $id as '$snap_name' (this takes ~3-5 min)..."
    doctl compute droplet-action snapshot "$id" --snapshot-name "$snap_name" --wait
    echo "Snapshot complete. Destroying droplet $id..."
    doctl compute droplet delete "$id" --force
    # Kill any local ssh tunnel that was pointed at it.
    pkill -f "ssh.*-L $TUNNEL_LOCAL_PORT:localhost:$TUNNEL_REMOTE_PORT" 2>/dev/null || true
    echo "Sleep complete. Cost stops accruing now."
    echo "Wake later with:  $0 wake"
}

cmd_wake() {
    local existing
    existing=$(droplet_id || true)
    if [ -n "$existing" ]; then
        echo "Droplet already up as $existing ($(droplet_ip "$existing"))."
        cmd_tunnel
        return
    fi
    local snap
    snap=$(latest_snapshot_id || true)
    local image_arg
    if [ -n "$snap" ]; then
        echo "Restoring from snapshot $snap..."
        image_arg="--image $snap"
    else
        echo "No snapshot found; creating fresh droplet with base image $DROPLET_IMAGE_SLUG."
        image_arg="--image $DROPLET_IMAGE_SLUG"
    fi
    local ssh_id
    ssh_id=$(doctl compute ssh-key list --format ID,Name --no-header \
             | awk -v n="$SSH_KEY_NAME" '$2 == n { print $1; exit }')
    if [ -z "$ssh_id" ]; then
        echo "SSH key '$SSH_KEY_NAME' not found in DO account." >&2
        echo "Upload it (public key from $SSH_KEY.pub) via" >&2
        echo "  doctl compute ssh-key import $SSH_KEY_NAME --public-key-file $SSH_KEY.pub" >&2
        exit 1
    fi
    # shellcheck disable=SC2086
    doctl compute droplet create "$DROPLET_NAME" \
        $image_arg \
        --size "$DROPLET_SIZE" \
        --region "$DROPLET_REGION" \
        --ssh-keys "$ssh_id" \
        --wait
    local id ip
    id=$(droplet_id)
    ip=$(droplet_ip "$id")
    echo "Wake complete. Droplet $id up at $ip."
    echo "vLLM needs a couple of minutes to reload the Gemma weights."
    cmd_tunnel
}

cmd_tunnel() {
    local id ; id=$(droplet_id || true)
    if [ -z "$id" ]; then
        echo "No droplet running. Run '$0 wake' first." >&2
        exit 1
    fi
    local ip ; ip=$(droplet_ip "$id")
    cmd_tunnel_stop >/dev/null 2>&1 || true
    echo "Opening tunnel: localhost:$TUNNEL_LOCAL_PORT -> $ip:$TUNNEL_REMOTE_PORT"
    ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new \
        -N -f -L "$TUNNEL_LOCAL_PORT:localhost:$TUNNEL_REMOTE_PORT" \
        "root@$ip"
    sleep 2
    if pgrep -f "ssh.*-L $TUNNEL_LOCAL_PORT:localhost:$TUNNEL_REMOTE_PORT" >/dev/null; then
        echo "Tunnel up. paperflow's Docker container should reach Gemma via host.docker.internal:$TUNNEL_LOCAL_PORT"
    else
        echo "Tunnel did not stay up — check ssh output above." >&2
        exit 1
    fi
}

cmd_tunnel_stop() {
    if pgrep -f "ssh.*-L $TUNNEL_LOCAL_PORT:localhost:$TUNNEL_REMOTE_PORT" >/dev/null; then
        pkill -f "ssh.*-L $TUNNEL_LOCAL_PORT:localhost:$TUNNEL_REMOTE_PORT"
        echo "Tunnel closed."
    else
        echo "Tunnel already down."
    fi
}

# ---- dispatch --------------------------------------------------------
case "${1:-}" in
    status)       cmd_status ;;
    sleep)        cmd_sleep ;;
    wake)         cmd_wake ;;
    tunnel)       cmd_tunnel ;;
    tunnel-stop)  cmd_tunnel_stop ;;
    *)            echo "Unknown command: $1"; echo "Run '$0 --help' for usage."; exit 1 ;;
esac
