"""로컬 콜백 서버 진단 — "127.0.0.1 이 안 된다" 문제의 실제 원인 확인.

로이 PC 에서 직접 실행:
    python scripts\\diag_localhost.py

확인 항목:
  1) 127.0.0.1 (IPv4) 로 리스닝 가능한가
  2) ::1 (IPv6) 로 리스닝 가능한가
  3) localhost 가 어떤 주소로 해석되는가  ← IPv6 우선순위 문제
  4) 방화벽이 막고 있는가
  5) 실제로 브라우저가 붙을 수 있는가 (IPv4 로 접속 테스트)
"""
from __future__ import annotations

import socket
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

OK = "[OK  ]"
NG = "[FAIL]"


class _H(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"PONG")

    def log_message(self, *a):  # noqa: D102
        pass


def test_family(family: int, label: str, host: str) -> tuple[int, str]:
    """지정 주소_family 로 리스닝하고, 같은 주소로 접속해 본다."""
    try:
        srv = HTTPServer((host, 0), _H)
        srv.address_family = family
        port = srv.server_port
    except OSError as e:
        return 0, f"리스닝 실패 ({e.strerror or e})"
    threading.Thread(target=srv.handle_request, daemon=True).start()
    try:
        url = f"http://[{host}]:{port}/ping" if ":" in host else f"http://{host}:{port}/ping"
        r = urllib.request.urlopen(url, timeout=6)
        srv.server_close()
        return r.status, f"port={port} 응답={r.read().decode()}"
    except Exception as e:  # noqa: BLE001
        try:
            srv.server_close()
        except Exception:  # noqa: BLE001
            pass
        return 0, f"접속 실패 ({type(e).__name__}: {e})"


def main() -> int:
    print("=" * 66)
    print(" 로컬 콜백 서버 진단")
    print("=" * 66)

    # 1) localhost 해석 결과 — 이게 핵심
    print("\n[1] localhost 가 어떤 주소로 해석되는가")
    try:
        infos = socket.getaddrinfo("localhost", 0, type=socket.SOCK_STREAM)
        addrs = []
        for fam, typ, proto, canon, sa in infos:
            tag = {socket.AF_INET: "IPv4", socket.AF_INET6: "IPv6"}.get(fam, str(fam))
            entry = f"{sa[0]} ({tag})"
            if entry not in addrs:
                addrs.append(entry)
        for a in addrs:
            print(f"     - {a}")
        ipv6_first = addrs and "IPv6" in addrs[0]
        if ipv6_first:
            print(f"  {NG} IPv6 가 먼저 나옵니다 → 브라우저도 IPv6(localhost)를 먼저 시도")
            print("       서버가 IPv4(127.0.0.1) 에만 붙어 있으면 '거부됨' 으로 보입니다.")
            print("       → 해결: redirect_uri 를 127.0.0.1 로 명시 (코드가 이미 doing)")
        else:
            print(f"  {OK} IPv4 우선 — 정상")
    except Exception as e:  # noqa: BLE001
        print(f"  {NG} 해석 실패: {e}")

    # 2) IPv4
    print("\n[2] IPv4 (127.0.0.1) 리스닝+접속")
    st, msg = test_family(socket.AF_INET, "IPv4", "127.0.0.1")
    print(f"  {OK if st else NG} {msg}")

    # 3) IPv6
    print("\n[3] IPv6 (::1) 리스닝+접속")
    st6, msg6 = test_family(socket.AF_INET6, "IPv6", "::1")
    print(f"  {OK if st6 else NG} {msg6}")

    # 4) 0.0.0.0 (모든 인터페이스) — 방화벽 영향 확인용
    print("\n[4] 0.0.0.0 (전체 인터페이스) 리스닝+127.0.0.1 접속")
    try:
        srv = HTTPServer(("0.0.0.0", 0), _H)
        port = srv.server_port
        threading.Thread(target=srv.handle_request, daemon=True).start()
        r = urllib.request.urlopen(f"http://127.0.0.1:{port}/ping", timeout=6)
        srv.server_close()
        print(f"  {OK} port={port} 응답={r.read().decode()}")
    except Exception as e:  # noqa: BLE001
        print(f"  {NG} {type(e).__name__}: {e}")

    # 5) 프록시 환경변수 — 이게 있으면 로컬 주소까지 프록시를 타게 된다
    print("\n[5] 프록시 환경변수 (로컬 주소도 프록시 타면 실패)")
    import os
    found = False
    for k in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy",
              "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy"):
        v = os.environ.get(k)
        if v:
            found = True
            flag = NG if k.lower() in ("http_proxy", "https_proxy", "all_proxy") else OK
            print(f"  {flag} {k} = {v[:70]}")
    if not found:
        print(f"  {OK} 프록시 환경변수 없음")

    print("\n" + "=" * 66)
    print(" 진단 요약")
    print("=" * 66)
    if st:
        print(" 127.0.0.1 은 정상입니다.")
        print(" 브라우저에서 '거부됨' 이 나오면:")
        print("   1) 인증 창(검은 콘솔)이 아직 열려 있는지 확인 — 닫으면 서버가 죽습니다")
        print("   2) 30 분이 지나지 않았는지 확인")
        print("   3) Chrome 주소창에 127.0.0.1:포트 를 직접 쳐서 'PONG' 이 오는지 확인")
    else:
        print(" ❌ 127.0.0.1 리스닝/접속 자체가 안 됩니다.")
        print("    → 방화벽 또는 보안 소프트웨어가 로컬 소켓을 차단했을 가능성")
        print("    → Windows 보안성 -> 방화벽 -> 허용 앱 에 python.exe 추가")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
