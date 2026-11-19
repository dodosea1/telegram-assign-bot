# -*- coding: utf-8 -*-
"""
텔레그램 없이 자동응답을 시험하는 웹 시뮬레이터.

- 실제 telegram_autoreply.py / workflow.py 코드를 그대로 돌린다 (텔레그램 연결 부분만 가짜로 바꿈)
- 데이터는 simulator/data/ 에만 저장한다. 실제 rules.json, automation.db, 로그인 세션은 건드리지 않는다.

실행:  python simulator/sim_server.py   →  http://127.0.0.1:8765
      (지난 상태를 이어서 엶. 새로 시작: --fresh)
"""
import asyncio
import json
import shutil
import sys
import threading
import time
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = HERE / "data"
PORT = 8765

# ───────────────────────── 가상 인물·대화방 ─────────────────────────

ME = 1
PEOPLE = {
    ME:   {"name": "나", "username": "me"},
    9001: {"name": "홍길동", "username": "hong"},
    9002: {"name": "이몽룡", "username": "lee"},
    501:  {"name": "박담당", "username": "parkdam"},
    502:  {"name": "김담당", "username": "kimdam"},
    777:  {"name": "다른배정자", "username": "disp2"},
}
GROUPS = {
    -100501: {"title": "박 담당 단톡", "members": [ME, 501, 777]},
    -100502: {"title": "김 담당 단톡", "members": [ME, 502, 777]},
}
# 화면에 보이는 대화방 순서
CHATS = [
    {"id": ME, "title": "저장한 메시지", "kind": "saved", "senders": [ME]},
    {"id": 9001, "title": "홍길동", "kind": "private", "senders": [9001, ME]},
    {"id": 9002, "title": "이몽룡", "kind": "private", "senders": [9002, ME]},
    {"id": -100501, "title": "박 담당 단톡", "kind": "group", "senders": [501, 777, ME]},
    {"id": -100502, "title": "김 담당 단톡", "kind": "group", "senders": [502, 777, ME]},
]

STATE = {"messages": [], "next_id": 1, "version": 0}
LOCK = threading.Lock()
HANDLER = {}
LOOP = None


class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def user_entity(uid):
    p = PEOPLE[uid]
    return Obj(id=uid, first_name=p["name"], last_name=None, username=p["username"], bot=False)


def save_state():
    """대화방·사람·메시지를 파일에 저장해 서버를 다시 켜도 이어지게 한다. (LOCK 안에서 호출)"""
    data = {"people": {str(k): v for k, v in PEOPLE.items()},
            "groups": {str(k): v for k, v in GROUPS.items()},
            "chats": CHATS, "messages": STATE["messages"], "next_id": STATE["next_id"]}
    tmp = DATA / "sim_state.json.tmp"
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(DATA / "sim_state.json")


def load_state():
    path = DATA / "sim_state.json"
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    PEOPLE.clear()
    PEOPLE.update({int(k): v for k, v in data["people"].items()})
    GROUPS.clear()
    GROUPS.update({int(k): v for k, v in data["groups"].items()})
    CHATS[:] = data["chats"]
    STATE["messages"][:] = data["messages"]
    STATE["next_id"] = data["next_id"]


def add_message(chat_id, sender_id, text, reply_to=None, auto=False):
    with LOCK:
        mid = STATE["next_id"]
        STATE["next_id"] += 1
        msg = {"id": mid, "chat_id": chat_id, "sender_id": sender_id, "text": text,
               "reply_to": reply_to, "auto": auto, "time": time.strftime("%H:%M:%S")}
        STATE["messages"].append(msg)
        STATE["version"] += 1
        save_state()
    return msg


