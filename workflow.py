# -*- coding: utf-8 -*-
"""
담당자 예약 확정 → 완성 → 담당자 준비 확인 → 대상에게 주소 전달

  5단계  내가 /확정 홍길동 박      → 건 생성(완성대기), 박의 안내 문구를 홍길동에게 발송
  6단계  홍길동이 '완성'          → 박 단톡방에 준비 확인요청 (확인대기)
  7단계  박이 요청에 답장 '확인'   → 홍길동에게 박의 주소 발송 (완료)

텔레그램과 무관한 순수 로직. 각 함수는 실행할 '행동' 목록을 돌려주고,
실제 발송은 telegram_autoreply.py 가 맡는다.

행동 종류
  ("me", 텍스트)                         → 저장한 메시지로 알림
  ("send", 대상id, 텍스트)                → 대상에게 메시지 발송 (안내 문구)
  ("request", 건번호, 단톡방id, 텍스트)    → 단톡방에 준비 확인요청을 올리고, 메시지 id를 set_request()로 기록
  ("deliver", 건번호, 대상id, 주소)        → 대상에게 주소 발송. 성공하면 mark_done(), 실패하면 delivery_failed()
"""
import re
import sqlite3
import time

WAIT_ASSIGN = "담당자대기"     # 완성은 왔는데 확정된 담당자가 없음
WAIT_COMPLETE = "완성대기"     # 담당자 확정됨, 대상의 완성 알림을 기다림
WAIT_CONFIRM = "확인대기"      # 담당자 단톡방에 준비 확인요청을 올림
SENDING = "발송중"
DONE = "완료"
CANCELED = "취소"
OPEN_STATES = (WAIT_ASSIGN, WAIT_COMPLETE, WAIT_CONFIRM, SENDING)
_OPEN_SQL = "status IN ('" + "','".join(OPEN_STATES) + "')"

COMPLETION_WORDS = ("완성",)             # 대상이 보내면 '완성 알림'으로 보는 말 (/완성단어 로 바꿈)
CONFIRM_WORDS = ("확인", "올려")          # 담당자가 쓰면 '준비됨'으로 보는 말 (/확인단어 로 바꿈)
REJECT_WORD = "반려"
# 위 말이 들어 있어도 이런 말이 같이 있으면 준비된 걸로 치지 않는다 (예: "확인 아직 못했어요")
NEGATIONS = ("못", "아직", "안됨", "안돼", "안되", "불가", "보류", "반려", "나중", "말아", "마세요")

DEFAULT_REQUEST_TEMPLATE = ("[#{번호}] {대상} 님 완성됐습니다.\n"
                            "준비되셨으면 '확인' 또는 '올려주세요'라고 남겨 주세요. (이 메시지에 답장하면 더 정확합니다)")


def normalize(text):
    return re.sub(r"\s+", "", text or "").casefold()


# 완성 단어가 들어 있어도 아직 완성 전인 말이면 무시한다 (예: "아직 완성 안 됐어요", "언제 완성돼요?")
NOT_YET = ("아직", "언제", "안됐", "안되", "못했", "거의", "반쯤", "절반", "?")
# 완성 단어 바로 뒤에 이런 말이 붙어야 '다 끝났다'로 본다: 완성했어요, 완성됐습니다, 완성되었어요, 완성 완료, 완성이요
DONE_SUFFIXES = ("했", "됐", "되었", "됨", "돼써", "났", "완료", "입니다", "이에요", "예요", "이요", "요")
# 단어 자체에 이미 '끝났다'는 뜻이 들어 있으면 (예: 다됐어요, 끝났어요) 뒤에 붙는 말을 따지지 않는다
DONE_INSIDE = ("했", "됐", "되었", "됨", "났")


def parse_words(raw):
    """'완성, 완료 , 다됐어요' → ['완성', '완료', '다됐어요'] (빈 칸·중복 제거)"""
    out = []
    for w in re.split(r"[,，\n]", raw or ""):
        w = w.strip()
        if w and normalize(w) not in [normalize(x) for x in out]:
            out.append(w)
    return out


def mentions_completion(text, words=COMPLETION_WORDS):
    """완성 단어가 들어 있기는 한지 (완성 전 말이라도)."""
    norm = normalize(text)
    return any(normalize(w) and normalize(w) in norm for w in words)


