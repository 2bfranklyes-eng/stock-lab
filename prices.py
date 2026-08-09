# prices.py — indicator_raw의 시장 지수들을 공개용 price_daily로 복사
#   비교 탭에서 웹(anon)이 실제 주가를 지수와 겹쳐 그리려면 공개 read 테이블이 필요.
#   시장당 여러 지수를 싣기 때문에 price_daily의 PK는 (market, dt, code) — sql/price_daily_add_code.sql 참고.
import os
import sys
from dotenv import load_dotenv
from supabase import create_client

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

load_dotenv()
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
# 시장별로 공개할 지수들. 첫 번째가 대표 지수(다른 계산·백테스트가 쓰는 기준).
#   경기 순환변동치(월별)도 여기 실어 공개한다 — 프론트의 「경기 국면」 카드가 읽는다.
#   지수는 아니지만 (market, dt, code, close) 구조가 그대로 맞고, 이 표는 market 단위로
#   전량 교체되므로 여기 등록해 두지 않으면 다음 크론에서 지워진다.
CODES = {"US": ["us_index", "us_nasdaq", "us_dow"],   # S&P500 / 나스닥 / 다우
         "KR": ["kr_index", "kr_kosdaq",              # 코스피 / 코스닥
                "kr_coincident", "kr_leading",        # 동행·선행지수 순환변동치
                "kr_index_m"]}                        # 월말 코스피 장기(1996~)


def fetch(market, code):
    rows, start = [], 0
    while True:
        r = sb.table("indicator_raw").select("dt,value") \
              .eq("market", market).eq("code", code) \
              .order("dt").range(start, start + 999).execute().data
        rows += r
        if len(r) < 1000:
            break
        start += 1000
    return rows


def run(market):
    recs = []
    for code in CODES[market]:
        got = fetch(market, code)
        recs += [{"market": market, "dt": x["dt"], "code": code, "close": x["value"]} for x in got]
        print(f"  [{market}] {code}: {len(got)}행")
    sb.table("price_daily").delete().eq("market", market).execute()   # 전량 교체
    for i in range(0, len(recs), 1000):
        sb.table("price_daily").insert(recs[i:i + 1000]).execute()
    print(f"[{market}] price_daily 적재 완료: 총 {len(recs)}행")


if __name__ == "__main__":
    for m in (sys.argv[1:] or ["US", "KR"]):
        run(m.upper())