def make_event(msg):
    chat_id = msg["chat_id"]
    is_group = chat_id in GROUPS
    is_private = not is_group  # 1:1 대화와 저장한 메시지

    async def get_sender():
        return user_entity(msg["sender_id"])

    async def reply(text):
        await CLIENT.send_message(chat_id, text, reply_to=msg["id"])

    async def respond(text):
        await CLIENT.send_message(chat_id, text)

    return Obj(raw_text=msg["text"], chat_id=chat_id, out=(msg["sender_id"] == ME),
               is_private=is_private, is_group=is_group,
               is_reply=msg["reply_to"] is not None, reply_to_msg_id=msg["reply_to"],
               sender_id=msg["sender_id"], get_sender=get_sender, reply=reply, respond=respond)


async def dispatch(msg):
    try:
        await HANDLER["on_message"](make_event(msg))
    except Exception as e:  # 시뮬레이터 화면에 오류를 보여준다
        add_message(ME, ME, f"[시뮬레이터 오류] {e!r}")


# ───────────────────────── 가짜 telethon ─────────────────────────

class FakeClient:
    def __init__(self, *a, **kw):
        self.parse_mode = None

    async def start(self, **kw):
        pass

    async def get_me(self):
        return Obj(id=ME, first_name="나")

    def on(self, _event):
        def deco(fn):
            HANDLER["on_message"] = fn
            return fn
        return deco

    async def send_message(self, to, text, reply_to=None):
        chat_id = ME if to == "me" else to
        msg = add_message(chat_id, ME, text, reply_to, auto=True)
        # 실제 텔레그램처럼 내가 보낸 메시지도 이벤트로 들어온다
        asyncio.get_running_loop().create_task(dispatch(msg))
        return Obj(chat_id=chat_id, id=msg["id"])

    async def iter_dialogs(self):
        for gid, g in GROUPS.items():
            yield Obj(is_group=True, name=g["title"], id=gid, entity=gid)
        for c in list(CHATS):
            if c["kind"] == "private":
                yield Obj(is_group=False, name=c["title"], id=c["id"], entity=user_entity(c["id"]))

    async def get_participants(self, entity):
        return [user_entity(u) for u in GROUPS[entity]["members"]]

    async def run_until_disconnected(self):
        await asyncio.Event().wait()


CLIENT = None


def _fake_client_factory(*a, **kw):
    global CLIENT
    CLIENT = FakeClient(*a, **kw)
    return CLIENT


def install_fake_telethon():
    tel = types.ModuleType("telethon")
    tel.TelegramClient = _fake_client_factory
    tel.events = Obj(NewMessage=lambda *a, **k: None)
    errors = types.ModuleType("telethon.errors")
    errors.FloodWaitError = type("FloodWaitError", (Exception,), {"seconds": 0})
    tel.errors = errors
    sys.modules["telethon"] = tel
    sys.modules["telethon.errors"] = errors


# ───────────────────────── 봇 실행 ─────────────────────────

def prepare_data(reset=False):
    if reset and DATA.exists():
        shutil.rmtree(DATA)
    DATA.mkdir(exist_ok=True)
    if not (DATA / "rules.json").exists():
        src = ROOT / "rules.json"
        if src.exists():
            shutil.copy(src, DATA / "rules.json")


def start_bot():
    global LOOP
    install_fake_telethon()
    sys.path.insert(0, str(ROOT))
    import telegram_autoreply as ta

    # 실제 파일 대신 시뮬레이터 전용 파일을 쓰도록 바꿔치기
    ta.RULES_FILE = DATA / "rules.json"
    ta.Store.__init__.__defaults__ = (DATA / "rules.json",)
    ta.LOG_FILE = DATA / "sim.log"
    ta.WORKFLOW_DB = DATA / "automation.db"
    ta.load_config = lambda: {"api_id": 1, "api_hash": "sim"}
    ta.random.uniform = lambda a, b: 0.4  # 사람처럼 잠깐 쉬는 시간을 짧게

    LOOP = asyncio.new_event_loop()
    ready = threading.Event()

    async def runner():
        task = asyncio.ensure_future(ta.main())
        while "on_message" not in HANDLER:
            await asyncio.sleep(0.05)
        ready.set()
        await task

    threading.Thread(target=lambda: LOOP.run_until_complete(runner()), daemon=True).start()
    ready.wait(10)


