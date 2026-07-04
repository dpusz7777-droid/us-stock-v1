#!/usr/bin/env python3
import sys, os
sys.stdout = open(1, 'w', encoding='utf-8', closefd=False)
sys.stderr = sys.stdout
from v3_pipeline import V3Pipeline, create_scenario_data

p = V3Pipeline()
p.reset()
r = p.run(create_scenario_data('bull'))

print(f"Status: {r.status.value}")
print(f"Errors: {r.errors}")
print(f"Warnings: {r.warnings}")

for s in r.steps:
    if s.status != 'PASS' or s.error_message:
        print(f"STEP [{s.status}] {s.step_name}: err={s.error_message or 'none'}")
        print(f"  summary: {s.summary}")

if not r.errors:
    print("NO ERRORS - PASS")
else:
    print(f"Found {len(r.errors)} error(s)")