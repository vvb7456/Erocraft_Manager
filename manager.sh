#!/bin/bash

# Gunicorn 服务管理脚本

APP_NAME="ptero_manager"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$APP_DIR/$APP_NAME.pid"
LOG_DIR="$APP_DIR/logs"
APP_MODULE="app:create_app()"
VENV_ACTIVATE="$APP_DIR/venv/bin/activate"

# 激活虚拟环境
if [ -f "$VENV_ACTIVATE" ]; then
    source "$VENV_ACTIVATE"
else
    echo "错误: 未找到虚拟环境 venv"
    exit 1
fi

mkdir -p "$LOG_DIR"

if ! command -v gunicorn &> /dev/null; then
    echo "错误: gunicorn 未安装"
    exit 1
fi

start() {
    if [ -f "$PID_FILE" ] && ps -p $(cat "$PID_FILE") > /dev/null 2>&1; then
        echo "$APP_NAME 已在运行，PID: $(cat "$PID_FILE")"
        exit 1
    fi
    rm -f "$PID_FILE"

    echo "正在启动 $APP_NAME ..."
    cd "$APP_DIR" || exit
    gunicorn --config gunicorn_config.py "$APP_MODULE"

    sleep 2
    if [ -f "$PID_FILE" ] && ps -p $(cat "$PID_FILE") > /dev/null 2>&1; then
        echo "$APP_NAME 已启动，PID: $(cat "$PID_FILE")"
        echo "日志: $LOG_DIR"
    else
        echo "启动失败，请查看 $LOG_DIR/error.log"
        rm -f "$PID_FILE"
        exit 1
    fi
}

stop() {
    if [ ! -f "$PID_FILE" ]; then
        echo "$APP_NAME 未在运行"
        return
    fi
    echo "正在停止 $APP_NAME ..."
    kill $(cat "$PID_FILE") 2>/dev/null
    sleep 2
    # 强制终止残留进程
    if [ -f "$PID_FILE" ] && ps -p $(cat "$PID_FILE") > /dev/null 2>&1; then
        kill -9 $(cat "$PID_FILE") 2>/dev/null
    fi
    rm -f "$PID_FILE"
    echo "$APP_NAME 已停止"
}

status() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p $PID > /dev/null 2>&1; then
            echo "$APP_NAME 运行中，PID: $PID"
        else
            echo "$APP_NAME 状态异常：PID 文件存在但进程不在运行"
        fi
    else
        echo "$APP_NAME 未运行"
    fi
}

case "$1" in
    start)   start ;;
    stop)    stop ;;
    restart) stop; sleep 1; start ;;
    status)  status ;;
    *)       echo "用法: $0 {start|stop|restart|status}"; exit 1 ;;
esac
