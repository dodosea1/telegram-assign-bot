#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
텔레그램 키워드 자동 안내 프로그램 (개인 계정용)

- 1:1 대화로 들어온 메시지에 등록한 키워드가 있으면 안내 문구를 자동 발송
- 키워드/안내 문구는 텔레그램 '저장한 메시지'에 명령을 보내서 관리
- PC(Windows/Mac)와 안드로이드(Termux)에서 같은 파일로 구동

실행:  python telegram_autoreply.py
"""
import asyncio
import json
import os
import random
import re
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

from workflow import Workflow, parse_words, render, render_guide, unknown_placeholders

BASE = Path(__file__).resolve().parent
CONFIG_FILE = BASE / "config.json"      # api_id / api_hash (외부 공유 금지)
RULES_FILE = BASE / "rules.json"        # 키워드와 안내 문구
LOG_FILE = BASE / "autoreply.log"       # 발송 기록
SESSION_NAME = str(BASE / "autoreply")  # 로그인 정보 (autoreply.session, 외부 공유 금지)
WORKFLOW_DB = BASE / "automation.db"    # 담당자·완성 건 기록

LOGIN_ONLY = "--login" in sys.argv       # 로그인만 하고 종료 (폰 설치 때)
BACKGROUND = "--background" in sys.argv  # 입력을 묻지 않음 (폰에서 버튼으로 켤 때)
NEED_LOGIN_EXIT = 3                      # 로그인이 안 되어 있을 때 종료 코드
DEVICE = os.environ.get("TELE_DEVICE", "PC")

TELEGRAM_SERVICE_ID = 777000            # 텔레그램 공식 알림 계정 (로그인 코드 등)
MAX_ANSWER_LEN = 4000                   # 텔레그램 메시지 길이 한도(4096) 안쪽

HELP_TEXT = """📋 자동 안내 명령어 (이 '저장한 메시지' 방에서만 동작)

/추가 키워드1, 키워드2 | 안내 문구
  → 키워드 중 하나라도 보이면 안내 문구 발송 (문구는 여러 줄 가능)
/목록
  → 등록된 키워드와 번호 보기
/보기 번호
  → 해당 번호의 안내 문구 전체 보기
/수정 번호 | 새 안내 문구
/키워드 번호 | 새 키워드1, 새 키워드2
/삭제 번호
/테스트 문장
  → 상대가 그 문장을 보내면 어떤 안내가 나가는지 미리 보기
/끄기  /켜기
  → 자동 발송 일시 중지 / 재개
/간격 분
  → 같은 사람에게 같은 안내를 다시 보내지 않는 시간 (0 = 제한 없음)
/상태
/도움말

📦 예약 확정 → 완성 → 준비 확인 → 주소 전달
/확정 대상이름 담당자이름
  → 예약 확정. 담당자 안내 문구를 대상에게 보냄 (번호로도 가능: /확정 3 박)
    대상이 '완성' 같은 말을 하면 여기로 📦 알림이 옵니다
/완성 대상이름 (또는 /완성 번호)
  → 완성을 직접 확인한 뒤 보내면 담당자 단톡방에 준비 확인요청을 올림
/대기
  → 진행 중인 건 보기
/재요청 번호 · /취소 번호
/전달 번호
  → 담당자 확인이 애매해서 자동으로 안 보낸 건의 주소를 직접 보냄

[담당자 설정]
/담당자추가 이름 | 단톡방 이름 | 주소
  → 단톡방 멤버 중 그 이름인 사람을 담당자로 등록 (주소는 여러 줄 가능)
  → 이름으로 못 찾으면: /담당자추가 이름 | 단톡방 이름 | @아이디 | 주소
/안내문구 이름 | 예약 확정 때 대상에게 보낼 문구
  → {대상} {담당자} 를 쓰면 이름으로 바뀜
/담당자목록 · /담당자보기 이름
/담당자주소 이름 | 새 주소
/담당자삭제 이름
/요청문구 단톡방에 올릴 준비 확인요청 문구
  → {번호} {대상} {담당자} 사용 가능. '/요청문구 기본'이면 처음 문구로
/완성단어 완성, 완료, 다됐어요
  → 대상이 이 말을 하면 📦 알림을 보냄 (쉼표로 구분)
/자동요청 켜기 · /자동요청 끄기
  → 켜면 완성 알림을 알아듣는 즉시 /완성 없이 단톡방에 요청 (기본: 꺼짐)
