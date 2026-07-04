# 北极星 — PC 端同步验证指令

以下指令可以**直接复制到 PC 端的 DeepSeek / Codex**，让它自动完成同步验证。

---

## 任务：同步并验证北极星最新代码

### 第 1 步：确认项目目录

进入 PC 上的项目目录（可能叫 `美股V1` 或其他名字），先确认是不是 Git 仓库：

```bash
# 查看当前目录
cd
# 找到北极星项目目录，假设叫 美股V1，如果不是请换成实际目录名
ls -d 美股V1/.git 2>/dev/null
# 如果有 .git 子目录，就是 Git 仓库
```

### 第 2 步：检查工作区状态

```bash
cd 美股V1
git status --short
```

如果输出不为空（有文件被修改或未跟踪）：
- **列出来**，不要覆盖
- 让我确认后再处理

### 第 3 步：检查 Git 信息

```bash
git branch --show-current
git remote -v
git fetch origin
git log --oneline -5
```

### 第 4 步：拉取最新代码

如果工作区 clean，执行：

```bash
git pull origin master
```

### 第 5 步：确认最新 commit

```bash
git log --oneline -1
```

预期输出：
```
c2c8a6f docs: add recommendation review module guide v24
```

### 第 6 步：检查关键文件

```bash
ls -la docs/recommendation_review_module.md
ls -la northstar/ui/dashboard_review.py
ls -la tests/test_dashboard_review_imports.py
ls -la tests/test_recommendation_failure_summary.py
```

四个文件都应该存在。

### 第 7 步：运行测试（如果 PC 有 Python 环境）

```bash
python -m unittest tests.test_dashboard_review_imports -v
python -m unittest tests.test_recommendation_review_grading -v
python -m unittest tests.test_recommendation_review_snapshot_grading -v
python -m unittest tests.test_recommendation_review_quality_explanation -v
python -m unittest tests.test_recommendation_failure_reason -v
python -m unittest tests.test_recommendation_failure_summary -v
```

如果提示 `ModuleNotFoundError`，可能需要激活虚拟环境：

```bash
.venv/Scripts/activate
```
或
```bash
venv/Scripts/activate
```

如果 PC 没有 Python 环境或虚拟环境，跳过测试，只做代码同步。

### 第 8 步：最终验证

```bash
git status --short
git log --oneline -3
```

### 第 9 步：输出报告

请按以下格式输出报告：

```
## PC 同步验证报告

- 当前目录：<路径>
- 当前分支：<master / 其他>
- origin/master 最新 commit：<hash + message>
- 是否成功 pull 到 c2c8a6f：是/否
- 四个关键文件是否存在：是/否（缺哪些）
- 是否有冲突：无/有（列出冲突文件）
- git status 是否 clean：是/否
- 测试结果：<通过数/总数>（如果运行了测试）
- 是否建议统一 PC 目录名为“北极星”：建议/不建议（说明）