import re, sys, collections

import sys
path = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\Usuario\Downloads\femag_desktop.sql"
print(f"=== {path} ===")
ddl_cols = {}
insert_cols = collections.defaultdict(set)

with open(path, encoding="utf-8", errors="replace") as fh:
    in_ddl = False
    table = None
    for line in fh:
        s = line.strip()
        if s.startswith("CREATE TABLE"):
            m = re.match(r"CREATE TABLE (?:IF NOT EXISTS )?`([^`]+)`", s)
            table = m.group(1)
            ddl_cols[table] = set()
            in_ddl = True
            continue
        if in_ddl:
            if s.startswith(")"):
                in_ddl = False
                table = None
                continue
            m = re.match(r"`([^`]+)`\s", s)
            if m:
                ddl_cols[table].add(m.group(1))
            continue
        m = re.match(r"INSERT INTO `([^`]+)` \(([^)]+)\)", s)
        if m:
            t = m.group(1)
            cols = [c.strip().strip("`") for c in m.group(2).split(",")]
            insert_cols[t].update(cols)

for t, cols in sorted(insert_cols.items()):
    have = ddl_cols.get(t, set())
    missing = sorted(c for c in cols if c not in have)
    if missing:
        print(f"{t}: FALTAN {missing}")
