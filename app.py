#!/usr/bin/env python3
"""خادم محلي + واجهة عربية لرفع جودة الفيديو. بدون مكتبات إضافية (غير OpenCV وffmpeg).
تشغيل في Termux:  python app.py   ثم افتح  http://127.0.0.1:8000
"""
import hmac, json, os, re, secrets, subprocess, sys, threading, urllib.request, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "files"); os.makedirs(WORK, exist_ok=True)
JOBS = {}
CFG_PATH = os.path.join(HERE, "owner.json")

def cfg_load():
    try: return json.load(open(CFG_PATH))
    except Exception: return {}

def cfg_save(c):
    fd = os.open(CFG_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f: json.dump(c, f)

def owner_pw():
    c = cfg_load()
    if not c.get("pw"):
        c["pw"] = secrets.token_urlsafe(8); cfg_save(c)
        print("كلمة سر المالك (احفظها):", c["pw"])
    return c["pw"]

def cf(method, path, token, data=None, ctype=None):
    req = urllib.request.Request("https://api.cloudflare.com/client/v4" + path, data=data, method=method,
        headers={"Authorization": "Bearer " + token, **({"Content-Type": ctype} if ctype else {})})
    with urllib.request.urlopen(req, timeout=300) as r: return json.loads(r.read() or b"{}")

OWNER = """<!doctype html><html lang=ar dir=rtl><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>لوحة المالك</title><style>body{font-family:sans-serif;background:#0d1117;color:#e6edf3;padding:16px;max-width:560px;margin:auto}
input,button{width:100%;padding:12px;margin:6px 0;border-radius:10px;border:1px solid #30363d;background:#161b22;color:#e6edf3;font-size:16px}
button{background:#238636;border:0;font-weight:bold}p{color:#8b949e}</style>
<h2>إعدادات المالك</h2><input id=pw type=password placeholder="كلمة سر المالك">
<button id=ld>دخول</button><div id=box hidden>
<input id=tok type=password placeholder="مفتاح Cloudflare (يبقى محفوظ على الخادم فقط)">
<input id=acc placeholder="Account ID">
<input id=bkt placeholder="اسم الـ R2 bucket (للرفع)">
<button id=sv>حفظ</button><button id=vf>فحص المفتاح</button></div><p id=m></p>
<script>const $=i=>document.getElementById(i);
const call=async(u,b)=>(await fetch(u,{method:'POST',headers:{'X-Owner':$('pw').value},body:JSON.stringify(b||{})})).json();
$('ld').onclick=async()=>{const r=await call('/api/owner/get');if(r.error)return $('m').textContent='كلمة السر خطأ';
$('box').hidden=false;$('acc').value=r.account||'';$('bkt').value=r.bucket||'';$('m').textContent=r.has_token?'المفتاح محفوظ ✓ (مخفي)':'ما مضاف مفتاح';};
$('sv').onclick=async()=>{const r=await call('/api/owner/save',{token:$('tok').value,account:$('acc').value,bucket:$('bkt').value});$('tok').value='';$('m').textContent=r.error||'تم الحفظ ✓';};
$('vf').onclick=async()=>{$('m').textContent='...';const r=await call('/api/owner/verify');$('m').textContent=r.msg||r.error;};
</script></html>"""

PAGE = """<!doctype html><html lang=ar dir=rtl><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>رفع جودة الفيديو</title>
<style>body{font-family:sans-serif;background:#0d1117;color:#e6edf3;margin:0;padding:16px;max-width:560px;margin:auto}
select,button,input{width:100%;padding:12px;margin:6px 0;border-radius:10px;border:1px solid #30363d;background:#161b22;color:#e6edf3;font-size:16px}
button{background:#238636;border:0;font-weight:bold}.bar{height:14px;background:#30363d;border-radius:8px;overflow:hidden}
.bar i{display:block;height:100%;width:0;background:#2f81f7}video{width:100%;border-radius:10px;margin-top:10px}#m{color:#8b949e}</style>
<h2>رفع جودة الفيديو (شبكة عصبية حقيقية)</h2>
<input type=file id=f accept="video/*">
<select id=m><option value=fsrcnn>FSRCNN (سريع)</option><option value=espcn>ESPCN (سريع جداً)</option><option value=edsr>EDSR (أقوى وأبطأ)</option></select>
<select id=s><option>2</option><option>3</option><option>4</option></select>
<button id=go>ابدأ</button><div class=bar><i id=b></i></div><p id=m2></p><div id=r></div>
<script>
const $=i=>document.getElementById(i);
$('go').onclick=async()=>{const f=$('f').files[0];if(!f)return $('m2').textContent='اختر فيديو';
$('m2').textContent='رفع الفيديو...';
const r=await fetch('/up?m='+$('m').value+'&s='+$('s').value+'&n='+encodeURIComponent(f.name),{method:'POST',body:f});
const {id}=await r.json();
const t=setInterval(async()=>{const j=await (await fetch('/st?id='+id)).json();
$('b').style.width=j.p+'%';$('m2').textContent=j.msg;
if(j.done){clearInterval(t);$('r').innerHTML=j.ok?'<video controls src="/dl?id='+id+'"></video><a href="/dl?id='+id+'" download><button>تنزيل</button></a>':'';}},1500);};
</script></html>"""

def run(jid, inp, model, scale):
    j = JOBS[jid]; out = os.path.join(WORK, jid + "_out.mp4")
    try:
        p = subprocess.Popen([sys.executable, os.path.join(HERE, "upscale.py"), inp, "-m", model, "-s", str(scale), "-o", out]
                             + (["--bicubic"] if os.environ.get("BICUBIC") else []),
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        buf = ""
        while True:
            c = p.stdout.read(1)
            if not c: break
            buf += c
            if c in "\r\n":
                m = re.search(r"(\d+)/(\d+)", buf)
                if m: j["p"] = int(m.group(1)) * 100 // max(1, int(m.group(2))); j["msg"] = f"إطار {m.group(1)}/{m.group(2)}"
                elif buf.strip(): j["msg"] = buf.strip()[-120:]
                buf = ""
        p.wait()
        j["ok"] = p.returncode == 0 and os.path.exists(out)
        j["msg"] = "انتهى ✓" if j["ok"] else "فشل: " + j["msg"]
        if j["ok"]: j["p"] = 100
        c = cfg_load()
        if j["ok"] and c.get("token") and c.get("account") and c.get("bucket"):
            try:
                j["msg"] = "رفع للسحابة..."
                key = jid + ".mp4"
                r = cf("PUT", "/accounts/%s/r2/buckets/%s/objects/%s" % (c["account"], c["bucket"], key), c["token"],
                       open(out, "rb").read(), "video/mp4")
                j["cloud"] = "تم الرفع ✓ " + key if r.get("success", True) else "فشل الرفع"
            except Exception as e:
                j["cloud"] = "فشل رفع السحابة: %s" % e
            j["msg"] = "انتهى ✓ · " + j["cloud"]
    except Exception as e:
        j["ok"] = False; j["msg"] = "فشل: %s" % e
    j["done"] = True

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict,)): body = json.dumps(body).encode()
        elif isinstance(body, str): body = body.encode()
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        if u.path == "/owner": return self.send(200, OWNER, "text/html; charset=utf-8")
        if u.path == "/": return self.send(200, PAGE, "text/html; charset=utf-8")
        jid = (q.get("id") or [""])[0]
        if u.path == "/st" and jid in JOBS: return self.send(200, JOBS[jid])
        if u.path == "/dl" and jid in JOBS:
            data = open(os.path.join(WORK, jid + "_out.mp4"), "rb").read()
            return self.send(200, data, "video/mp4")
        self.send(404, {"error": "not found"})
    def do_POST(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        if u.path.startswith("/api/owner/"):
            n = int(self.headers.get("Content-Length", 0)); body = json.loads(self.rfile.read(n) or b"{}")
            if not hmac.compare_digest(self.headers.get("X-Owner", ""), owner_pw()): return self.send(403, {"error": "ممنوع"})
            c = cfg_load(); a = u.path.rsplit("/", 1)[1]
            if a == "get": return self.send(200, {"has_token": bool(c.get("token")), "account": c.get("account", ""), "bucket": c.get("bucket", "")})
            if a == "save":
                if body.get("token"): c["token"] = body["token"].strip()
                c["account"] = body.get("account", "").strip(); c["bucket"] = body.get("bucket", "").strip()
                cfg_save(c); return self.send(200, {"ok": True})
            if a == "verify":
                if not c.get("token"): return self.send(200, {"msg": "ما مضاف مفتاح"})
                try:
                    r = cf("GET", "/user/tokens/verify", c["token"])
                    return self.send(200, {"msg": "المفتاح صالح ✓" if r.get("success") else "المفتاح غير صالح"})
                except Exception as e: return self.send(200, {"msg": "فشل الفحص: %s" % e})
            return self.send(404, {})
        if u.path != "/up": return self.send(404, {})
        jid = uuid.uuid4().hex[:8]; inp = os.path.join(WORK, jid + "_in.mp4")
        n = int(self.headers.get("Content-Length", 0)); left = n
        with open(inp, "wb") as f:
            while left > 0:
                b = self.rfile.read(min(1 << 20, left))
                if not b: break
                f.write(b); left -= len(b)
        m = q.get("m", ["fsrcnn"])[0]; s = int(q.get("s", ["2"])[0])
        if m not in ("fsrcnn", "espcn", "edsr") or s not in (2, 3, 4): return self.send(400, {})
        JOBS[jid] = {"p": 0, "msg": "بدأ...", "done": False, "ok": False}
        threading.Thread(target=run, args=(jid, inp, m, s), daemon=True).start()
        self.send(200, {"id": jid})

if __name__ == "__main__":
    owner_pw()
    print("الواجهة: http://127.0.0.1:8000   لوحة المالك: http://127.0.0.1:8000/owner")
    ThreadingHTTPServer(("127.0.0.1", 8000), H).serve_forever()
