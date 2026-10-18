-- fin_q3m 뷰 교체 (2026-10-17 검토): 음수 매출(과거 재작성)을 빈칸으로. biz_check.sql 의 뷰 부분과 같다.
-- ▶ Supabase → SQL Editor 에서 1회 실행. 표 데이터는 건드리지 않는다(뷰 정의만 바뀜).
create or replace view public.fin_q3m with (security_invoker = on) as
with x as (
  select f.*,
         extract(month from f.fiscal_q)::int / 3 as qn,
         lag(f.fiscal_q)       over w as p_q,
         lag(f.fs_div)         over w as p_div,
         lag(f.revenue_ytd)    over w as p_rev,
         lag(f.op_income_ytd)  over w as p_op,
         lag(f.net_income_ytd) over w as p_net,
         lag(f.ocf_ytd)        over w as p_ocf,
         lag(f.capex_ytd)      over w as p_capex,
         lag(f.interest_ytd)   over w as p_int
  from public.fin_q f
  window w as (partition by f.code, f.bsns_year order by f.fiscal_q)
), y as (
  select x.*,
         (x.qn = 1) as first_q,
         (x.p_q = (date_trunc('quarter', x.fiscal_q::timestamp) - interval '1 day')::date
          and x.p_div = x.fs_div) as chain_ok
  from x
)
select code, fiscal_q, bsns_year, qn, reprt, fs_div, rcept_no, rcept_dt,
       -- 매출은 음수가 될 수 없다. 음수면 회사가 과거를 다시 작성한 것(중단사업 재분류 등 — 이번 보고서는
       -- 계속사업만, 직전 분기 누적은 옛 기준) → 빼면 틀린 값이라 비운다(2026-10-17 검토: 실측 16건, 최대 −7.4조)
       case when first_q then revenue_ytd    when chain_ok and revenue_ytd >= p_rev then revenue_ytd - p_rev end as revenue,
       case when first_q then op_income_ytd  when chain_ok then op_income_ytd  - p_op    end as op_income,
       case when first_q then net_income_ytd when chain_ok then net_income_ytd - p_net   end as net_income,
       case when first_q then ocf_ytd        when chain_ok then ocf_ytd        - p_ocf   end as ocf,
       case when first_q then capex_ytd      when chain_ok then capex_ytd      - p_capex end as capex,
       case when first_q then interest_ytd   when chain_ok then interest_ytd   - p_int   end as interest,
       assets, liabilities, equity, cur_assets, cur_liabilities, ppe, cash, receivables, inventory
from y;
