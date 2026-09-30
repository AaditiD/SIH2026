import sqlite3, json, hashlib, base64, io, math
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from PIL import Image

DB = "prahari.db"
SLA = {"critical": 1, "high": 3, "medium": 7, "low": 14}          # days to fix
WEIGHT = {"critical": 15, "high": 8, "medium": 4, "low": 1.5}     # score penalty
# Regulation knowledge base (prototype). Verify exact clause numbers before citing officially.
KB = [
 dict(t="Ventilation & gas", k=["methane", "gas", "ventilation", "airflow", "fan"], sev="critical",
      clause="Coal Mines Regulations 2017 - Ventilation & gas monitoring", cause="Inadequate airflow or faulty gas monitoring",
      action="Withdraw persons, restore ventilation, recalibrate detectors, re-test before resuming"),
 dict(t="Roof & side support", k=["roof", "support", "fall", "sidewall", "crack", "prop"], sev="critical",
      clause="Coal Mines Regulations 2017 - Systematic support rules", cause="Support missing, delayed or overloaded strata",
      action="Stop work below, install additional support, strata monitoring"),
 dict(t="Electrical safety", k=["cable", "electrical", "earthing", "spark", "insulation"], sev="high",
      clause="Coal Mines Regulations 2017 - Electrical installations", cause="Damaged cable or poor earthing",
      action="Isolate supply, replace/repair, test earthing and insulation"),
 dict(t="Blasting practice", k=["blast", "explosive", "misfire", "shot"], sev="high",
      clause="Coal Mines Regulations 2017 - Explosives and shotfiring", cause="Procedure breach or misfire handling",
      action="Enforce shotfirer procedure, clear danger zone, review blast plan"),
 dict(t="Haul road & slope", k=["haul road", "dumper", "slope", "bench", "vehicle"], sev="high",
      clause="Coal Mines Regulations 2017 - Opencast working & transport", cause="Poor road/bench condition or traffic control",
      action="Repair road, add berms and signage, restrict vehicle movement"),
 dict(t="Fire prevention", k=["fire", "smoke", "heating", "extinguisher"], sev="high",
      clause="Coal Mines Regulations 2017 - Fire prevention", cause="Spontaneous heating or missing fire equipment",
      action="Seal/cool affected area, service extinguishers, increase patrols"),
 dict(t="Dust control", k=["dust", "water spray", "respirable", "sprinkler"], sev="medium",
      clause="Coal Mines Regulations 2017 - Dust suppression", cause="Spray system not working",
      action="Repair sprays, schedule dust sampling"),
 dict(t="PPE compliance", k=["helmet", "ppe", "cap lamp", "boots", "mask"], sev="medium",
      clause="Mines safety rules - Personal protective equipment", cause="PPE not issued or enforced",
      action="Issue PPE, toolbox talk, supervisor checks"),
]

def now(): return datetime.now(timezone.utc)
def P(s): return datetime.fromisoformat(s.replace("Z", "+00:00"))
def db():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c

def init():
    c = db()
    c.executescript("""
    create table if not exists mines(id integer primary key, name text, company text, lat real, lng real, radius real);
    create table if not exists inspections(id integer primary key autoincrement, client_id text unique, mine_id int, inspector text,
      ts text, lat real, lng real, note text, photo_hash text, evidence_ok int, flags text, contractor text);
    create table if not exists cases(id integer primary key autoincrement, mine_id int, inspection_id int, title text, clause text,
      severity text, created text, due text, status text);
    create table if not exists audit(id integer primary key autoincrement, ts text, event text, payload text, prev text, hash text);""")
    if not c.execute("select 1 from mines").fetchone():
        c.executemany("insert into mines values(?,?,?,?,?,?)", [
            (1, "Jharia Colliery (underground)", "BCCL", 23.74, 86.41, 3000),
            (2, "Talcher Opencast", "MCL", 20.95, 85.22, 3000),
            (3, "Korba Gevra Opencast", "SECL", 22.35, 82.68, 3000)])
    c.commit(); c.close()

def log(c, event, payload):
    r = c.execute("select hash from audit order by id desc limit 1").fetchone()
    prev = r[0] if r else "0"; ts = now().isoformat(); p = json.dumps(payload)
    c.execute("insert into audit(ts,event,payload,prev,hash) values(?,?,?,?,?)",
              (ts, event, p, prev, hashlib.sha256((prev + ts + event + p).encode()).hexdigest()))

