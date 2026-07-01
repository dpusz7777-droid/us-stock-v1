import subprocess
import sys

def run(cmd):
    print(f"\n>>> {cmd}")
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        print("❌ Error:", cmd)
        sys.exit(1)

print("===== AI AUTO SYNC START =====")

run("git pull origin master")
run("git add .")
run('git commit -m "auto sync"')
run("git push origin master")

print("\n===== SYNC COMPLETE =====")
input("\n按回车退出...")   # ⭐关键：防止窗口消失