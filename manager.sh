#!/bin/bash

# FastAPI Web + manager-jobs 服务管理脚本
# 用法: manager.sh {start|stop|restart|status}

set -u

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$APP_DIR/logs"
PYTHON_BIN="$APP_DIR/venv/bin/python"
UVICORN_BIN="$APP_DIR/venv/bin/uvicorn"
ALEMBIC_BIN="$APP_DIR/venv/bin/alembic"
ALEMBIC_CONFIG="$APP_DIR/alembic.ini"

WEB_APP="${MANAGER_WEB_APP:-app.main:app}"
WEB_HOST="${MANAGER_WEB_HOST:-0.0.0.0}"
WEB_PORT="${MANAGER_WEB_PORT:-5001}"
WEB_WORKERS="${MANAGER_WEB_WORKERS:-1}"
WEB_PID_FILE="$APP_DIR/erocraft_manager_web.pid"
WEB_LOG_FILE="$LOG_DIR/manager-web.log"
WEB_HEALTH_URL="${MANAGER_WEB_HEALTH_URL:-http://127.0.0.1:${WEB_PORT}/api/version}"

JOBS_MODULE="${MANAGER_JOBS_MODULE:-app.jobs.main}"
JOBS_PID_FILE="$APP_DIR/erocraft_manager_jobs.pid"
JOBS_LOG_FILE="$LOG_DIR/manager-jobs.log"

ensure_runtime() {
    mkdir -p "$LOG_DIR"
    for bin in "$PYTHON_BIN" "$UVICORN_BIN" "$ALEMBIC_BIN"; do
        if [[ ! -x "$bin" ]]; then
            echo "错误: 未找到运行时 $bin"
            exit 1
        fi
    done
    if [[ ! -f "$ALEMBIC_CONFIG" ]]; then
        echo "错误: 未找到 Alembic 配置 $ALEMBIC_CONFIG"
        exit 1
    fi
}

run_migrations() {
    echo "正在应用数据库迁移 ..."
    cd "$APP_DIR" || exit 1
    "$ALEMBIC_BIN" -c "$ALEMBIC_CONFIG" upgrade head
}

start_detached() {
    local log_file="$1"
    shift
    if command -v setsid > /dev/null 2>&1; then
        nohup setsid "$@" < /dev/null >> "$log_file" 2>&1 &
    else
        nohup "$@" < /dev/null >> "$log_file" 2>&1 &
    fi
}

is_running() {
    local pid_file="$1"
    [[ -f "$pid_file" ]] || return 1
    local pid
    pid="$(cat "$pid_file" 2>/dev/null)"
    [[ -n "$pid" ]] || return 1
    ps -p "$pid" > /dev/null 2>&1
}

wait_for_start() {
    local pid_file="$1"
    for _ in {1..10}; do
        is_running "$pid_file" && return 0
        sleep 1
    done
    return 1
}

web_is_ready() {
    is_running "$WEB_PID_FILE" || return 1
    if command -v curl > /dev/null 2>&1; then
        curl --silent --fail --max-time 2 "$WEB_HEALTH_URL" > /dev/null 2>&1
        return $?
    fi
    local port_check
    port_check="$(ss -ltnp 2>/dev/null | grep -F ":$WEB_PORT ")"
    [[ -n "$port_check" ]]
}

wait_for_web_ready() {
    for _ in {1..20}; do
        web_is_ready && return 0
        sleep 1
    done
    return 1
}

stop_process() {
    local pid_file="$1"
    local label="$2"
    if ! is_running "$pid_file"; then
        rm -f "$pid_file"
        echo "$label 未运行"
        return 0
    fi
    local pid
    pid="$(cat "$pid_file")"
    echo "正在停止 $label ..."
    kill "$pid" 2>/dev/null || true
    for _ in {1..10}; do
        if ! ps -p "$pid" > /dev/null 2>&1; then
            rm -f "$pid_file"
            echo "$label 已停止"
            return 0
        fi
        sleep 1
    done
    kill -9 "$pid" 2>/dev/null || true
    rm -f "$pid_file"
    echo "$label 已强制停止"
}

start() {
    ensure_runtime
    if is_running "$WEB_PID_FILE" && web_is_ready; then
        echo "manager-web 已在运行，PID: $(cat "$WEB_PID_FILE")"
    elif is_running "$WEB_PID_FILE"; then
        echo "检测到 manager-web 进程存在但健康检查失败，正在清理旧进程 ..."
        stop_process "$WEB_PID_FILE" "manager-web"
    fi
    if is_running "$JOBS_PID_FILE"; then
        echo "manager-jobs 已在运行，PID: $(cat "$JOBS_PID_FILE")"
    fi

    run_migrations || return 1

    cd "$APP_DIR" || exit 1

    if ! is_running "$WEB_PID_FILE"; then
        rm -f "$WEB_PID_FILE"
        echo "正在启动 manager-web ..."
        start_detached "$WEB_LOG_FILE" "$UVICORN_BIN" "$WEB_APP" --host "$WEB_HOST" --port "$WEB_PORT" --workers "$WEB_WORKERS" --no-access-log
        echo $! > "$WEB_PID_FILE"
        if wait_for_start "$WEB_PID_FILE" && wait_for_web_ready; then
            echo "manager-web 已启动，PID: $(cat "$WEB_PID_FILE")，端口: $WEB_PORT"
        else
            echo "manager-web 启动失败，请查看 $WEB_LOG_FILE"
            stop_process "$WEB_PID_FILE" "manager-web" > /dev/null 2>&1 || true
            return 1
        fi
    fi

    if ! is_running "$JOBS_PID_FILE"; then
        rm -f "$JOBS_PID_FILE"
        echo "正在启动 manager-jobs ..."
        start_detached "$JOBS_LOG_FILE" "$PYTHON_BIN" -m "$JOBS_MODULE"
        echo $! > "$JOBS_PID_FILE"
        if wait_for_start "$JOBS_PID_FILE"; then
            echo "manager-jobs 已启动，PID: $(cat "$JOBS_PID_FILE")"
        else
            echo "manager-jobs 启动失败，请查看 $JOBS_LOG_FILE"
            return 1
        fi
    fi
}

stop() {
    stop_process "$JOBS_PID_FILE" "manager-jobs"
    stop_process "$WEB_PID_FILE" "manager-web"
}

restart() {
    stop
    start
}

status() {
    if is_running "$WEB_PID_FILE"; then
        if web_is_ready; then
            echo "manager-web 运行中，PID: $(cat "$WEB_PID_FILE")"
        else
            echo "manager-web 进程存在但健康检查失败，PID: $(cat "$WEB_PID_FILE")"
        fi
    else
        echo "manager-web 未运行"
    fi
    if is_running "$JOBS_PID_FILE"; then
        echo "manager-jobs 运行中，PID: $(cat "$JOBS_PID_FILE")"
    else
        echo "manager-jobs 未运行"
    fi
}

case "${1:-}" in
    start)   start ;;
    stop)    stop ;;
    restart) restart ;;
    status)  status ;;
    *)       echo "用法: $0 {start|stop|restart|status}"; exit 1 ;;
esac