# ───────────────────────── 웹 서버 ─────────────────────────

def workflow_state():
    """가이드가 진행 단계를 알 수 있게 automation.db 내용을 읽어 온다."""
    import sqlite3
    wfmod = sys.modules.get("workflow")
    default_tpl = wfmod.DEFAULT_REQUEST_TEMPLATE if wfmod else ""
    out = {"managers": [], "cases": [], "template": default_tpl, "default_template": default_tpl,
           "completion_words": list(wfmod.COMPLETION_WORDS) if wfmod else [],
           "confirm_words": list(wfmod.CONFIRM_WORDS) if wfmod else [],
           "default_completion_words": list(wfmod.COMPLETION_WORDS) if wfmod else [],
           "default_confirm_words": list(wfmod.CONFIRM_WORDS) if wfmod else []}
    path = DATA / "automation.db"
    if not path.exists():
        return out
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    try:
        out["managers"] = [dict(r) for r in con.execute(
            "SELECT name, guide, address, group_id, group_title, user_id FROM managers ORDER BY name")]
        row = con.execute("SELECT value FROM settings WHERE key='request_template'").fetchone()
        if row:
            out["template"] = row["value"]
        row = con.execute("SELECT value FROM settings WHERE key='auto_request'").fetchone()
        out["auto_request"] = bool(row and row["value"] == "1")
        for key in ("completion_words", "confirm_words"):
            row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            if row and wfmod:
                out[key] = wfmod.parse_words(row["value"])
        out["cases"] = [dict(r) for r in con.execute(
            "SELECT id, target_id, target_name, manager, status, request_chat_id, request_msg_id FROM cases ORDER BY id")]
    except sqlite3.Error:
        pass
    finally:
        con.close()
    return out


def reset_all():
    import sqlite3
    with LOCK:
        STATE["messages"].clear()
        STATE["version"] += 1
        save_state()
    path = DATA / "automation.db"
    if path.exists():
        con = sqlite3.connect(str(path))
        for t in ("cases", "managers", "settings"):
            try:
                con.execute(f"DELETE FROM {t}")
            except sqlite3.Error:
                pass
        try:
            con.execute("DELETE FROM sqlite_sequence")
        except sqlite3.Error:
            pass
        con.commit()
        con.close()
    try:
        (DATA / "sim.log").write_text("", encoding="utf-8")
    except OSError:
        pass


def remove_chat(chat_id):
    """대상(1:1) 또는 담당자 단톡방을 지운다. 등록된 담당자와 진행 중인 건도 함께 정리한다."""
    import sqlite3
    with LOCK:
        chat = next((c for c in CHATS if c["id"] == chat_id), None)
        if not chat or chat["kind"] == "saved":
            return "지울 수 없는 대화방입니다"
        if sum(c["kind"] == chat["kind"] for c in CHATS) <= 1:
            return "마지막 하나는 지울 수 없습니다"
        CHATS.remove(chat)
        STATE["messages"][:] = [m for m in STATE["messages"] if m["chat_id"] != chat_id]
        if chat["kind"] == "group":
            members = GROUPS.pop(chat_id)["members"]
            person = next((u for u in members if u not in (ME, 777)), None)
        else:
            person = chat_id
        if person and not any(person in g["members"] for g in GROUPS.values()) \
                and not any(c["id"] == person for c in CHATS):
            PEOPLE.pop(person, None)
        STATE["version"] += 1
        save_state()

    path = DATA / "automation.db"
    if path.exists():
        con = sqlite3.connect(str(path))
        try:
            open_states = "('담당자대기','완성대기','확인대기','발송중')"
            if chat["kind"] == "group":
                names = [r[0] for r in con.execute("SELECT name FROM managers WHERE group_id=?", (chat_id,))]
                for n in names:
                    con.execute(f"UPDATE cases SET status='취소' WHERE manager=? AND status IN {open_states}", (n,))
                con.execute("DELETE FROM managers WHERE group_id=?", (chat_id,))
            else:
                con.execute(f"UPDATE cases SET status='취소' WHERE target_id=? AND status IN {open_states}", (chat_id,))
            con.commit()
        except sqlite3.Error:
            pass
        finally:
            con.close()
    return None


