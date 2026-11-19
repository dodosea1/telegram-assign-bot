# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import workflow as wf  # noqa: E402

GROUP_PARK, PARK = -1001, 501
GROUP_KIM, KIM = -1002, 502
OTHER_DISPATCHER = 777
A, B = 9001, 9002


def kinds(actions):
    return [a[0] for a in actions]


def find(actions, kind):
    return [a for a in actions if a[0] == kind]


class Base(unittest.TestCase):
    def setUp(self):
        self.w = wf.Workflow(":memory:")
        self.w.add_manager("박", GROUP_PARK, "박 단톡", PARK, "@park", "서울시 박주소 1")
        self.w.add_manager("김", GROUP_KIM, "김 단톡", KIM, "@kim", "부산시 김주소 2")
        self.w.set_guide("박", "{대상}님, {담당자} 담당자로 예약 확정되었습니다.")
        self.w.set_auto_request(True)  # 아래 기존 테스트는 '자동 요청' 모드 기준 (기본값은 꺼짐 → ManualModeTest)
        self.msg = 100

    def run_request(self, actions):
        """request 행동을 실제로 올린 것처럼 메시지 id를 기록하고 그 id를 돌려준다."""
        req = find(actions, "request")
        if not req:
            return None
        self.msg += 1
        self.w.set_request(req[0][1], req[0][2], self.msg)
        return self.msg

    def book(self, target=A, name="홍길동", manager="박"):
        return self.w.confirm_booking(target, name, manager)

    def complete(self, target=A, name="홍길동", text="제품 완성했어요"):
        acts = self.w.on_completion(target, name, text)
        return acts, self.run_request(acts)


class BookingTest(Base):
    def test_confirm_creates_case_and_sends_guide(self):
        acts = self.book()
        self.assertEqual(kinds(acts), ["send", "me"])
        self.assertEqual(acts[0][1], A)
        self.assertEqual(acts[0][2], "홍길동님, 박 담당자로 예약 확정되었습니다.")
        case = self.w.open_case_for(A)
        self.assertEqual((case["status"], case["manager"]), (wf.WAIT_COMPLETE, "박"))

    def test_confirm_without_guide_warns_me(self):
        acts = self.book(manager="김")
        self.assertEqual(kinds(acts), ["me"])
        self.assertIn("안내 문구가 없어", acts[0][1])

    def test_confirm_unknown_manager(self):
        acts = self.book(manager="최")
        self.assertEqual(kinds(acts), ["me"])
        self.assertIsNone(self.w.open_case_for(A))

    def test_change_manager_before_completion(self):
        self.book(manager="박")
        acts = self.book(manager="김")
        self.assertIn("변경 전: 박", find(acts, "me")[0][1])
        self.assertEqual(self.w.open_case_for(A)["manager"], "김")
        self.assertEqual(len(self.w.open_cases()), 1)

    def test_same_manager_twice_is_noop(self):
        self.book()
        acts = self.book()
        self.assertEqual(kinds(acts), ["me"])
        self.assertIn("이미", acts[0][1])

    def test_manager_name_variants(self):
        for q in ("박담당", "박 담당", "@park"):
            with self.subTest(q=q):
                self.assertEqual(self.w.find_manager(q)["name"], "박")
        self.assertIsNone(self.w.find_manager("담당"))  # 박·김 둘 다 걸리면 못 고름
        acts = self.book(manager="박담당")
        self.assertEqual(self.w.open_case_for(A)["manager"], "박")
        self.assertEqual(kinds(acts), ["send", "me"])

    def test_unknown_placeholders(self):
        self.assertEqual(wf.unknown_placeholders("{홍길동}님 {담당자}", ("대상", "담당자")), ["홍길동"])
        self.assertEqual(wf.unknown_placeholders("{대상}님 {담당자}", ("대상", "담당자")), [])

    def test_manager_can_hold_many_bookings(self):
        self.book(A, "홍길동", "박")
        acts = self.book(B, "이몽룡", "박")
        self.assertEqual(kinds(acts), ["send", "me"])
        self.assertEqual(len(self.w.manager_cases("박")), 2)