def audit_ok(c):
    prev = "0"
    for r in c.execute("select * from audit order by id"):
        if r["prev"] != prev or hashlib.sha256((r["prev"] + r["ts"] + r["event"] + r["payload"]).encode()).hexdigest() != r["hash"]:
            return False
        prev = r["hash"]
    return True

def assist(note):
    n = note.lower(); best, hits = None, []
    for e in KB:
        h = [k for k in e["k"] if k in n]
        if len(h) > len(hits): best, hits = e, h
    if not best:
        return dict(hazard=False, clause="No statutory match found", severity="low", cause="Officer to determine", action="Officer to review", matched=[])
    return dict(hazard=True, title=best["t"], clause=best["clause"], severity=best["sev"], cause=best["cause"], action=best["action"], matched=hits)

def dhash(b64):
    px = list(Image.open(io.BytesIO(base64.b64decode(b64))).convert("L").resize((9, 8)).getdata())
    return int("".join("1" if px[r * 9 + k] > px[r * 9 + k + 1] else "0" for r in range(8) for k in range(8)), 2)

def metres(a, b, c, d):
    p = math.pi / 180; x = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 12742000 * math.asin(math.sqrt(x))

def level(due, status):      # 0 Officer, 1 Mine Manager, 2 GM, 3 Corporate
    if status == "closed": return 0
    over = (now() - P(due)).total_seconds() / 3600
    return 0 if over <= 0 else min(3, 1 + int(over // 24))

CQ = "select i.contractor con, i.mine_id mid, k.severity sev from cases k join inspections i on i.id=k.inspection_id where k.status!='closed' and i.contractor is not null"
def contractors(c):
    t = {}
    for r in c.execute(CQ):
        d = t.setdefault(r["con"], dict(name=r["con"], points=0, mines=set(), cases=0)); d["points"] += WEIGHT[r["sev"]]; d["mines"].add(r["mid"]); d["cases"] += 1
    return sorted([dict(name=d["name"], points=d["points"], mines=len(d["mines"]), cases=d["cases"]) for d in t.values()], key=lambda d: -d["points"])

def cascade(c, mid):   # a contractor's open issues at OTHER mines raise this mine's risk
    t, out = {}, {}
    for r in c.execute(CQ): t.setdefault(r["con"], {}); t[r["con"]][r["mid"]] = t[r["con"]].get(r["mid"], 0) + WEIGHT[r["sev"]]
    for (con,) in c.execute("select distinct contractor from inspections where mine_id=? and contractor is not null", (mid,)).fetchall():
        other = sum(v for m, v in t.get(con, {}).items() if m != mid)
        if other >= 8: out[con] = round(0.25 * other, 1)
    return out

def risk(c, mid):
    f = {}
    for r in c.execute("select * from cases where mine_id=? and status!='closed'", (mid,)):
        lv = level(r["due"], r["status"]); pts = WEIGHT[r["severity"]] * (1.5 if lv else 1) + 3 * lv
        f[f'{r["title"]} ({r["severity"]}{", overdue" if lv else ""})'] = pts
    bad = c.execute("select count(*) from inspections where mine_id=? and evidence_ok=0", (mid,)).fetchone()[0]
    if bad: f[f"Unverified evidence ({bad} submissions)"] = 2 * bad
    for con, p in cascade(c, mid).items(): f[f"Contractor risk: {con} (issues at other mines)"] = p
    fs = sorted(f.items(), key=lambda x: -x[1])
    return max(0, round(100 - sum(f.values()))), [dict(label=k, points=round(v, 1)) for k, v in fs[:4]]

app = FastAPI(title="PRAHARI prototype")
init()

class Insp(BaseModel):
    client_id: str; mine_id: int; inspector: str; note: str; lat: float; lng: float; captured_at: str
    photo_b64: Optional[str] = None
    contractor: Optional[str] = None
class Note(BaseModel): note: str
class Verify(BaseModel): approve: bool
class Days(BaseModel): days: int = 5

@app.get("/api/mines")
def mines():
    c = db(); r = [dict(x) for x in c.execute("select * from mines")]; c.close(); return r

@app.post("/api/assist")
def api_assist(b: Note): return assist(b.note)

@app.post("/api/inspections")
def submit(b: Insp):
    c = db()
    old = c.execute("select id from inspections where client_id=?", (b.client_id,)).fetchone()
    if old: c.close(); return dict(duplicate_submission=True, inspection_id=old[0])
    m = c.execute("select * from mines where id=?", (b.mine_id,)).fetchone(); flags = []; h = None
    d = metres(b.lat, b.lng, m["lat"], m["lng"])
    if d > m["radius"]: flags.append(f"Outside mine geofence ({d / 1000:.1f} km away)")
    age = (now() - P(b.captured_at)).total_seconds()
    if age > 72 * 3600: flags.append("Stale timestamp (captured over 72 h ago)")
    if age < -300: flags.append("Timestamp is in the future")
    if not b.photo_b64: flags.append("No photo evidence")
    else:
        h = dhash(b.photo_b64)
        for r in c.execute("select photo_hash from inspections where photo_hash is not null"):
            if bin(int(r[0], 16) ^ h).count("1") <= 5: flags.append("Duplicate or recycled photo"); break
    if len(b.note.strip()) < 15: flags.append("Incomplete observation (note too short)")
    cur = c.execute("insert into inspections(client_id,mine_id,inspector,ts,lat,lng,note,photo_hash,evidence_ok,flags,contractor) values(?,?,?,?,?,?,?,?,?,?,?)",
        (b.client_id, b.mine_id, b.inspector, b.captured_at, b.lat, b.lng, b.note, None if h is None else format(h, "x"), int(not flags), json.dumps(flags), b.contractor))
    iid = cur.lastrowid; s = assist(b.note); cid = None
    log(c, "inspection", dict(id=iid, mine=b.mine_id, ok=not flags))
    def mk(title, clause, sev):
        x = c.execute("insert into cases(mine_id,inspection_id,title,clause,severity,created,due,status) values(?,?,?,?,?,?,?,?)",
            (b.mine_id, iid, title, clause, sev, now().isoformat(), (now() + timedelta(days=SLA[sev])).isoformat(), "open"))
        log(c, "case_created", dict(case=x.lastrowid, severity=sev)); return x.lastrowid
    if s["hazard"]: cid = mk(s["title"], s["clause"], s["severity"])
    if flags: mk("Evidence integrity review", "Evidence verification policy", "medium")
    c.commit(); c.close()
    return dict(inspection_id=iid, evidence_ok=not flags, flags=flags, suggestion=s, case_id=cid)

@app.get("/api/cases")
def cases():
    c = db(); out = []
    for r in c.execute("select cases.*, mines.name mine from cases join mines on mines.id=cases.mine_id order by cases.id desc"):
        x = dict(r); x["level"] = level(r["due"], r["status"]); out.append(x)
    c.close(); return out

@app.post("/api/cases/{cid}/action")
def action(cid: int):
    c = db(); c.execute("update cases set status='action_done' where id=? and status='open'", (cid,)); log(c, "action_done", dict(case=cid)); c.commit(); c.close(); return dict(ok=True)

@app.post("/api/cases/{cid}/verify")
def verify(cid: int, b: Verify):
    c = db(); st = "closed" if b.approve else "open"
    c.execute("update cases set status=? where id=? and status='action_done'", (st, cid)); log(c, "verified", dict(case=cid, approved=b.approve)); c.commit(); c.close(); return dict(status=st)

@app.get("/api/dashboard")
def dashboard(mine_id: int = 0, company: str = ""):
    c = db(); out = []
    rows = [m for m in c.execute("select * from mines") if (not mine_id or m["id"] == mine_id) and (not company or m["company"] == company)]
    ids = [m["id"] for m in rows]
    for m in rows:
        sc, f = risk(c, m["id"]); cs = c.execute("select due,status from cases where mine_id=? and status!='closed'", (m["id"],)).fetchall()
        out.append(dict(id=m["id"], lat=m["lat"], lng=m["lng"], name=m["name"], company=m["company"], score=sc, factors=f, open=len(cs), overdue=sum(1 for x in cs if level(x["due"], x["status"]))))
    k = c.execute("select count(*), sum(evidence_ok) from inspections").fetchone()
    cs = [dict(severity=x["severity"], level=level(x["due"], x["status"]), status=x["status"]) for x in c.execute("select * from cases") if x["mine_id"] in ids]
    op = [x for x in cs if x["status"] != "closed"]
    r = dict(mines=out, audit_ok=audit_ok(c),
        kpi=dict(inspections=k[0], verified=round(100 * (k[1] or 0) / k[0]) if k[0] else 100, open=len(op),
                 overdue=sum(1 for x in op if x["level"]), closed=len(cs) - len(op), avg=round(sum(m["score"] for m in out) / len(out))),
        severity={s: sum(1 for x in op if x["severity"] == s) for s in SLA}, ladder=[sum(1 for x in op if x["level"] == i) for i in range(4)],
        contractors=contractors(c), recent=[dict(event=x["event"], ts=x["ts"]) for x in c.execute("select * from audit order by id desc limit 6")])
    c.close(); return r

@app.get("/api/satellite/{mid}")
def satellite(mid: int):   # DEMO: simulated values standing in for Sentinel-2 change detection
    c = db(); m = c.execute("select * from mines where id=?", (mid,)).fetchone(); c.close()
    if "Opencast" not in m["name"]: return dict(applicable=False)
    rep = 40 + mid * 6; det = round(rep * (0.55 if mid == 2 else 0.92))
    return dict(applicable=True, reported_ha=rep, detected_ha=det, mismatch=rep - det > 0.2 * rep)

@app.get("/api/audit")
def audit():
    c = db(); r = [dict(x) for x in c.execute("select * from audit order by id desc limit 50")]; c.close(); return r

@app.post("/api/demo/fastforward")
def ff(b: Days):
    c = db()
    for r in c.execute("select id,due from cases where status!='closed'").fetchall():
        c.execute("update cases set due=? where id=?", ((P(r["due"]) - timedelta(days=b.days)).isoformat(), r["id"]))
    c.commit(); c.close(); return dict(ok=True)

@app.post("/api/demo/reset")
def reset():
    c = db()
    for t in ("inspections", "cases", "audit"): c.execute(f"delete from {t}")
    c.commit(); c.close(); return dict(ok=True)

def seed():
    import random
    c = db(); n = c.execute("select count(*) from inspections").fetchone()[0]; c.close()
    if n: return
    def img(i):
        r = random.Random(i); im = Image.new("L", (64, 64)); im.putdata([r.randint(0, 255) for _ in range(4096)])
        b = io.BytesIO(); im.save(b, "PNG"); return base64.b64encode(b.getvalue()).decode()
    S = [(1, "Methane reading high near panel 3, ventilation fan not running", 0), (1, "Roof crack and missing support props in gallery 2", 0),
         (1, "Cap lamp and helmet not worn by two workers", 0), (2, "Haul road slope unstable, dumper near bench edge", 0),
         (2, "Dust suppression water spray not working at crusher", 1), (2, "Blasting misfire not reported at bench 4", 2),
         (3, "Electrical cable damaged, earthing missing at pump", 0), (3, "Fire smoke seen near coal stack, extinguisher empty", 0),
         (3, "Routine housekeeping check completed, no issues", 0)]
    ms = {x["id"]: x for x in mines()}
    for i, (m, note, mode) in enumerate(S):
        submit(Insp(client_id=f"seed{i}", mine_id=m, inspector=["A. Sharma", "R. Das", "K. Patel"][i % 3], note=note,
            lat=ms[m]["lat"] + (0.6 if mode == 1 else 0.001), lng=ms[m]["lng"], captured_at=now().isoformat(), photo_b64=None if mode == 2 else img(i), contractor=["Apex Mining Services", "Bharat Earthmovers"][i % 2]))
    c = db()
    c.execute("update cases set status='closed' where title='PPE compliance'")
    c.execute("update cases set status='action_done' where title='Haul road & slope'")
    for t, dd in (("Ventilation & gas", 2), ("Roof & side support", 4), ("Electrical safety", 4.5)):
        for r in c.execute("select id,due from cases where title=?", (t,)).fetchall():
            c.execute("update cases set due=? where id=?", ((P(r["due"]) - timedelta(days=dd)).isoformat(), r["id"]))
    c.commit(); c.close()

seed()
app.mount("/static", StaticFiles(directory="static"), name="static")
@app.get("/")
def home(): return FileResponse("static/index.html")