def is_completion(text, words=COMPLETION_WORDS):
    """'다 끝났다'는 완성 알림인지. 완성할게요·완성될 것 같아요·완성 후에·완성까지 등은 아니다."""
    norm = normalize(text)
    if any(n in norm for n in NOT_YET):
        return False
    core = re.sub(r"[!.~^♡♥ㅎㅋ👍🙏😊]+$", "", norm)  # 끝의 느낌표·웃음 등은 떼고 본다
    for w in (normalize(x) for x in words):
        if not w or w not in norm or "미" + w in norm:
            continue
        if any(d in w for d in DONE_INSIDE):           # 다됐어요, 완료했습니다 …
            return True
        for m in re.finditer(re.escape(w), norm):
            after = norm[m.end():]
            if after.startswith(DONE_SUFFIXES):          # 완성했어요, 완성됐습니다, 완성 완료 …
                return True
        if core.endswith(w):                           # "사장님 완성!" 처럼 단어로 끝나는 말
            return True
    return False


def classify_reply(text, words=CONFIRM_WORDS):
    """담당자 답장을 'confirm' / 'reject' / None 으로 분류."""
    norm = normalize(text)
    if REJECT_WORD in norm:
        return "reject"
    if any(normalize(w) and normalize(w) in norm for w in words) and not any(n in norm for n in NEGATIONS):
        return "confirm"
    return None


def render(template, case_id, target_name, manager_name):
    text = (template.replace("{번호}", str(case_id))
                    .replace("{대상}", target_name or "")
                    .replace("{담당자}", manager_name or ""))
    if "{번호}" not in template:  # 단톡방에서 누구 건인지 알 수 있게 번호는 항상 붙인다
        text = f"[#{case_id}] " + text
    return text


def _preview(text, n=40):
    one = " ".join((text or "").split())
    return one if len(one) <= n else one[:n] + "…"


