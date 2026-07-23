# plot.py — S(t) 심리점수 vs S&P500 겹쳐 그려 눈으로 검증
import os
from dotenv import load_dotenv
import pandas as pd
import matplotlib.pyplot as plt
from supabase import create_client

load_dotenv()
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
plt.rcParams["font.family"] = "Malgun Gothic"   # 한글 깨짐 방지 (윈도우 기본 폰트)
plt.rcParams["axes.unicode_minus"] = False


def fetch(table, sel, **eq):
    rows, step, start = [], 1000, 0
    while True:
        q = sb.table(table).select(sel)
        for k, v in eq.items():
            q = q.eq(k, v)
        r = q.order("dt").range(start, start + step - 1).execute().data
        rows += r
        if len(r) < step:
            break
        start += step
    return pd.DataFrame(rows)


sent = fetch("sentiment_daily", "dt,s_score", market="US")
px = fetch("indicator_raw", "dt,value", market="US", code="us_index")
sent["dt"] = pd.to_datetime(sent["dt"])
px["dt"] = pd.to_datetime(px["dt"])
m = sent.merge(px.rename(columns={"value": "spx"}), on="dt").sort_values("dt")

fig, ax1 = plt.subplots(figsize=(13, 5))
ax1.plot(m["dt"], m["spx"], color="#222", lw=1, label="S&P500")
ax1.set_ylabel("S&P500")
ax2 = ax1.twinx()
ax2.plot(m["dt"], m["s_score"], color="#d97706", lw=1.1, alpha=.85, label="S(t) 심리")
ax2.axhline(80, color="#c0392b", ls="--", lw=.6)   # 극단탐욕 경계
ax2.axhline(20, color="#2471a3", ls="--", lw=.6)   # 극단공포 경계
ax2.set_ylabel("S(t) 심리점수 (0~100)")
ax2.set_ylim(0, 100)
ax1.set_title("S&P500  vs  S(t) 심리점수 — 공포(아래)·탐욕(위)")
fig.tight_layout()
fig.savefig("sentiment.png", dpi=110)
print("저장 완료: sentiment.png")