class CompletionTest(Base):
    def test_completion_after_booking_requests_immediately(self):
        self.book()
        acts, _ = self.complete()
        self.assertEqual(kinds(acts), ["request", "me"])
        self.assertEqual(acts[0][2], GROUP_PARK)
        self.assertTrue(acts[0][3].startswith("[#1] 홍길동 님 완성됐습니다."))
        self.assertEqual(self.w.open_case_for(A)["status"], wf.WAIT_CONFIRM)

    def test_completion_without_booking_asks_me(self):
        acts, _ = self.complete()
        self.assertEqual(kinds(acts), ["me"])
        self.assertIn("/확정 홍길동", acts[0][1])
        self.assertEqual(self.w.open_case_for(A)["status"], wf.WAIT_ASSIGN)
        # 나중에 확정하면 안내 + 바로 확인요청
        acts = self.book()
        self.assertEqual(kinds(acts), ["send", "me", "request", "me"])

    def test_non_completion_ignored(self):
        self.book()
        self.assertEqual(self.w.on_completion(A, "홍길동", "언제쯤 될까요"), [])
        self.assertEqual(self.w.open_case_for(A)["status"], wf.WAIT_COMPLETE)

    def test_not_yet_completed_messages_ignored(self):
        self.book()
        for text in ("완성되면 연락드릴게요", "완성 되면 말할게요", "언제 완성돼요?", "아직 완성 안 됐어요",
                     "미완성이에요", "완성 전에 여쭤볼게요", "완성 후에 말씀드릴게요", "완성하고 연락드릴게요",
                     "완성까지 좀 걸려요", "완성될 때 알려드릴게요", "완성되는 대로 말할게요", "완성 예정이에요",
                     "지금 완성 중이에요", "완성할게요", "내일쯤 완성될 것 같아요", "완성해서 보내드릴게요",
                     "거의 완성됐어요", "완성됐나요?"):
            with self.subTest(text=text):
                acts = self.w.on_completion(A, "홍길동", text)
                self.assertNotIn("request", kinds(acts))       # 단톡방에는 안 감
                self.assertEqual(kinds(acts), ["me"])          # 나에게만 조용히 알림
                self.assertIn("/완성 1", acts[0][1])
        self.assertEqual(self.w.open_case_for(A)["status"], wf.WAIT_COMPLETE)
        for text in ("완성했어요", "사장님 완성됐어요!", "완성", "완성 완료", "완성되었습니다", "완성이요~",
                     "방금 완성했습니다 ㅎㅎ", "완성했어요 사진 보내드릴게요"):
            with self.subTest(text=text):
                self.assertTrue(wf.is_completion(text))

    def test_unrelated_words_with_completion_inside(self):
        self.book()
        self.assertEqual(kinds(self.w.on_completion(A, "홍길동", "완성도가 좋네요")), ["me"])  # 단톡방엔 안 감
        self.assertEqual(self.w.open_case_for(A)["status"], wf.WAIT_COMPLETE)

    def test_no_note_without_booking(self):
        self.assertEqual(self.w.on_completion(A, "홍길동", "완성되면 말할게요"), [])
        self.assertIsNone(self.w.open_case_for(A))

    def test_force_completion(self):
        self.book()
        self.w.on_completion(A, "홍길동", "완성되면 말할게요")
        acts = self.w.force_completion(1)
        self.assertEqual(kinds(acts), ["request", "me"])
        self.assertEqual(self.w.case(1)["status"], wf.WAIT_CONFIRM)
        self.assertEqual(kinds(self.w.force_completion(1)), ["me"])  # 이미 요청 올라간 건은 다시 안 함

    def test_repeat_completion(self):
        self.book()
        self.complete()
        acts, _ = self.complete(text="완성!!")
        self.assertEqual(kinds(acts), ["me"])
        self.assertIn("다시", acts[0][1])

    def test_custom_request_template(self):
        self.w.set_request_template("{대상} 완성. {담당자}님 준비되면 올려주세요 (#{번호})")
        self.book()
        acts, _ = self.complete()
        self.assertEqual(acts[0][3], "홍길동 완성. 박님 준비되면 올려주세요 (#1)")

    def test_template_without_number_gets_prefix(self):
        self.w.set_request_template("{대상} 완성입니다")
        self.book()
        acts, _ = self.complete()
        self.assertEqual(acts[0][3], "[#1] 홍길동 완성입니다")

    def test_change_manager_after_request_moves_request(self):
        self.book(manager="박")
        _, old_msg = self.complete()
        acts = self.book(manager="김")
        self.assertEqual(find(acts, "request")[0][2], GROUP_KIM)
        new_msg = self.run_request(acts)
        self.assertEqual(self.w.on_group_reply(GROUP_PARK, old_msg, PARK, "박", "확인"), [])
        self.assertEqual(kinds(self.w.on_group_reply(GROUP_KIM, new_msg, KIM, "김", "확인")), ["deliver"])


