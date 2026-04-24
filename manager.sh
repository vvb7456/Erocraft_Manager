#!/bin/bash

# FastAPI Web + manager-jobs 服务管理脚本

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

    if [[ ! -x "$PYTHON_BIN" ]]; then
        echo "错误: 未找到 Python 运行时 $PYTHON_BIN"
        exit 1
    fi
    if [[ ! -x "$UVICORN_BIN" ]]; then
        echo "错误: 未找到 Uvicorn 运行时 $UVICORN_BIN"
        exit 1
    fi
    if [[ ! -x "$ALEMBIC_BIN" ]]; then
        echo "错误: 未找到 Alembic 运行时 $ALEMBIC_BIN"
        exit 1
    fi
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
    if [[ ! -f "$pid_file" ]]; then
        return 1
    fi

    local pid
    pid="$(cat "$pid_file" 2>/dev/null)"
    if [[ -z "$pid" ]]; then
        return 1
    fi

    ps -p "$pid" > /dev/null 2>&1
}

wait_for_start() {
    local pid_file="$1"
    for _ in {1..10}; do
        if is_running "$pid_file"; then
            return 0
        fi
        sleep 1
    done
    return 1
}

web_is_ready() {
    if ! is_running "$WEB_PID_FILE"; then
        return 1
    fi

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
        if web_is_ready; then
            return 0
        fi
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

start_web() {
    ensure_runtime
    if is_running "$WEB_PID_FILE"; then
        if web_is_ready; then
            echo "manager-web 已在运行，PID: $(cat "$WEB_PID_FILE")"
            return 0
        fi
        echo "检测到 manager-web 进程存在但健康检查失败，正在清理旧进程 ..."
        stop_process "$WEB_PID_FILE" "manager-web"
    fi

    run_migrations || return 1

    rm -f "$WEB_PID_FILE"
    echo "正在启动 manager-web ..."
    cd "$APP_DIR" || exit 1
    start_detached "$WEB_LOG_FILE" "$UVICORN_BIN" "$WEB_APP" --host "$WEB_HOST" --port "$WEB_PORT" --workers "$WEB_WORKERS"
    echo $! > "$WEB_PID_FILE"

    if wait_for_start "$WEB_PID_FILE" && wait_for_web_ready; then
        echo "manager-web 已启动，PID: $(cat "$WEB_PID_FILE")，端口: $WEB_PORT"
        return 0
    fi

    echo "manager-web 启动失败，请查看 $WEB_LOG_FILE"
    stop_process "$WEB_PID_FILE" "manager-web" > /dev/null 2>&1 || true
    rm -f "$WEB_PID_FILE"
    return 1
}

start_jobs() {
    ensure_runtime
    if is_running "$JOBS_PID_FILE"; then
        echo "manager-jobs 已在运行，PID: $(cat "$JOBS_PID_FILE")"
        return 0
    fi

    run_migrations || return 1

    rm -f "$JOBS_PID_FILE"
    echo "正在启动 manager-jobs ..."
    cd "$APP_DIR" || exit 1
    start_detached "$JOBS_LOG_FILE" "$PYTHON_BIN" -m "$JOBS_MODULE"
    echo $! > "$JOBS_PID_FILE"

    if wait_for_start "$JOBS_PID_FILE"; then
        echo "manager-jobs 已启动，PID: $(cat "$JOBS_PID_FILE")"
        return 0
    fi

    echo "manager-jobs 启动失败，请查看 $JOBS_LOG_FILE"
    rm -f "$JOBS_PID_FILE"
    return 1
}

status_one() {
    local pid_file="$1"
    local label="$2"

    if is_running "$pid_file"; then
        if [[ "$label" == "manager-web" ]] && ! web_is_ready; then
            echo "$label 进程存在但健康检查失败，PID: $(cat "$pid_file")"
        else
            echo "$label 运行中，PID: $(cat "$pid_file")"
        fi
    else
        echo "$label 未运行"
    fi
}

start_all() {
    start_web || return 1
    start_jobs || return 1
}

stop_all() {
    stop_process "$JOBS_PID_FILE" "manager-jobs"
    stop_process "$WEB_PID_FILE" "manager-web"
}

restart_all() {
    stop_all
    start_all
}

status_all() {
    status_one "$WEB_PID_FILE" "manager-web"
    status_one "$JOBS_PID_FILE" "manager-jobs"
}

case "${1:-}" in
    start) start_all ;;
    stop) stop_all ;;
    restart) restart_all ;;
    status) status_all ;;
    start-web) start_web ;;
    stop-web) stop_process "$WEB_PID_FILE" "manager-web" ;;
    status-web) status_one "$WEB_PID_FILE" "manager-web" ;;
    start-jobs) start_jobs ;;
    stop-jobs) stop_process "$JOBS_PID_FILE" "manager-jobs" ;;
    status-jobs) status_one "$JOBS_PID_FILE" "manager-jobs" ;;
    *)
        echo "用法: $0 {start|stop|restart|status|start-web|stop-web|status-web|start-jobs|stop-jobs|status-jobs}"
        exit 1
        ;;
esac