class Workflow:
    def __init__(self, path="automation.db"):
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS managers (
                name TEXT PRIMARY KEY,
                group_id INTEGER NOT NULL,
                group_title TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                user_label TEXT NOT NULL,
                address TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_id INTEGER NOT NULL,
                target_name TEXT NOT NULL,
                completion_text TEXT,
                manager TEXT,
                status TEXT NOT NULL,
                request_chat_id INTEGER,
                request_msg_id INTEGER,
                created REAL NOT NULL,
                updated REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        cols = [r["name"] for r in self.db.execute("PRAGMA table_info(managers)")]
        if "guide" not in cols:  # 이전 버전 DB 업그레이드
            self.db.execute("ALTER TABLE managers ADD COLUMN guide TEXT NOT NULL DEFAULT ''")
        case_cols = [r["name"] for r in self.db.execute("PRAGMA table_info(cases)")]
        if "others_spoke" not in case_cols:  # 요청 이후 담당자·나 말고 다른 사람이 단톡방에 말했는지
            self.db.execute("ALTER TABLE cases ADD COLUMN others_spoke INTEGER NOT NULL DEFAULT 0")
        self.db.commit()

    # ───────── 설정 ─────────

    def request_template(self):
        row = self.db.execute("SELECT value FROM settings WHERE key='request_template'").fetchone()
        return row["value"] if row else DEFAULT_REQUEST_TEMPLATE

    def _words(self, key, default):
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return parse_words(row["value"]) if row else list(default)

    def _set_words(self, key, words):
        if words:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, ", ".join(words)))
        else:
            self.db.execute("DELETE FROM settings WHERE key=?", (key,))
        self.db.commit()

    def auto_request(self):
        """True: 완성 알림을 알아들으면 바로 단톡방에 요청 / False(기본): 나에게만 알리고 /완성 으로 직접 요청"""
        row = self.db.execute("SELECT value FROM settings WHERE key='auto_request'").fetchone()
        return bool(row and row["value"] == "1")

    def set_auto_request(self, on):
        self.db.execute("INSERT OR REPLACE INTO settings VALUES ('auto_request', ?)", ("1" if on else "0",))
        self.db.commit()

    def completion_words(self):
        return self._words("completion_words", COMPLETION_WORDS)

    def set_completion_words(self, words):
        self._set_words("completion_words", words)

    def confirm_words(self):
        return self._words("confirm_words", CONFIRM_WORDS)

    def set_confirm_words(self, words):
        self._set_words("confirm_words", words)

    def set_request_template(self, text):
        if text:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES ('request_template', ?)", (text,))
        else:
            self.db.execute("DELETE FROM settings WHERE key='request_template'")
        self.db.commit()

    # ───────── 담당자 ─────────

    def add_manager(self, name, group_id, group_title, user_id, user_label, address):
        old = self.manager(name)
        guide = old["guide"] if old else ""
        self.db.execute(
            "INSERT OR REPLACE INTO managers (name, group_id, group_title, user_id, user_label, address, guide) "
            "VALUES (?,?,?,?,?,?,?)", (name, group_id, group_title, user_id, user_label, address, guide))
        self.db.commit()

    def manager(self, name):
        return self.db.execute("SELECT * FROM managers WHERE name=?", (name,)).fetchone()

    def find_manager(self, query):
        """'박', '박담당', '박 담당' 처럼 조금 달라도 하나로 좁혀지면 찾아 준다."""
        exact = self.manager(query)
        if exact:
            return exact
        nq = normalize(query)
        hits = [m for m in self.managers()
                if nq and (normalize(m["name"]) in nq or nq in normalize(m["name"])
                           or nq in normalize(m["user_label"]))]
        return hits[0] if len(hits) == 1 else None

    def managers(self):
        return self.db.execute("SELECT * FROM managers ORDER BY name").fetchall()

    def set_address(self, name, address):
        cur = self.db.execute("UPDATE managers SET address=? WHERE name=?", (address, name))
        self.db.commit()
        return cur.rowcount > 0

    def set_guide(self, name, guide):
        cur = self.db.execute("UPDATE managers SET guide=? WHERE name=?", (guide, name))
        self.db.commit()
        return cur.rowcount > 0

    def manager_cases(self, name):
        return self.db.execute(
            f"SELECT * FROM cases WHERE manager=? AND {_OPEN_SQL} ORDER BY id", (name,)).fetchall()

    def delete_manager(self, name):
        if self.manager_cases(name):
            return False
        cur = self.db.execute("DELETE FROM managers WHERE name=?", (name,))
        self.db.commit()
        return cur.rowcount > 0

    def _manager_names(self):
        names = [m["name"] for m in self.managers()]
        return ", ".join(names) if names else "(등록된 담당자 없음 → /담당자추가)"

    # ───────── 건 ─────────

    def case(self, case_id):
        return self.db.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()

    def open_cases(self):
        return self.db.execute(f"SELECT * FROM cases WHERE {_OPEN_SQL} ORDER BY id").fetchall()

    def open_case_for(self, target_id):
        return self.db.execute(
            f"SELECT * FROM cases WHERE target_id=? AND {_OPEN_SQL} ORDER BY id DESC LIMIT 1",
            (target_id,)).fetchone()

    def _new_case(self, target_id, target_name, status, manager=None, completion_text=None):
        now = time.time()
        cur = self.db.execute(
            "INSERT INTO cases (target_id, target_name, completion_text, manager, status, created, updated) "
            "VALUES (?,?,?,?,?,?,?)", (target_id, target_name, completion_text, manager, status, now, now))
        self.db.commit()
        return self.case(cur.lastrowid)

    def _set(self, case_id, **fields):
        fields["updated"] = time.time()
        cols = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE cases SET {cols} WHERE id=?", (*fields.values(), case_id))
        self.db.commit()

    def _request(self, case, m):
        """준비 확인요청을 올리는 행동. 이전 요청 메시지는 더 이상 인정하지 않는다."""
        self._set(case["id"], status=WAIT_CONFIRM, request_chat_id=None, request_msg_id=None, others_spoke=0)
        text = render(self.request_template(), case["id"], case["target_name"], m["name"])
        return [("request", case["id"], m["group_id"], text),
                ("me", f"📨 #{case['id']} {case['target_name']} 완성 → {m['name']} 단톡방({m['group_title']})에 "
                       f"준비 확인요청")]

    # ───────── 5단계: 내가 /확정 ─────────

    def confirm_booking(self, target_id, target_name, manager_name):
        """대상의 담당자를 확정한다. 안내 문구를 보내고, 이미 완성이 왔으면 바로 확인요청까지."""
        m = self.find_manager(manager_name)
        if not m:
            return [("me", f"❗ '{manager_name}' 담당자가 없습니다. 등록된 담당자: {self._manager_names()}")]
        manager_name = m["name"]
        case = self.open_case_for(target_id)
        if case and case["status"] == SENDING:
            return [("me", f"❗ #{case['id']} 건은 지금 주소 발송 중이라 바꿀 수 없습니다.")]
        if case and case["manager"] == manager_name and case["status"] != WAIT_ASSIGN:
            return [("me", f"ℹ️ #{case['id']} {target_name} 님은 이미 {manager_name} 님으로 확정되어 있습니다 "
                           f"({case['status']}).")]

        actions = []
        if not case:
            case = self._new_case(target_id, target_name, WAIT_COMPLETE, manager=manager_name)
            head = (f"📌 #{case['id']} {target_name} → {manager_name} 확정. "
                    + ("완성 알림이 오면 단톡방에 자동으로 확인요청합니다." if self.auto_request()
                       else f"완성 알림이 오면 여기로 알려 드립니다. 확인 후 → /완성 {target_name}"))
        else:
            before = case["manager"]
            self._set(case["id"], manager=manager_name)
            case = self.case(case["id"])
            head = (f"📌 #{case['id']} {target_name} → {manager_name} 확정"
                    + (f" (변경 전: {before})" if before else ""))

        if m["guide"]:
            actions.append(("send", target_id, render_guide(m["guide"], target_name, manager_name)))
            head += "\n안내 문구를 보냈습니다."
        else:
            head += f"\n⚠️ {manager_name} 님 안내 문구가 없어 보내지 않았습니다. (/안내문구 {manager_name} | 문구)"
        actions.append(("me", head))

        if case["status"] in (WAIT_ASSIGN, WAIT_CONFIRM):  # 이미 완성이 왔던 건 → 바로 (다시) 확인요청
            actions += self._request(case, m)
        return actions

    def assign(self, case_id, manager_name, force=False):
        """번호로 확정: /확정 3 박"""
        case = self.case(case_id)
        if not case:
            return [("me", f"❗ #{case_id} 건이 없습니다. /대기 로 번호를 확인해 주세요.")]
        if case["status"] not in OPEN_STATES:
            return [("me", f"❗ #{case_id} 건은 이미 {case['status']} 상태입니다.")]
        return self.confirm_booking(case["target_id"], case["target_name"], manager_name)

    def rerequest(self, case_id):
        case = self.case(case_id)
        if not case or case["status"] != WAIT_CONFIRM:
            return [("me", f"❗ #{case_id} 건은 확인대기 상태가 아닙니다.")]
        m = self.manager(case["manager"])
        if not m:
            return [("me", f"❗ #{case_id} 건의 담당자 '{case['manager']}'가 삭제되었습니다. /확정 으로 다시 지정해 주세요.")]
        return self._request(case, m)

    def set_request(self, case_id, chat_id, msg_id):
        self._set(case_id, request_chat_id=chat_id, request_msg_id=msg_id)

    def cancel(self, case_id):
        case = self.case(case_id)
        if not case or case["status"] not in (WAIT_ASSIGN, WAIT_COMPLETE, WAIT_CONFIRM):
            return [("me", f"❗ #{case_id} 건은 취소할 수 있는 상태가 아닙니다.")]
        self._set(case_id, status=CANCELED)
        return [("me", f"🗑 #{case_id} {case['target_name']} 건을 취소했습니다.")]

    # ───────── 6단계: 대상이 '완성' ─────────

    def on_completion(self, target_id, target_name, text):
        words = self.completion_words()
        if not self.auto_request():
            return self._notify_completion(target_id, target_name, text, words)
        if not is_completion(text, words):
            case = self.open_case_for(target_id)
            if case and case["status"] == WAIT_COMPLETE and mentions_completion(text, words):
                # 단톡방에는 아무것도 안 보내고, 나에게만 조용히 알려 둔다
                return [("me", f"💬 #{case['id']} {target_name}: \"{_preview(text, 60)}\"\n"
                               f"→ 아직 완성 전 말로 보고 단톡방에 알리지 않았습니다.\n"
                               f"완성이 맞으면 → /완성 {case['id']}")]
            return []
        return self._complete(target_id, target_name, text)

    def _notify_completion(self, target_id, target_name, text, words):
        """직접 확인 모드: 완성 관련 말이 오면 나에게만 알린다. 단톡방 요청은 내가 /완성 으로."""
        if not mentions_completion(text, words):
            return []
        case = self.open_case_for(target_id)
        looks = "완성 알림으로 보입니다" if is_completion(text, words) else "완성 전 말일 수도 있습니다"
        if case and case["status"] == WAIT_COMPLETE:
            return [("me", f"📦 #{case['id']} {target_name}: \"{_preview(text, 80)}\"\n({looks})\n"
                           f"완성이 맞으면 → /완성 {case['id']}   ({case['manager']} 단톡방에 요청이 올라갑니다)")]
        if case:
            return []  # 이미 요청이 올라간 건 → 조용히
        return [("me", f"📦 {target_name}: \"{_preview(text, 80)}\"\n({looks}) 예약 확정된 건이 없습니다.\n"
                       f"→ /확정 {target_name} 담당자이름  한 뒤  /완성 {target_name}")]

    def force_completion(self, case_id):
        """/완성 번호 — 완성 알림으로 못 알아들은 건을 완성으로 처리한다."""
        case = self.case(case_id)
        if not case or case["status"] not in (WAIT_COMPLETE, WAIT_ASSIGN):
            return [("me", f"❗ #{case_id} 건은 완성대기 상태가 아닙니다. (/대기 로 확인)")]
        if case["status"] == WAIT_ASSIGN:
            return [("me", f"ℹ️ #{case_id} 건은 이미 완성으로 접수되어 있고 담당자 확정을 기다립니다. "
                           f"→ /확정 {case['target_name']} 담당자이름")]
        return self._complete(case["target_id"], case["target_name"], "(/완성 으로 직접 처리)")

    def _complete(self, target_id, target_name, text):
        case = self.open_case_for(target_id)
        if case and case["status"] == WAIT_COMPLETE:
            self._set(case["id"], completion_text=text)
            m = self.manager(case["manager"])
            if not m:
                self._set(case["id"], status=WAIT_ASSIGN, manager=None)
                return [("me", f"❗ #{case['id']} {target_name} 완성 알림이 왔는데 담당자 '{case['manager']}'가 "
                               f"삭제되었습니다. → /확정 {target_name} 담당자이름")]
            return self._request(self.case(case["id"]), m)
        if case:
            return [("me", f"ℹ️ #{case['id']} {target_name} 님이 '완성'을 다시 보냈습니다 "
                           f"(현재: {case['status']}).\n원문: {_preview(text)}")]
        case = self._new_case(target_id, target_name, WAIT_ASSIGN, completion_text=text)
        return [("me", f"🆕 #{case['id']} {target_name} 완성 알림 — 확정된 담당자가 없습니다.\n"
                       f"원문: {_preview(text)}\n\n"
                       f"담당자를 정해 주세요 → /확정 {target_name} 담당자이름\n"
                       f"등록된 담당자: {self._manager_names()}")]

    # ───────── 7단계: 단톡방 답장 ─────────

    def on_group_reply(self, chat_id, reply_to_msg_id, sender_id, sender_name, text):
        if not reply_to_msg_id:
            return []
        case = self.db.execute(
            "SELECT * FROM cases WHERE request_chat_id=? AND request_msg_id=?",
            (chat_id, reply_to_msg_id)).fetchone()
        if not case:
            return []  # 내 요청이 아닌 메시지에 대한 답장 → 다른 배정자 건이므로 무시
        kind = classify_reply(text, self.confirm_words())
        m = self.manager(case["manager"]) if case["manager"] else None
        if case["status"] != WAIT_CONFIRM:
            if kind == "confirm":
                return [("me", f"ℹ️ #{case['id']} 건은 이미 {case['status']} 상태라 주소를 다시 보내지 않았습니다. "
                               f"({sender_name}: {_preview(text)})")]
            return []
        if not m or sender_id != m["user_id"]:
            if kind:
                return [("me", f"⚠️ #{case['id']} 요청에 담당자가 아닌 {sender_name} 님이 답장했습니다. "
                               f"무시했습니다.\n내용: {_preview(text)}")]
            return []
        if kind == "confirm":
            self._set(case["id"], status=SENDING)  # 답장이 연달아 와도 주소는 한 번만
            return [("deliver", case["id"], case["target_id"], m["address"])]
        if kind == "reject":
            return [("me", f"↩️ #{case['id']} {case['target_name']} 건을 {m['name']} 님이 반려했습니다.\n"
                           f"내용: {_preview(text, 200)}\n다시 요청: /재요청 {case['id']}  ·  취소: /취소 {case['id']}")]
        return [("me", f"💬 #{case['id']} {m['name']} 님 답장 (준비 확인으로 보지 않음): {_preview(text, 200)}")]

    def on_group_message(self, chat_id, reply_to_msg_id, sender_id, sender_name, text):
        """단톡방의 모든 메시지(내가 보낸 것 제외). 답장이면 on_group_reply, 아니면 답장 없이 한 확인 처리."""
        if reply_to_msg_id:
            mine = self.db.execute("SELECT 1 FROM cases WHERE request_chat_id=? AND request_msg_id=?",
                                   (chat_id, reply_to_msg_id)).fetchone()
            if mine:
                return self.on_group_reply(chat_id, reply_to_msg_id, sender_id, sender_name, text)

        waiting = self.db.execute(
            "SELECT * FROM cases WHERE request_chat_id=? AND status=? ORDER BY id",
            (chat_id, WAIT_CONFIRM)).fetchall()
        if not waiting:
            return []
        managers = {c["manager"]: self.manager(c["manager"]) for c in waiting}
        mine = [c for c in waiting if managers[c["manager"]] and managers[c["manager"]]["user_id"] == sender_id]

        if not mine:
            # 담당자가 아닌 사람(다른 배정자 등)이 말함 → 이후 '답장 없는 확인'은 누구 건인지 확실하지 않다
            for c in waiting:
                self._set(c["id"], others_spoke=1)
            return []
        if reply_to_msg_id:
            return []  # 담당자가 내 요청이 아닌 다른 메시지에 답장 → 다른 배정자 건

        kind = classify_reply(text, self.confirm_words())
        if kind is None:
            return []
        norm = normalize(text)
        picked = [c for c in mine if re.search(rf"#{c['id']}(?!\d)", norm)
                  or normalize(c["target_name"]) in norm] or mine
        name = managers[mine[0]["manager"]]["name"]
        if kind == "reject":
            ids = ", ".join(f"#{c['id']}" for c in picked)
            return [("me", f"↩️ {ids} {name} 님이 단톡방에 반려 메시지를 남겼습니다 (답장 아님).\n내용: {_preview(text, 200)}")]
        if len(picked) > 1:
            options = "\n".join(f" · #{c['id']} {c['target_name']} → /전달 {c['id']}" for c in picked)
            return [("me", f"❓ {name} 님이 답장 없이 \"{_preview(text)}\"라고 했는데, 확인대기 건이 여러 개라 "
                           f"어느 건인지 몰라 보내지 않았습니다.\n{options}")]
        case = picked[0]
        if case["others_spoke"]:
            return [("me", f"⚠️ #{case['id']} {name} 님이 답장 없이 \"{_preview(text)}\"라고 했지만, 요청 이후 "
                           f"다른 사람이 단톡방에 말해서 다른 배정자 건일 수 있어 자동으로 보내지 않았습니다.\n"
                           f"#{case['id']} {case['target_name']} 건이 맞으면 → /전달 {case['id']}")]
        self._set(case["id"], status=SENDING)
        return [("deliver", case["id"], case["target_id"], managers[case["manager"]]["address"])]

    def force_deliver(self, case_id):
        """/전달 번호 — 확인대기 건의 주소를 직접 보내게 한다."""
        case = self.case(case_id)
        if not case or case["status"] != WAIT_CONFIRM:
            return [("me", f"❗ #{case_id} 건은 확인대기 상태가 아닙니다. (/대기 로 확인)")]
        m = self.manager(case["manager"])
        if not m:
            return [("me", f"❗ #{case_id} 건의 담당자 '{case['manager']}'가 삭제되었습니다.")]
        self._set(case_id, status=SENDING)
        return [("deliver", case_id, case["target_id"], m["address"])]

    def mark_done(self, case_id):
        self._set(case_id, status=DONE)
        case = self.case(case_id)
        return [("me", f"✅ #{case_id} {case['manager']} 준비 확인 → {case['target_name']} 님에게 주소 발송 완료")]

    def delivery_failed(self, case_id, error):
        self._set(case_id, status=WAIT_CONFIRM)
        return [("me", f"❌ #{case_id} 주소 발송 실패: {error}\n건은 확인대기로 남아 있습니다. "
                       f"담당자가 다시 답장하거나, 직접 보내고 /취소 {case_id} 하세요.")]


def unknown_placeholders(text, allowed):
    """{홍길동} 처럼 잘못 쓴 자리표시를 찾아 돌려준다."""
    return [p for p in re.findall(r"\{([^{}]*)\}", text or "") if p not in allowed]


def render_guide(guide, target_name, manager_name):
    return guide.replace("{대상}", target_name or "").replace("{담당자}", manager_name or "")