def snapshot():
    with LOCK:
        log = ""
        try:
            log = (DATA / "sim.log").read_text(encoding="utf-8")[-6000:]
        except OSError:
            pass
        snap = {"version": STATE["version"], "me": ME,
                "people": {str(k): v for k, v in PEOPLE.items()},
                "chats": CHATS, "messages": list(STATE["messages"]), "log": log}
    snap["wf"] = workflow_state()
    return snap


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = (HERE / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/api/state"):
            self._json(snapshot())
        else:
            self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/api/send":
            chat_id, sender_id = int(data["chat_id"]), int(data["sender_id"])
            text = str(data.get("text", "")).strip()
            reply_to = data.get("reply_to")
            if not text:
                return self._json({"error": "빈 메시지"}, 400)
            msg = add_message(chat_id, sender_id, text, int(reply_to) if reply_to else None)
            asyncio.run_coroutine_threadsafe(dispatch(msg), LOOP)
            self._json({"ok": True})
        elif self.path == "/api/remove":
            err = remove_chat(int(data.get("chat_id", 0)))
            self._json({"error": err} if err else {"ok": True}, 400 if err else 200)
        elif self.path == "/api/reset":
            reset_all()
            self._json({"ok": True})
        elif self.path == "/api/add":
            name = str(data.get("name", "")).strip()[:20]
            kind = data.get("kind")
            title = str(data.get("title", "")).strip()[:40]  # 단톡방 제목 (비우면 '이름 단톡')
            if kind == "manager" and not title:  # "윈터 단톡" 처럼 써도 "윈터 단톡 단톡"이 되지 않게
                for suffix in ("단톡방", "단톡"):
                    if name.endswith(suffix):
                        name = name[: -len(suffix)].strip()
            if not name or kind not in ("manager", "target"):
                return self._json({"error": "이름을 입력해 주세요"}, 400)
            if kind == "manager":
                title = title or f"{name} 단톡"
            with LOCK:
                # 같은 칸(대상끼리 / 단톡방끼리)에서만 이름이 겹치면 막는다
                if kind == "target" and any(c["kind"] == "private" and c["title"] == name for c in CHATS):
                    return self._json({"error": f"대상 '{name}'은 이미 ② 칸에 있습니다"}, 400)
                if kind == "manager" and any(c["kind"] == "group" and c["title"] == title for c in CHATS):
                    return self._json({"error": f"단톡방 '{title}'은 이미 ③ 칸에 있습니다"}, 400)
                uid = max(PEOPLE) + 1 if kind == "target" else max(u for u in PEOPLE if u < 9000) + 1
                PEOPLE[uid] = {"name": name, "username": f"user{uid}"}
                if kind == "manager":
                    gid = -100000 - uid
                    GROUPS[gid] = {"title": title, "members": [ME, uid, 777]}
                    CHATS.append({"id": gid, "title": title, "kind": "group", "senders": [uid, 777, ME]})
                else:
                    CHATS.insert(1 + sum(c["kind"] == "private" for c in CHATS),
                                 {"id": uid, "title": name, "kind": "private", "senders": [uid, ME]})
                STATE["version"] += 1
                save_state()
            self._json({"ok": True})
        else:
            self.send_error(404)


def main():
    # 기본은 이어서 하기. 완전히 새로 시작하려면 --fresh (또는 화면의 '처음부터 다시')
    prepare_data(reset="--fresh" in sys.argv)
    load_state()
    start_bot()
    print(f"시뮬레이터: http://127.0.0.1:{PORT}  (데이터: {DATA})", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