/확인단어 확인, 올려
  → 담당자가 쓰면 준비됨으로 볼 말
  (뒤에 아무것도 안 쓰면 지금 값을 보여 줌, '기본'이면 처음 값으로)"""


# ───────────────────────── 저장소 ─────────────────────────

def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def _save_json(path, data):
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


class Store:
    """rules.json 을 읽고 쓰는 저장소."""

    def __init__(self, path=RULES_FILE):
        self.path = path
        data = _load_json(path, {})
        self.enabled = data.get("enabled", True)
        self.cooldown_min = data.get("cooldown_min", 10)
        self.next_id = data.get("next_id", 1)
        self.rules = data.get("rules", [])   # [{"id", "keywords": [...], "answer"}]

    def save(self):
        _save_json(self.path, {
            "enabled": self.enabled,
            "cooldown_min": self.cooldown_min,
            "next_id": self.next_id,
            "rules": self.rules,
        })

    def get(self, rule_id):
        for r in self.rules:
            if r["id"] == rule_id:
                return r
        return None


# ───────────────────────── 키워드 매칭 ─────────────────────────

def normalize(text):
    """띄어쓰기와 대소문자 차이를 무시하기 위한 정규화."""
    return re.sub(r"\s+", "", text).casefold()


def find_matches(text, rules):
    """메시지에 키워드가 포함된 규칙들을 등록 순서대로 반환."""
    norm = normalize(text)
    matched = []
    for rule in rules:
        if any(normalize(k) in norm for k in rule["keywords"] if normalize(k)):
            matched.append(rule)
    return matched


class Cooldown:
    """같은 사람에게 같은 안내를 일정 시간 안에 반복 발송하지 않도록 기억."""

    def __init__(self):
        self._last = {}

    def filter(self, user_id, rules, cooldown_min, now=None):
        now = time.time() if now is None else now
        limit = cooldown_min * 60
        return [r for r in rules
                if limit <= 0 or now - self._last.get((user_id, r["id"]), 0) >= limit]

    def mark(self, user_id, rules, now=None):
        now = time.time() if now is None else now
        for r in rules:
            self._last[(user_id, r["id"])] = now


# ───────────────────────── 명령 처리 ─────────────────────────

def _parse_keywords(raw):
    seen, out = set(), []
    for k in raw.split(","):
        k = k.strip()
        if k and normalize(k) not in seen:
            seen.add(normalize(k))
            out.append(k)
    return out


def _parse_id(raw):
    raw = raw.strip()
    return int(raw) if raw.isdigit() else None


def _preview(text, n=30):
    one = " ".join(text.split())
    return one if len(one) <= n else one[:n] + "…"


def handle_command(text, store):
    """'저장한 메시지'에 입력된 명령을 처리하고 답장 문구를 돌려준다. 명령이 아니면 None."""
    text = text.strip()
    if not text.startswith("/"):
        return None
    parts = text.split(None, 1)
    cmd = parts[0]
    rest = parts[1] if len(parts) > 1 else ""

    if cmd in ("/도움말", "/help", "/start"):
        return HELP_TEXT

    if cmd == "/추가":
        if "|" not in rest:
            return "❗ 형식: /추가 키워드1, 키워드2 | 안내 문구"
        kw_raw, answer = rest.split("|", 1)
        keywords, answer = _parse_keywords(kw_raw), answer.strip()
        if not keywords or not answer:
            return "❗ 키워드와 안내 문구를 모두 입력해 주세요.\n형식: /추가 키워드1, 키워드2 | 안내 문구"
        if len(answer) > MAX_ANSWER_LEN:
            return f"❗ 안내 문구가 너무 깁니다. ({len(answer)}자 / 최대 {MAX_ANSWER_LEN}자)"
        rule = {"id": store.next_id, "keywords": keywords, "answer": answer}
        store.rules.append(rule)
        store.next_id += 1
        store.save()
        return f"✅ {rule['id']}번 등록\n키워드: {', '.join(keywords)}\n안내: {_preview(answer, 60)}"

    if cmd == "/목록":
        if not store.rules:
            return "📭 등록된 키워드가 없습니다.\n/추가 키워드 | 안내 문구 로 등록하세요."
        lines = [f"📋 등록된 안내 {len(store.rules)}개"]
        for r in store.rules:
            lines.append(f"\n{r['id']}번 · {', '.join(r['keywords'])}\n   → {_preview(r['answer'])}")
        return "\n".join(lines)

    if cmd == "/보기":
        rule = store.get(_parse_id(rest))
        if not rule:
            return "❗ 형식: /보기 번호  (번호는 /목록 에서 확인)"
        return f"🔎 {rule['id']}번\n키워드: {', '.join(rule['keywords'])}\n\n{rule['answer']}"

    if cmd == "/수정":
        if "|" not in rest:
            return "❗ 형식: /수정 번호 | 새 안내 문구"
        id_raw, answer = rest.split("|", 1)
        rule, answer = store.get(_parse_id(id_raw)), answer.strip()
        if not rule:
            return "❗ 해당 번호가 없습니다. /목록 에서 번호를 확인해 주세요."
        if not answer:
            return "❗ 새 안내 문구를 입력해 주세요."
        if len(answer) > MAX_ANSWER_LEN:
            return f"❗ 안내 문구가 너무 깁니다. ({len(answer)}자 / 최대 {MAX_ANSWER_LEN}자)"
        rule["answer"] = answer
        store.save()
        return f"✅ {rule['id']}번 안내 문구 수정 완료"

    if cmd == "/키워드":
        if "|" not in rest:
            return "❗ 형식: /키워드 번호 | 새 키워드1, 새 키워드2"
        id_raw, kw_raw = rest.split("|", 1)
        rule, keywords = store.get(_parse_id(id_raw)), _parse_keywords(kw_raw)
        if not rule:
            return "❗ 해당 번호가 없습니다. /목록 에서 번호를 확인해 주세요."
        if not keywords:
            return "❗ 새 키워드를 입력해 주세요."
        rule["keywords"] = keywords
        store.save()
        return f"✅ {rule['id']}번 키워드 변경: {', '.join(keywords)}"

    if cmd == "/삭제":
        rule = store.get(_parse_id(rest))
        if not rule:
            return "❗ 형식: /삭제 번호  (번호는 /목록 에서 확인)"
        store.rules.remove(rule)
        store.save()
        return f"🗑 {rule['id']}번 삭제 ({', '.join(rule['keywords'])})"

    if cmd == "/테스트":
        if not rest.strip():
            return "❗ 형식: /테스트 상대가 보낼 법한 문장\n(예: /테스트 택배 언제 오나요?)"
        matched = find_matches(rest, store.rules)
        if not matched:
            return "🧪 테스트 결과: 일치하는 키워드가 없어 아무것도 보내지 않습니다."
        lines = [f"🧪 테스트 결과: 상대가 이렇게 보내면 아래 안내 {len(matched)}개가 발송됩니다."]
        for r in matched:
            lines.append(f"\n── {r['id']}번 ({', '.join(r['keywords'])}) ──\n{r['answer']}")
        if not store.enabled:
            lines.append("\n⚠️ 지금은 자동 안내가 꺼져 있어 실제로는 발송되지 않습니다. (/켜기)")
        return "\n".join(lines)

    if cmd == "/켜기":
        store.enabled = True
        store.save()
        return "▶️ 자동 안내를 켰습니다."

    if cmd == "/끄기":
        store.enabled = False
        store.save()
        return "⏸ 자동 안내를 껐습니다. (/켜기 로 재개)"

    if cmd == "/간격":
        minutes = _parse_id(rest)
        if minutes is None:
            return "❗ 형식: /간격 분  (예: /간격 10, 제한 없음은 /간격 0)"
        store.cooldown_min = minutes
        store.save()
        return (f"⏱ 같은 사람에게 같은 안내는 {minutes}분에 한 번만 보냅니다."
                if minutes else "⏱ 재발송 제한을 해제했습니다.")

    if cmd == "/상태":
        state = "켜짐 ▶️" if store.enabled else "꺼짐 ⏸"
        gap = f"{store.cooldown_min}분" if store.cooldown_min else "제한 없음"
        return f"ℹ️ 자동 안내: {state}\n등록된 안내: {len(store.rules)}개\n재발송 간격: {gap}"

    return "❓ 모르는 명령입니다. /도움말 을 보내 보세요."


# ───────────────────────── 실행 ─────────────────────────

def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


KEYWORD_COMMANDS = ("/추가", "/목록", "/보기", "/수정", "/키워드", "/삭제", "/테스트",
                    "/켜기", "/끄기", "/간격", "/상태", "/도움말")
WORKFLOW_COMMANDS = ("/담당자추가", "/담당자목록", "/담당자보기", "/담당자주소", "/담당자삭제",
                     "/안내문구", "/요청문구", "/완성단어", "/확인단어", "/자동요청",
                     "/확정", "/대기", "/완성", "/재요청", "/전달", "/취소")


def _display_name(entity):
    if entity is None:
        return "?"
    name = " ".join(filter(None, [getattr(entity, "first_name", None),
                                  getattr(entity, "last_name", None)]))
    return name or getattr(entity, "title", None) or getattr(entity, "username", None) or str(entity.id)


async def _find_group(client, query):
    """제목에 query가 들어간 단톡방을 찾는다. (dialog, 오류문구)"""
    q = normalize(query)
    groups = [d async for d in client.iter_dialogs() if d.is_group]
    found = [d for d in groups if q in normalize(d.name)]
    exact = [d for d in found if normalize(d.name) == q]
    if len(exact) == 1:
        return exact[0], None
    if len(found) == 1:
        return found[0], None
    if not found:
        names = "\n".join(f" · {d.name}" for d in groups[:20]) or " (단톡방 없음)"
        return None, f"❗ '{query}'가 들어간 단톡방을 찾지 못했습니다.\n내 단톡방(최근 순):\n{names}"
    names = "\n".join(f" · {d.name}" for d in found[:10])
    return None, f"❗ '{query}'에 해당하는 단톡방이 여러 개입니다. 더 정확히 써 주세요.\n{names}"


def _member_line(u):
    return f" · {_display_name(u)}" + (f" (@{u.username})" if u.username else "")


async def _find_member(client, group, query, my_id=None):
    """단톡방 멤버 중 @아이디 또는 이름으로 담당자를 찾는다. (user, 오류문구)"""
    members = [u for u in await client.get_participants(group.entity) if u.id != my_id]
    q = query.strip().lstrip("@").casefold()
    by_username = [u for u in members if (u.username or "").casefold() == q]
    if len(by_username) == 1:
        return by_username[0], None
    nq = normalize(query.strip().lstrip("@"))
    by_name = [u for u in members if nq and nq in normalize(_display_name(u))]
    if len(by_name) == 1:
        return by_name[0], None
    if not by_name:
        listing = "\n".join(_member_line(u) for u in members[:20])
        return None, (f"❗ '{group.name}' 단톡방 멤버 중 '{query}'를 찾지 못했습니다.\n"
                      f"이 단톡방 멤버:\n{listing}\n\n"
                      f"이 중 담당자의 이름이나 @아이디를 써 주세요.")
    listing = "\n".join(_member_line(u) for u in by_name[:10])
    return None, f"❗ '{query}'에 해당하는 멤버가 여러 명입니다. @아이디로 써 주세요.\n{listing}"


async def handle_workflow_command(text, wf, client):
    """완성-확인 흐름 명령. 명령이 아니면 None, 아니면 (답장문구 또는 None, 실행할 행동 목록)."""
    text = text.strip()
    parts = text.split(None, 1)
    if not parts or parts[0] not in WORKFLOW_COMMANDS:
        return None
    cmd, rest = parts[0], (parts[1] if len(parts) > 1 else "")

    if cmd == "/담당자추가":
        fields = [f.strip() for f in rest.split("|", 3)]
        usage = ("❗ 형식: /담당자추가 이름 | 단톡방 이름 | 주소\n"
                 "  (단톡방에서 이름으로 못 찾으면: /담당자추가 이름 | 단톡방 이름 | @아이디 | 주소)")
        if len(fields) == 3 and all(fields):
            name, group_q, address = fields
            member_q = name  # 계정을 안 쓰면 담당자 이름으로 단톡방 멤버를 찾는다
        elif len(fields) == 4 and all(fields):
            name, group_q, member_q, address = fields
        else:
            return usage, []
        if len(address) > MAX_ANSWER_LEN:
            return f"❗ 주소가 너무 깁니다. ({len(address)}자)", []
        group, err = await _find_group(client, group_q)
        if err:
            return err, []
        user, err = await _find_member(client, group, member_q, my_id=(await client.get_me()).id)
        if err:
            return err, []
        label = _display_name(user) + (f" (@{user.username})" if user.username else "")
        wf.add_manager(name, group.id, group.name, user.id, label, address)
        return (f"✅ 담당자 '{name}' 등록\n단톡방: {group.name}\n계정: {label}\n주소:\n{address}"), []

    if cmd == "/담당자목록":
        ms = wf.managers()
        if not ms:
            return "📭 등록된 담당자가 없습니다. /담당자추가 로 등록하세요.", []
        lines = [f"👥 담당자 {len(ms)}명"]
        for m in ms:
            cases = wf.manager_cases(m["name"])
            state = ", ".join(f"#{c['id']} {c['target_name']}({c['status']})" for c in cases) or "진행 중인 건 없음"
            guide = _preview(m["guide"], 40) if m["guide"] else "없음 ⚠️"
            lines.append(f"\n{m['name']} · {state}\n   단톡방: {m['group_title']}\n   계정: {m['user_label']}\n"
                         f"   주소: {_preview(m['address'], 40)}\n   안내 문구: {guide}")
        return "\n".join(lines), []

    if cmd == "/담당자보기":
        m = wf.manager(rest.strip())
        if not m:
            return f"❗ '{rest.strip()}' 담당자가 없습니다.", []
        return (f"🔎 {m['name']}\n단톡방: {m['group_title']}\n계정: {m['user_label']}\n\n[주소]\n{m['address']}\n\n"
                f"[안내 문구]\n{m['guide'] or '(없음)'}"), []

    if cmd == "/안내문구":
        if "|" not in rest:
            return "❗ 형식: /안내문구 담당자이름 | 예약 확정 때 보낼 문구  ({대상} {담당자} 사용 가능)", []
        name, guide = (s.strip() for s in rest.split("|", 1))
        if len(guide) > MAX_ANSWER_LEN:
            return f"❗ 문구가 너무 깁니다. ({len(guide)}자)", []
        bad = unknown_placeholders(guide, ("대상", "담당자"))
        if bad:
            return (f"❗ 중괄호 안에는 글자 그대로 {{대상}} 또는 {{담당자}}만 쓸 수 있습니다. "
                    f"(지금: {', '.join('{' + b + '}' for b in bad)})\n"
                    f"실제 이름은 보낼 때 자동으로 들어갑니다.\n"
                    f"예: /안내문구 {name} | {{대상}}님, {{담당자}} 담당자로 예약 확정되었습니다."), []
        m = wf.find_manager(name)
        if not m:
            return f"❗ '{name}' 담당자가 없습니다. 등록된 담당자: {wf._manager_names()}", []
        name = m["name"]
        wf.set_guide(name, guide)
        if not guide:
            return f"✅ '{name}' 안내 문구를 지웠습니다.", []
        return f"✅ '{name}' 안내 문구 저장\n── 예시 (대상: 홍길동) ──\n{render_guide(guide, '홍길동', name)}", []

    if cmd == "/자동요청":
        arg = rest.strip()
        if arg in ("켜기", "켬", "on"):
            wf.set_auto_request(True)
        elif arg in ("끄기", "끔", "off"):
            wf.set_auto_request(False)
        elif arg:
            return "❗ 형식: /자동요청 켜기  또는  /자동요청 끄기", []
        if wf.auto_request():
            state = ("켜짐 ▶️ 대상이 완성 알림을 보내면 바로 단톡방에 요청합니다.\n"
                     "(완성 전 말로 보이면 나에게만 알림 → /완성)")
        else:
            state = ("꺼짐 ⏸ 대상이 완성 관련 말을 하면 나에게만 📦 알림이 옵니다.\n"
                     "직접 확인 후 /완성 대상이름 으로 단톡방에 요청하세요.")
        return f"⚙️ 자동 요청: {state}", []

    if cmd in ("/완성단어", "/확인단어"):
        is_done = cmd == "/완성단어"
        what = "대상이 하면 📦 완성 알림을 보낼 말" if is_done else "담당자가 쓰면 '준비됨'으로 볼 말"
        current = wf.completion_words() if is_done else wf.confirm_words()
        text = rest.strip()
        if not text:
            return (f"📝 {what}\n지금: {', '.join(current)}\n\n"
                    f"바꾸기: {cmd} 단어1, 단어2  (쉼표로 구분, 들어 있기만 하면 됨)\n처음 값으로: {cmd} 기본"), []
        words = None if text == "기본" else parse_words(text)
        if words is not None and not words:
            return f"❗ 단어를 하나 이상 써 주세요. (예: {cmd} {', '.join(current)})", []
        (wf.set_completion_words if is_done else wf.set_confirm_words)(words)
        now = wf.completion_words() if is_done else wf.confirm_words()
        return f"✅ {what}: {', '.join(now)}", []

    if cmd == "/요청문구":
        text = rest.strip()
        if not text:
            return (f"📝 지금 요청 문구\n{wf.request_template()}\n\n"
                    "바꾸기: /요청문구 새 문구  ({번호} {대상} {담당자} 사용 가능)\n처음 문구로: /요청문구 기본"), []
        bad = unknown_placeholders(text, ("번호", "대상", "담당자"))
        if bad and text != "기본":
            return (f"❗ 중괄호 안에는 글자 그대로 {{번호}} {{대상}} {{담당자}}만 쓸 수 있습니다. "
                    f"(지금: {', '.join('{' + b + '}' for b in bad)})\n"
                    f"예: /요청문구 [#{{번호}}] {{대상}} 님 완성됐습니다. 준비되시면 답장 부탁드립니다."), []
        wf.set_request_template(None if text == "기본" else text)
        return f"✅ 요청 문구 저장\n── 예시 ──\n{render(wf.request_template(), 3, '홍길동', '박')}", []

    if cmd == "/담당자주소":
        if "|" not in rest:
            return "❗ 형식: /담당자주소 이름 | 새 주소", []
        name, address = (s.strip() for s in rest.split("|", 1))
        if not address:
            return "❗ 새 주소를 입력해 주세요.", []
        return (f"✅ '{name}' 주소 변경" if wf.set_address(name, address)
                else f"❗ '{name}' 담당자가 없습니다."), []

    if cmd == "/담당자삭제":
        name = rest.strip()
        if not wf.manager(name):
            return f"❗ '{name}' 담당자가 없습니다.", []
        return (f"🗑 '{name}' 삭제" if wf.delete_manager(name)
                else f"❗ '{name}' 님은 진행 중인 건이 있어 지금은 삭제할 수 없습니다. (/대기)"), []

    if cmd == "/대기":
        cases = wf.open_cases()
        if not cases:
            return "📭 진행 중인 건이 없습니다.", []
        lines = [f"📋 진행 중 {len(cases)}건"]
        for c in cases:
            who = f" · {c['manager']}" if c["manager"] else ""
            lines.append(f"#{c['id']} {c['target_name']} · {c['status']}{who}")
        return "\n".join(lines), []

    args = rest.split()
    if args and args[-1] == "강제":  # 예전 형식 호환 (이제 필요 없음)
        args = args[:-1]
    case_id = int(args[0].lstrip("#")) if args and args[0].lstrip("#").isdigit() else None

    if cmd == "/확정":
        if len(args) < 2:
            return "❗ 형식: /확정 대상이름 담당자이름  (예: /확정 홍길동 박)", []
        manager = args[-1]
        if case_id is not None and len(args) == 2:
            return None, wf.assign(case_id, manager)
        target, err = await _find_target(client, wf, " ".join(args[:-1]))
        if err:
            return err, []
        return None, wf.confirm_booking(target[0], target[1], manager)

    if cmd == "/완성" and case_id is None and args:  # 번호 대신 대상 이름도 받는다: /완성 홍길동
        q = normalize(" ".join(args))
        hits = [c for c in wf.open_cases() if normalize(c["target_name"]) == q]
        if len(hits) != 1:
            return f"❗ 진행 중인 '{' '.join(args)}' 건을 찾지 못했습니다. /대기 에서 번호를 확인해 /완성 번호 로 보내 주세요.", []
        case_id = hits[0]["id"]

    if case_id is None:
        return "❗ 번호를 써 주세요. 번호는 /대기 에서 확인", []
    if cmd == "/완성":
        return None, wf.force_completion(case_id)
    if cmd == "/재요청":
        return None, wf.rerequest(case_id)
    if cmd == "/전달":
        return None, wf.force_deliver(case_id)
    if cmd == "/취소":
        return None, wf.cancel(case_id)
    return None


async def _find_target(client, wf, query):
    """/확정 의 대상 찾기: 진행 중인 건의 대상 이름 → 1:1 대화방 이름 순. ((id, 이름), 오류문구)"""
    nq = normalize(query)
    for c in wf.open_cases():
        if normalize(c["target_name"]) == nq:
            return (c["target_id"], c["target_name"]), None
    me = await client.get_me()
    people = []
    async for d in client.iter_dialogs():
        if d.is_group or getattr(d, "is_channel", False) or getattr(d.entity, "bot", False):
            continue
        if d.id > 0 and d.id not in (me.id, TELEGRAM_SERVICE_ID):
            people.append(d)
    exact = [d for d in people if normalize(d.name) == nq]
    found = exact or [d for d in people if nq and nq in normalize(d.name)]
    if len(found) == 1:
        return (found[0].id, found[0].name), None
    if not found:
        return None, (f"❗ '{query}' 이름의 1:1 대화방을 찾지 못했습니다.\n"
                      f"대상과 주고받은 1:1 대화가 있어야 합니다. 대화방에 보이는 이름 그대로 써 주세요.")
    names = "\n".join(f" · {d.name}" for d in found[:10])
    return None, f"❗ '{query}'에 해당하는 대화방이 여러 개입니다. 정확한 이름을 써 주세요.\n{names}"


def load_config():
    cfg = _load_json(CONFIG_FILE, None)
    if cfg and cfg.get("api_id") and cfg.get("api_hash"):
        return cfg
    if BACKGROUND:
        log("설정(api_id)이 없습니다. 먼저 로그인 단계를 진행하세요. (폰: tele login)")
        sys.exit(NEED_LOGIN_EXIT)
    print("처음 실행입니다. https://my.telegram.org 에서 발급받은 값을 입력해 주세요.")
    while True:
        api_id = input("api_id (숫자): ").strip()
        if api_id.isdigit():
            break
        print("숫자만 입력해 주세요.")
    api_hash = input("api_hash: ").strip()
    cfg = {"api_id": int(api_id), "api_hash": api_hash}
    _save_json(CONFIG_FILE, cfg)
    print("config.json 에 저장했습니다.\n")
    return cfg


async def main():
    from telethon import TelegramClient, events
    from telethon.errors import FloodWaitError

    cfg = load_config()
    store = Store()
    cooldown = Cooldown()
    wf = Workflow(WORKFLOW_DB)

    client = TelegramClient(SESSION_NAME, cfg["api_id"], cfg["api_hash"])
    client.parse_mode = None  # 안내 문구를 입력한 글자 그대로 발송

    if BACKGROUND:
        await client.connect()
        if not await client.is_user_authorized():
            log("로그인이 필요합니다. (폰: tele login)")
            await client.disconnect()
            sys.exit(NEED_LOGIN_EXIT)
    else:
        await client.start(
            phone=lambda: input("전화번호 (예: +821012345678): ").strip(),
            code_callback=lambda: input("텔레그램 앱으로 온 로그인 코드: ").strip(),
            password=lambda: input("2단계 인증 비밀번호: ").strip(),
        )
    me = await client.get_me()
    if LOGIN_ONLY:
        print(f"\n✅ 로그인 완료: {me.first_name}\n")
        await client.disconnect()
        return
    log(f"로그인: {me.first_name} / 등록된 안내 {len(store.rules)}개 / "
        f"자동 안내 {'켜짐' if store.enabled else '꺼짐'}")
    print("텔레그램 '저장한 메시지'에 /도움말 을 보내면 명령어를 볼 수 있습니다.")
    print("종료하려면 Ctrl+C 를 누르세요.\n")

    async def run_actions(actions):
        """workflow 가 돌려준 행동을 실제로 실행."""
        for act in actions:
            kind = act[0]
            try:
                if kind == "me":
                    await client.send_message("me", act[1])
                elif kind == "send":
                    await client.send_message(act[1], act[2])
                    log(f"안내 발송: → {act[1]}")
                elif kind == "request":
                    _, cid, chat_id, text = act
                    msg = await client.send_message(chat_id, text)
                    wf.set_request(cid, msg.chat_id, msg.id)
                    log(f"확인요청: #{cid} → 단톡방 {chat_id}")
                elif kind == "deliver":
                    _, cid, target_id, address = act
                    try:
                        await client.send_message(target_id, address)
                    except Exception as e:
                        log(f"주소 발송 실패: #{cid} / {e!r}")
                        await run_actions(wf.delivery_failed(cid, repr(e)))
                        continue
                    log(f"주소 발송: #{cid} → {target_id}")
                    await run_actions(wf.mark_done(cid))
                    case = wf.case(cid)
                    await client.send_message(case["request_chat_id"], f"#{cid} 주소 전달 완료",
                                              reply_to=case["request_msg_id"])
            except Exception as e:  # 한 건 실패해도 프로그램은 계속 구동
                log(f"행동 실패: {kind} / {e!r}")
                if kind != "me":
                    try:
                        await client.send_message("me", f"❌ 자동 처리 중 오류 ({kind}): {e!r}")
                    except Exception:
                        pass

    @client.on(events.NewMessage())
    async def on_message(event):
        text = event.raw_text or ""

        # 1) '저장한 메시지' 방 → 관리 명령
        if event.chat_id == me.id:
            result = await handle_workflow_command(text, wf, client)
            if result is not None:
                reply, actions = result
                if reply:
                    await event.reply(reply)
                await run_actions(actions)
                log(f"명령: {text.split()[0]}")
                return
            reply = handle_command(text, store)
            if reply:
                await event.reply(reply)
                log(f"명령: {text.split()[0]}")
            return

        if not text:
            return
        if event.out:
            # 명령을 저장한 메시지가 아닌 대화방에 잘못 보낸 경우 → 상대에게 이미 전송됐으니 알려만 준다
            first = text.split()[0] if text.split() else ""
            if first in WORKFLOW_COMMANDS or first in KEYWORD_COMMANDS:
                await client.send_message("me", f"⚠️ 명령 '{first}'를 다른 대화방에 보내셨습니다. "
                                                f"명령은 '저장한 메시지'에서만 동작하고, 방금 메시지는 상대에게 "
                                                f"그대로 전송되었습니다. 필요하면 그 메시지를 삭제해 주세요.")
            return

        # 2) 단톡방에서 내 확인요청 메시지에 달린 답장 → 담당자 확인 처리
        # 2) 단톡방 메시지 → 담당자 준비 확인 처리 (답장이든 아니든)
        if event.is_group:
            sender = await event.get_sender()
            actions = wf.on_group_message(event.chat_id, event.reply_to_msg_id if event.is_reply else None,
                                          event.sender_id, _display_name(sender), text)
            await run_actions(actions)
            return

        # 3) 다른 사람이 보낸 1:1 메시지
        if not event.is_private or event.chat_id == TELEGRAM_SERVICE_ID:
            return
        sender = await event.get_sender()
        if sender is None or getattr(sender, "bot", False):
            return

        # 3-1) '완성' 알림 → 건 생성 후 나에게 알림
        await run_actions(wf.on_completion(event.chat_id, _display_name(sender), text))

        # 3-2) 키워드 자동 안내
        if not store.enabled:
            return

        matched = cooldown.filter(event.chat_id, find_matches(text, store.rules),
                                  store.cooldown_min)
        if not matched:
            return
        cooldown.mark(event.chat_id, matched)

        await asyncio.sleep(random.uniform(1.0, 2.5))  # 사람이 답하는 정도의 짧은 간격
        name = getattr(sender, "first_name", None) or str(event.chat_id)
        for rule in matched:
            try:
                await event.respond(rule["answer"])
                log(f"발송: {name} ← {rule['id']}번 ({', '.join(rule['keywords'])})")
            except FloodWaitError as e:
                log(f"텔레그램 발송 제한: {e.seconds}초 대기 필요 → 이번 발송은 건너뜀")
                return
            except Exception as e:  # 한 건 실패해도 프로그램은 계속 구동
                log(f"발송 실패: {name} ← {rule['id']}번 / {e!r}")

    # 켜짐 알림: 두 기기에서 동시에 켜면 알림이 두 번 와서 바로 알 수 있음
    try:
        await client.send_message("me", f"🟢 자동응답 켜짐 ({DEVICE})")
    except Exception as e:
        log(f"켜짐 알림 실패: {e!r}")

    stop = asyncio.Event()
    try:  # 폰에서 '끄기' 버튼(SIGTERM)을 누르면 꺼짐 알림을 보내고 종료
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stop.set)
    except (NotImplementedError, AttributeError, RuntimeError):
        pass  # Windows
    running = asyncio.ensure_future(client.run_until_disconnected())
    stopping = asyncio.ensure_future(stop.wait())
    await asyncio.wait({running, stopping}, return_when=asyncio.FIRST_COMPLETED)
    if stop.is_set():
        try:
            await client.send_message("me", f"🔴 자동응답 꺼짐 ({DEVICE})")
        except Exception:
            pass
        log("종료 요청으로 껐습니다.")
        await client.disconnect()
        return
    stopping.cancel()
    log("텔레그램 연결이 끊어졌습니다.")
    sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n종료했습니다.")
