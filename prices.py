# prices.py — indicator_raw의 대표 지수(us_index/kr_index)를 공개용 price_daily로 복사
#   비교 탭에서 웹(anon)이 실제 주가를 지수와 겹쳐 그리려면 공개 read 테이블이 필요.
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
CODE = {"US": "us_index", "KR": "kr_index"}   # 대표 지수(S&P500 / 코스피)


def run(market):
    rows, start = [], 0
    while True:
        r = sb.table("indicator_raw").select("dt,value") \
              .eq("market", market).eq("code", CODE[market]) \
              .order("dt").range(start, start + 999).execute().data
        rows += r
        if len(r) < 1000:
            break
        start += 1000
    recs = [{"market": market, "dt": x["dt"], "close": x["value"]} for x in rows]
    sb.table("price_daily").delete().eq("market", market).execute()   # 전량 교체
    for i in range(0, len(recs), 1000):
        sb.table("price_daily").insert(recs[i:i + 1000]).execute()
    print(f"[{market}] price_daily 적재 완료: {len(recs)}행")


if __name__ == "__main__":
    for m in (sys.argv[1:] or ["US", "KR"]):
        run(m.upper())