class ReplyTest(Base):
    def setUp(self):
        super().setUp()
        self.book()
        _, self.req = self.complete()

    def reply(self, text, sender=PARK, msg=None, chat=GROUP_PARK):
        return self.w.on_group_reply(chat, msg or self.req, sender, "누군가", text)

    def test_ready_words_deliver(self):
        for word in ("확인", "확인했습니다", "올려주세요", "올려주세여", "네 올려 주세요"):
            with self.subTest(word=word):
                self.setUp()
                self.assertEqual(self.reply(word), [("deliver", 1, A, "서울시 박주소 1")])

    def test_negated_not_accepted(self):
        for word in ("확인 아직 못했어요", "나중에 올려주세요", "아직 올리지 마세요", "올려주지 마세요"):
            with self.subTest(word=word):
                self.assertNotIn("deliver", kinds(self.reply(word)))

    def test_delivers_once(self):
        self.reply("확인")
        self.assertNotIn("deliver", kinds(self.reply("올려주세요")))
        self.w.mark_done(1)
        self.assertEqual(self.w.case(1)["status"], wf.DONE)
        self.assertNotIn("deliver", kinds(self.reply("확인")))

    def test_other_dispatcher_ignored(self):
        acts = self.reply("확인", sender=OTHER_DISPATCHER)
        self.assertEqual(kinds(acts), ["me"])
        self.assertEqual(self.w.case(1)["status"], wf.WAIT_CONFIRM)

    def test_not_a_reply_or_other_message(self):
        self.assertEqual(self.w.on_group_reply(GROUP_PARK, None, PARK, "박", "확인"), [])
        self.assertEqual(self.reply("확인", msg=999), [])

    def test_reject(self):
        acts = self.reply("반려 시간 안 맞아요")
        self.assertEqual(kinds(acts), ["me"])
        self.assertEqual(self.w.case(1)["status"], wf.WAIT_CONFIRM)

    def test_delivery_failure_allows_retry(self):
        self.reply("확인")
        self.w.delivery_failed(1, "PeerFlood")
        self.assertEqual(kinds(self.reply("확인")), ["deliver"])

    def test_rerequest_invalidates_old_message(self):
        acts = self.w.rerequest(1)
        new = self.run_request(acts)
        self.assertEqual(self.reply("확인"), [])
        self.assertEqual(kinds(self.reply("확인", msg=new)), ["deliver"])

    def test_cancel(self):
        self.w.cancel(1)
        self.assertNotIn("deliver", kinds(self.reply("확인")))
        self.assertIsNone(self.w.open_case_for(A))

    def test_cannot_delete_manager_with_open_case(self):
        self.assertFalse(self.w.delete_manager("박"))
        self.assertTrue(self.w.delete_manager("김"))


