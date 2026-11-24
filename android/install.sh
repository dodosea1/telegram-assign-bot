#!/data/data/com.termux/files/usr/bin/bash
# 텔레그램 배정 자동응답 - 안드로이드(Termux) 설치
#   설치:  bash <(curl -sL https://raw.githubusercontent.com/dodosea1/telegram-assign-bot/main/android/install.sh)
#   이미 설치돼 있으면 코드만 새로 받고 설정·로그인·담당자 기록은 그대로 둡니다.
set -e

REPO="dodosea1/telegram-assign-bot"
APP="$HOME/tele"
KEEP="config.json autoreply.session rules.json automation.db autoreply.log"

say()  { printf '\n\033[1;32m▶ %s\033[0m\n' "$1"; }
fail() { printf '\n\033[1;31m✖ %s\033[0m\n' "$1"; exit 1; }

[ -d /data/data/com.termux ] || fail "Termux 앱 안에서 실행해 주세요."

say "1/4 필요한 프로그램 설치 (1~5분, 글자가 많이 지나가도 정상입니다)"
export DEBIAN_FRONTEND=noninteractive
yes | pkg upgrade -y -o Dpkg::Options::=--force-confnew || true
pkg install -y -o Dpkg::Options::=--force-confnew python curl \
  || fail "프로그램 설치 실패. 와이파이를 확인하고 다시 실행해 주세요."

say "2/4 자동응답 프로그램 내려받기"
TMP="$(mktemp -d)"
curl -fsSL "https://github.com/$REPO/archive/refs/heads/main.tar.gz" | tar xz -C "$TMP" \
  || fail "내려받기 실패. 인터넷 연결을 확인해 주세요."
SRC="$(ls -d "$TMP"/*/ | head -1)"
mkdir -p "$APP"
for f in $KEEP; do [ -e "$APP/$f" ] && cp -p "$APP/$f" "$TMP/keep_$f"; done
cp -r "$SRC"/. "$APP"/
for f in $KEEP; do [ -e "$TMP/keep_$f" ] && cp -p "$TMP/keep_$f" "$APP/$f"; done
rm -rf "$TMP"

say "3/4 텔레그램 연결 부품 설치"
python -m pip install -q --disable-pip-version-check -r "$APP/requirements.txt" \
  || fail "부품 설치 실패. 다시 실행해 주세요."

say "4/4 명령어·홈 화면 버튼 만들기"
install -m 755 "$APP/android/tele" "$PREFIX/bin/tele"
mkdir -p "$HOME/.shortcuts"
for b in "$APP"/android/shortcuts/*; do install -m 755 "$b" "$HOME/.shortcuts/$(basename "$b")"; done

printf '\n\033[1;32m✅ 설치 완료\033[0m\n\n'
if [ -e "$APP/autoreply.session" ]; then
  echo "이미 로그인돼 있습니다. 홈 화면의 [자동응답 켜기] 버튼이나 'tele start' 로 켜세요."
else
  echo "다음 단계: 아래를 입력하고 엔터 → 텔레그램 로그인"
  printf '\n    \033[1mtele login\033[0m\n\n'
fi
