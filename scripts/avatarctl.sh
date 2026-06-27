#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-status}"
NAME="${2:-}"

INSTALL_ROOT="/opt/rk3588-avatar-gateway"
ENV_FILE="/etc/default/avatar-gateway"
AVATAR_DIR="$INSTALL_ROOT/assets/avatars"

ensure_env_file() {
  if [[ ! -f "$ENV_FILE" ]]; then
    sudo touch "$ENV_FILE"
  fi
}

set_env_value() {
  local key="$1"
  local value="$2"
  local tmp_file

  ensure_env_file
  tmp_file="$(mktemp)"
  sudo cat "$ENV_FILE" > "$tmp_file"

  if grep -q "^${key}=" "$tmp_file"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$tmp_file"
  else
    echo "${key}=${value}" >> "$tmp_file"
  fi

  sudo tee "$ENV_FILE" < "$tmp_file" > /dev/null
  rm -f "$tmp_file"
}

list_avatars() {
  if [[ ! -d "$AVATAR_DIR" ]]; then
    echo "头像目录不存在: $AVATAR_DIR" >&2
    return 1
  fi

  find "$AVATAR_DIR" -maxdepth 1 -type f -name "*.png" -printf "%f\n" | sed 's/\.png$//' | sort
}

select_avatar() {
  if [[ -z "$NAME" ]]; then
    echo "用法: $0 select-avatar <name>" >&2
    return 1
  fi

  if [[ ! -f "$AVATAR_DIR/$NAME.png" ]]; then
    echo "未找到头像: $AVATAR_DIR/$NAME.png" >&2
    return 1
  fi

  set_env_value "AVATAR_NAME" "$NAME"
  sudo systemctl restart avatar-gateway
  echo "已切换头像为: $NAME"
}

set_scale() {
  if [[ -z "$NAME" ]]; then
    echo "用法: $0 set-scale <value>" >&2
    return 1
  fi

  if ! [[ "$NAME" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    echo "缩放值必须是正数，例如 1.2" >&2
    return 1
  fi

  set_env_value "AVATAR_SCALE" "$NAME"
  sudo systemctl restart avatar-gateway
  echo "已设置 AVATAR_SCALE=$NAME"
}

case "$ACTION" in
  start|stop|restart|status)
    exec sudo systemctl "$ACTION" avatar-gateway
    ;;
  list-avatars)
    list_avatars
    ;;
  select-avatar)
    select_avatar
    ;;
  set-scale)
    set_scale
    ;;
  *)
    echo "用法: $0 {start|stop|restart|status|list-avatars|select-avatar <name>|set-scale <value>}" >&2
    exit 1
    ;;
esac