class NonReplyTest(Base):
    """답장 없이 단톡방에 '확인' / '올려주세요'라고만 한 경우."""

    def setUp(self):
        super().setUp()
        self.book()
        _, self.req = self.complete()

    def say(self, text, sender=PARK, reply_to=None, chat=GROUP_PARK):
        return self.w.on_group_message(chat, reply_to, sender, "누군가", text)

    def test_plain_confirm_delivers(self):
        for word in ("확인", "올려주세요", "네 올려주세여"):
            with self.subTest(word=word):
                self.setUp()
                self.assertEqual(self.say(word), [("deliver", 1, A, "서울시 박주소 1")])

    def test_reply_still_works(self):
        self.assertEqual(kinds(self.say("확인", reply_to=self.req)), ["deliver"])

    def test_plain_confirm_from_non_manager_ignored(self):
        self.assertEqual(self.say("확인", sender=OTHER_DISPATCHER), [])
        self.assertEqual(self.w.case(1)["status"], wf.WAIT_CONFIRM)

    def test_after_other_dispatcher_spoke_not_auto(self):
        self.say("[다른 건] 이몽룡 님 완성됐어요 확인 부탁드려요", sender=OTHER_DISPATCHER)
        acts = self.say("확인")
        self.assertEqual(kinds(acts), ["me"])
        self.assertIn("/전달 1", acts[0][1])
        self.assertEqual(kinds(self.w.force_deliver(1)), ["deliver"])

    def test_new_request_resets_other_spoke(self):
        self.say("잡담", sender=OTHER_DISPATCHER)
        self.run_request(self.w.rerequest(1))
        self.assertEqual(kinds(self.say("확인")), ["deliver"])

    def test_manager_reply_to_other_message_ignored(self):
        self.assertEqual(self.say("확인", reply_to=999), [])
        self.assertEqual(self.w.case(1)["status"], wf.WAIT_CONFIRM)

    def test_chitchat_ignored(self):
        self.assertEqual(self.say("잠시만요"), [])
        self.assertEqual(kinds(self.say("확인")), ["deliver"])  # 담당자 본인 잡담은 혼선으로 치지 않음

    def test_negated_plain_not_sent(self):
        self.assertEqual(self.say("아직 확인 못했어요"), [])

    def test_multiple_waiting_needs_pick(self):
        self.book(B, "이몽룡", "박")
        self.complete(B, "이몽룡")
        acts = self.say("확인")
        self.assertEqual(kinds(acts), ["me"])
        self.assertIn("/전달 1", acts[0][1])
        self.assertIn("/전달 2", acts[0][1])
        self.assertEqual(self.say("이몽룡 확인"), [("deliver", 2, B, "서울시 박주소 1")])
        self.assertEqual(self.say("#1 올려주세요"), [("deliver", 1, A, "서울시 박주소 1")])

    def test_force_deliver_only_when_waiting(self):
        self.say("확인")
        self.w.mark_done(1)
        self.assertNotIn("deliver", kinds(self.w.force_deliver(1)))

    def test_other_group_ignored(self):
        self.assertEqual(self.say("확인", chat=GROUP_KIM, sender=KIM), [])


class WordsTest(Base):
    def test_parse_words(self):
        self.assertEqual(wf.parse_words(" 완성, 완료 ,,다됐어요, 완료"), ["완성", "완료", "다됐어요"])

    def test_custom_completion_words(self):
        self.w.set_completion_words(["완료", "다됐어요"])
        self.book()
        self.assertEqual(self.w.on_completion(A, "홍길동", "완성했어요"), [])  # 이제 '완성'은 아님
        self.assertEqual(kinds(self.w.on_completion(A, "홍길동", "완료되면 연락드릴게요")), ["me"])  # 나에게만
        self.assertEqual(kinds(self.w.on_completion(A, "홍길동", "사장님 다 됐어요")), ["request", "me"])

    def test_custom_confirm_words(self):
        self.w.set_confirm_words(["ok", "고고"])
        self.book()
        _, req = self.complete()
        self.assertEqual(self.w.on_group_message(GROUP_PARK, None, PARK, "박", "확인"), [])
        self.assertEqual(kinds(self.w.on_group_message(GROUP_PARK, None, PARK, "박", "OK~")), ["deliver"])

    def test_other_completion_words(self):
        cases = {
            "완료": (["작업 완료!", "완료했습니다", "완료됐어요"], ["완료되면 말할게요", "완료 예정입니다", "내일 완료할게요"]),
            "마무리": (["마무리 했어요", "마무리됐습니다"], ["마무리되면 연락드릴게요", "마무리 중이에요", "마무리할게요"]),
            "끝": (["다 끝났어요", "끝!"], ["끝나면 말할게요", "끝날 것 같아요", "언제 끝나요"]),
            "끝났어요": (["다 끝났어요", "끝났어요!"], ["끝나면 말할게요"]),
            "다됐어요": (["다 됐어요", "사장님 다됐어요~"], ["다 되면 말할게요"]),
        }
        for word, (yes, no) in cases.items():
            for t in yes:
                with self.subTest(word=word, text=t):
                    self.assertTrue(wf.is_completion(t, [word]))
            for t in no:
                with self.subTest(word=word, text=t):
                    self.assertFalse(wf.is_completion(t, [word]))

    def test_reset_to_default(self):
        self.w.set_completion_words(["완료"])
        self.w.set_completion_words(None)
        self.assertEqual(self.w.completion_words(), ["완성"])
        self.assertEqual(self.w.confirm_words(), ["확인", "올려"])


