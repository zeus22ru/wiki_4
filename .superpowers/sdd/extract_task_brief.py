import re
import pathlib
import sys

plan_path = pathlib.Path(sys.argv[1])
n = int(sys.argv[2])
out_path = pathlib.Path(sys.argv[3])

plan = plan_path.read_text(encoding="utf-8")
lines = plan.splitlines(True)
out = []
infence = False
intask = False
for line in lines:
    if line.startswith("```"):
        infence = not infence
    if not infence and re.match(r"^#+\s+Task\s+\d+", line):
        m = re.match(r"^#+\s+Task\s+(\d+)", line)
        intask = bool(m and int(m.group(1)) == n)
    if intask:
        out.append(line)

out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text("".join(out), encoding="utf-8")
if not out:
    raise SystemExit(f"task {n} not found")
print(f"wrote {out_path}: {len(out)} lines")
