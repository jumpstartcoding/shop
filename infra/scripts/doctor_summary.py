"""Turn the doctor task's JSON (from `aws lambda invoke`) into Markdown for the GitHub job
summary. A crashed invocation (FunctionError payload) is reported as such.

    python3 infra/scripts/doctor_summary.py doctor.json https://shop.example
"""

import json
import sys

path, site = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "")
report = json.load(open(path))

print(f"## Go-live checks for {site}\n")
if "checks" not in report:
    print("The check task itself failed to run:\n")
    print("```\n" + json.dumps(report, indent=2)[:4000] + "\n```")
    sys.exit(0)

icon = {"ok": "✅", "warn": "⚠️", "fail": "❌"}
print("| | Check | Result |\n|---|---|---|")
for c in report["checks"]:
    detail = c["detail"].replace("|", "\\|").replace("\n", " ")
    print(f"| {icon.get(c['status'], '?')} | {c['title']} | {detail} |")
print()
if report.get("ok"):
    print("Deploy is healthy. ⚠️ items work but need attention before customers rely on them.")
else:
    print("**A critical check failed; the app cannot work until it is fixed.**")
