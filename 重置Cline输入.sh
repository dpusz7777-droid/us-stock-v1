#!/bin/bash
# ==========================================================
# Cline 输入框重置脚本（不重启 VS Code）
# ==========================================================
# 用法：
#   chmod +x 重置Cline输入.sh && ./重置Cline输入.sh
#
# 这个脚本做了 4 件事：
#   1. 清理卡住的 Cline 任务状态
#   2. 清除所有旧任务（保留备份）
#   3. 重置 taskHistory
#   4. 命令 VS Code 重载 Cline 扩展
#   整个过程 < 5 秒，不需要重启 VS Code
# ==========================================================

echo ""
echo "🔧 Cline 输入框重置工具"
echo "═══════════════════════════"

# === Step 1: 清理卡住的任务状态 ===
echo ""
echo "▸ [1/3] 清理卡住的 Cline 任务状态..."

TASKS_DIR="$HOME/Library/Application Support/Code/User/globalStorage/shengsuan-cloud.cline-shengsuan/tasks"
STATE_DIR="$HOME/Library/Application Support/Code/User/globalStorage/shengsuan-cloud.cline-shengsuan/state"

# 备份旧任务
if [ -d "$TASKS_DIR" ]; then
    mkdir -p "$TASKS_DIR/auto_backup"
    for d in "$TASKS_DIR"/*/; do
        folder=$(basename "$d")
        if [ "$folder" != "auto_backup" ] && [ -d "$d" ]; then
            ts=$(date +%s)
            cp -r "$d" "$TASKS_DIR/auto_backup/${folder}_${ts}" 2>/dev/null
        fi
    done
    # 删除所有旧任务目录
    find "$TASKS_DIR" -maxdepth 1 -type d ! -name "tasks" ! -name "auto_backup" -exec rm -rf {} + 2>/dev/null
fi

# 清空 taskHistory
if [ -f "$STATE_DIR/taskHistory.json" ]; then
    cp "$STATE_DIR/taskHistory.json" "$STATE_DIR/taskHistory.json.bak" 2>/dev/null
fi
echo '[]' > "$STATE_DIR/taskHistory.json" 2>/dev/null
echo "   ✅ 已清理完毕"

# === Step 2: 确认 keybinding 配置正确 ===
echo ""
echo "▸ [2/3] 确认 keybindings 配置..."

KB_FILE="$HOME/Library/Application Support/Code/User/keybindings.json"
if [ -f "$KB_FILE" ]; then
    HAS_NEGATIVE=$(grep -c -- "-editor.action.insertLineBreak" "$KB_FILE" 2>/dev/null)
    if [ "$HAS_NEGATIVE" -ge 1 ]; then
        echo "   ✅ keybindings 已配置负绑定（移除 VS Code 拦截）"
    else
        echo "   ⚠️  keybindings 存在但可能缺少负绑定，请检查"
    fi
else
    echo "   ⚠️  未找到 keybindings.json"
fi

# === Step 3: 重载 Cline 扩展 ===
echo ""
echo "▸ [3/3] 重载 Cline 扩展进程..."

# 方法1: 使用 VS Code 命令重载窗口（最可靠）
code --reload-window 2>/dev/null
echo "   ✅ VS Code 窗口重载命令已发送"

echo ""
echo "═══════════════════════════"
echo "✅ 修复完成！"
echo ""
echo "VS Code 重载后，Cline 输入框应该恢复正常："
echo "  • Enter          → 发送消息"
echo "  • Shift+Enter    → 换行"
echo ""
echo "如果还有问题，再次运行本脚本即可"
echo "旧任务备份位置：$TASKS_DIR/auto_backup"
echo ""