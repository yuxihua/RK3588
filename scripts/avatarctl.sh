#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-status}"
NAME="${2:-}"

INSTALL_ROOT="/opt/rk3588-avatar-gateway"
ENV_FILE="/etc/default/avatar-gateway"
AVATAR_DIR="$INSTALL_ROOT/assets/avatars"

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

  echo "AVATAR_NAME=$NAME" | sudo tee "$ENV_FILE" > /dev/null
  sudo systemctl restart avatar-gateway
  echo "已切换头像为: $NAME"
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
  *)
    echo "用法: $0 {start|stop|restart|status|list-avatars|select-avatar <name>}" >&2
    exit 1
    ;;
esac