class ManualModeTest(Base):
    """기본값: 완성 관련 말은 나에게만 알리고, 단톡방 요청은 /완성 으로 직접."""

    def setUp(self):
        super().setUp()
        self.w.set_auto_request(False)

    def test_default_is_manual(self):
        self.assertFalse(wf.Workflow(":memory:").auto_request())

    def test_completion_only_notifies_me(self):
        self.book()
        for text in ("완성했어요", "완성되면 말할게요", "사장님 완성!"):
            with self.subTest(text=text):
                acts = self.w.on_completion(A, "홍길동", text)
                self.assertEqual(kinds(acts), ["me"])
                self.assertIn("/완성 1", acts[0][1])
        self.assertIn("완성 알림으로 보입니다", self.w.on_completion(A, "홍길동", "완성했어요")[0][1])
        self.assertIn("완성 전 말일 수도", self.w.on_completion(A, "홍길동", "완성되면 말할게요")[0][1])
        self.assertEqual(self.w.open_case_for(A)["status"], wf.WAIT_COMPLETE)

    def test_unrelated_message_silent(self):
        self.book()
        self.assertEqual(self.w.on_completion(A, "홍길동", "안녕하세요 언제쯤 될까요"), [])

    def test_manual_request_then_delivery(self):
        self.book()
        self.w.on_completion(A, "홍길동", "완성했어요")
        acts = self.w.force_completion(1)
        self.assertEqual(kinds(acts), ["request", "me"])
        req = self.run_request(acts)
        self.assertEqual(kinds(self.w.on_group_message(GROUP_PARK, req, PARK, "박", "올려주세요")), ["deliver"])

    def test_no_booking_tells_how(self):
        acts = self.w.on_completion(A, "홍길동", "완성했어요")
        self.assertEqual(kinds(acts), ["me"])
        self.assertIn("/확정 홍길동", acts[0][1])
        self.assertIsNone(self.w.open_case_for(A))

    def test_quiet_after_request(self):
        self.book()
        self.run_request(self.w.force_completion(1))
        self.assertEqual(self.w.on_completion(A, "홍길동", "완성했어요~"), [])

    def test_switch_persists(self):
        path = os.path.join(tempfile.mkdtemp(), "s.db")
        w1 = wf.Workflow(path)
        w1.set_auto_request(True)
        w1.db.close()
        w2 = wf.Workflow(path)
        self.assertTrue(w2.auto_request())
        w2.db.close()


class StorageTest(unittest.TestCase):
    def test_persists_and_upgrades_old_db(self):
        import sqlite3
        path = os.path.join(tempfile.mkdtemp(), "a.db")
        old = sqlite3.connect(path)  # 이전 버전 스키마 (guide 컬럼 없음)
        old.execute("CREATE TABLE managers (name TEXT PRIMARY KEY, group_id INTEGER NOT NULL, "
                    "group_title TEXT NOT NULL, user_id INTEGER NOT NULL, user_label TEXT NOT NULL, "
                    "address TEXT NOT NULL)")
        old.execute("INSERT INTO managers VALUES ('박', -1001, '박 단톡', 501, '@park', '주소')")
        old.commit()
        old.close()

        w1 = wf.Workflow(path)
        self.assertEqual(w1.manager("박")["guide"], "")
        w1.confirm_booking(A, "홍", "박")
        acts = w1.force_completion(1)  # 기본은 직접 확인 모드 → /완성
        w1.set_request(1, find(acts, "request")[0][2], 100)
        w1.db.close()

        w2 = wf.Workflow(path)
        self.assertEqual(kinds(w2.on_group_reply(GROUP_PARK, 100, PARK, "박", "올려주세요")), ["deliver"])
        w2.db.close()


if __name__ == "__main__":
    unittest.main()
