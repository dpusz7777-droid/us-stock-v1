#!/bin/bash
# ============================================================
#  北极星 — Mac 一键启动脚本
# ============================================================

# 固定项目目录（避免 Finder 双击时工作目录不对）
PROJECT_DIR="/Users/duyu/Documents/北极星"
cd "$PROJECT_DIR" || {
    echo "❌ 错误：无法进入项目目录 $PROJECT_DIR"
    echo "请检查目录是否存在。"
    echo ""
    echo "按回车键关闭此窗口..."
    read -r
    exit 1
}
echo "✅ 已进入项目目录：$PROJECT_DIR"

# 激活虚拟环境
VENV_DIR="$PROJECT_DIR/.venv"
if [ ! -f "$VENV_DIR/bin/activate" ]; then
    echo "❌ 错误：虚拟环境不存在（$VENV_DIR）"
    echo "请在终端运行："
    echo "  cd $PROJECT_DIR"
    echo "  python3 -m venv .venv"
    echo "  .venv/bin/pip install -r requirements.txt"
    echo ""
    echo "按回车键关闭此窗口..."
    read -r
    exit 1
fi
source "$VENV_DIR/bin/activate"
echo "✅ 已激活虚拟环境（Python $($VENV_DIR/bin/python3 --version | awk '{print $2}')）"

# 检查 8501 端口是否被占用（旧进程）
if lsof -i :8501 -P -n 2>/dev/null | grep -q LISTEN; then
    echo "⚠️  端口 8501 已被占用，尝试释放旧进程..."
    PID_OLD=$(lsof -i :8501 -P -n 2>/dev/null | awk '/LISTEN/{print $2}' | head -1)
    if [ -n "$PID_OLD" ]; then
        kill "$PID_OLD" 2>/dev/null
        sleep 2
        if lsof -i :8501 -P -n 2>/dev/null | grep -q LISTEN; then
            echo "❌ 无法释放端口 8501，请手动关闭旧进程。"
            echo "可在终端运行：kill -9 $PID_OLD"
            echo ""
            echo "按回车键关闭此窗口..."
            read -r
            exit 1
        fi
        echo "✅ 已释放端口 8501"
    fi
fi

echo "🚀 正在启动北极星……"
echo ""
echo "  系统将依次启动："
echo "    1. 后台交易引擎"
echo "    2. Streamlit 可视化看板（http://127.0.0.1:8501）"
echo ""

# 运行 launch.py（会自动打开浏览器）
$VENV_DIR/bin/python launch.py

EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ]; then
    echo ""
    echo "❌ 北极星启动失败（exit code=$EXIT_CODE）"
    echo "请查看日志：$PROJECT_DIR/logs/backend.log"
    echo ""
    echo "按回车键关闭此窗口..."
    read -r
else
    echo ""
    echo "🛑 北极星已停止运行。"
    echo ""
    echo "按回车键关闭此窗口..."
    read -r
fi