#!/bin/bash
# ============================================================
#  北极星 — 一键同步到 GitHub
# ============================================================

PROJECT_DIR="/Users/duyu/Documents/北极星"
cd "$PROJECT_DIR" || {
    echo "❌ 错误：无法进入项目目录 $PROJECT_DIR"
    echo ""
    echo "按回车键关闭此窗口..."
    read -r
    exit 1
}
echo "✅ 已进入项目目录：$PROJECT_DIR"

# 检查是否有改动需要提交
if git diff --quiet && git diff --cached --quiet && [ -z "$(git ls-files --others --exclude-standard)" ]; then
    echo ""
    echo "📭 没有需要同步的改动，工作区干净。"
    echo ""
    echo "按回车键关闭此窗口..."
    read -r
    exit 0
fi

echo "📦 正在暂存所有改动..."
git add .

# 生成带时间的 commit message
COMMIT_MSG="update from mac $(date '+%Y-%m-%d %H:%M')"
echo "💬 Commit: $COMMIT_MSG"
git commit -m "$COMMIT_MSG"

echo "☁️  正在推送到 GitHub（origin master）..."
git push origin master 2>&1
PUSH_EXIT=$?

if [ $PUSH_EXIT -eq 0 ]; then
    echo ""
    echo "✅ 同步成功！已推送到 GitHub。"
    echo "  提交: $COMMIT_MSG"
else
    echo ""
    echo "❌ 推送失败（exit code=$PUSH_EXIT）"
    echo "可能的原因："
    echo "  1. 网络连接问题"
    echo "  2. GitHub 需要认证（Personal Access Token）"
    echo "  3. 远程仓库有新的提交，需要先 git pull"
    echo ""
    echo "📋 失败详情请看上方日志。如需手动处理，可在终端："
    echo "  cd $PROJECT_DIR"
    echo "  git pull origin master"
    echo "  然后重试同步。"
fi

echo ""
echo "按回车键关闭此窗口..."
read -r