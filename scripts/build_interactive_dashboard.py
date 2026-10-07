#!/usr/bin/env python3
"""Build a self-contained Plotly dashboard from Futu screen metrics and saved daily-bar JSON."""
import argparse
import csv
import glob
import json
import os
import sys

NUMERIC = [
    "close", "bars", "return_63_pct", "adr20_pct", "turnover50",
    "above_sma200_pct", "best_base_pct", "best_base_days", "prior20_low",
    "prior20_high", "trigger_gap_pct", "ema10", "ema10_distance_pct",
    "ema20", "ema20_distance_pct", "ema50", "ema50_distance_pct",
]
LABELS = {
    "return_63_pct": "63日報酬 (%)", "close": "收盤價 (USD)",
    "adr20_pct": "ADR20 (%)", "turnover50": "50日均成交金額 (百萬美元)",
    "above_sma200_pct": "高於SMA200 (%)", "best_base_pct": "最窄整固區間 (%)",
    "trigger_gap_pct": "距20日高點觸發 (%)", "ema10_distance_pct": "距EMA10 (%)",
    "ema20_distance_pct": "距EMA20 (%)", "ema50_distance_pct": "距EMA50 (%)",
    "bars": "K線根數",
}
RULES = ["63日報酬≥20%", "股價>$5", "50日均成交額>$5m", "ADR20>3.5%",
         "高於SMA200≤60%", "整固幅度<8%", "收盤≥前20日低點"]
EXCLUDED_CLASS_TOKENS = ("ETF", "PREFERRED", "PREFERENCE", "PREF", "PFD", "優先股", "优先股", "CDI", "CEF", "CLOSED-END", "WARRANT", "RIGHT", "UNIT", "FUND")
ALLOWED_CLASS_TOKENS = ("COMMON", "ORDINARY", "普通股", "ADR", "ADS")


def as_float(value):
    try:
        return float(value) if value not in (None, "") else None
    except (ValueError, TypeError):
        return None


def as_bool(value):
    return str(value).strip().lower() in ("true", "1", "yes", "y")


def load_metrics(path, common_adr_only=False):
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError("metrics CSV contains no rows")
    kept, excluded = [], []
    for row in rows:
        row["code"] = row.get("code", "").strip()
        row["name"] = row.get("name", "").strip()
        if not row["code"] or not row["name"]:
            raise ValueError("metrics CSV must include non-empty 'code' and 'name' columns")
        for key in NUMERIC:
            if key in row:
                row[key] = as_float(row[key])
        for key in ("above_prior20_low", "breakout_close", "pass_core"):
            row[key] = as_bool(row.get(key, False))
        instrument = (row.get("Futu_security_type") or row.get("instrument_type") or "").upper()
        security_class = (row.get("US_listing_class") or row.get("security_class") or "").upper()
        if common_adr_only:
            # A stock_type=STOCK response is not enough to identify preferreds/CDIs/funds.
            # Require both a non-ETF instrument type and a positive class label.
            if instrument == "ETF" or any(t in security_class for t in EXCLUDED_CLASS_TOKENS):
                excluded.append((row["code"], row["name"], security_class or instrument or "unclassified"))
                continue
            if not any(t in security_class for t in ALLOWED_CLASS_TOKENS):
                excluded.append((row["code"], row["name"], security_class or "unclassified"))
                continue
        ds = [row.get(k) for k in ("ema10_distance_pct", "ema20_distance_pct", "ema50_distance_pct")]
        row["ema_mean_distance_pct"] = sum(ds) / 3 if all(v is not None for v in ds) else None
        row["failures"] = row.get("failures", "")
        row["rules"] = [
            row.get("return_63_pct") is not None and row["return_63_pct"] >= 20,
            row.get("close") is not None and row["close"] > 5,
            row.get("turnover50") is not None and row["turnover50"] > 5_000_000,
            row.get("adr20_pct") is not None and row["adr20_pct"] > 3.5,
            row.get("above_sma200_pct") is not None and row["above_sma200_pct"] <= 60,
            row.get("best_base_pct") is not None and row["best_base_pct"] < 8,
            row.get("above_prior20_low", False),
        ]
        kept.append(row)
    if common_adr_only and not kept:
        raise ValueError("No rows remained after common-stock/ADR classification")
    return kept, excluded


def load_bars(rows, patterns):
    by_name = {}
    for pattern in patterns:
        for path in glob.glob(os.path.expanduser(pattern)):
            try:
                payload = json.load(open(path, encoding="utf-8"))
                bars = payload.get("data", {}).get("kline_list", [])
                if not bars:
                    continue
                bars = sorted(bars, key=lambda b: b["date"])
                name = bars[-1].get("name") or bars[-1].get("sc_name")
                if name and (name not in by_name or len(bars) > len(by_name[name])):
                    by_name[name] = bars
            except (OSError, ValueError, KeyError, TypeError) as exc:
                print(f"Warning: skipped {path}: {exc}", file=sys.stderr)
    out, missing = {}, []
    for row in rows:
        bars = by_name.get(row["name"])
        if not bars:
            missing.append((row["code"], row["name"]))
            continue
        out[row["code"]] = [{
            "date": str(b["date"]), "open": float(b["open"]),
            "high": float(b["high"]), "low": float(b["low"]),
            "close": float(b["close"]),
        } for b in bars]
    if missing:
        names = ", ".join(f"{c} {n}" for c, n in missing[:10])
        raise ValueError(f"Missing saved daily bars for {len(missing)} included symbols: {names}")
    return out


def build_html(rows, bars, title, as_of):
    try:
        import plotly.offline as po
        plotly_js = po.get_plotlyjs()
    except ImportError as exc:
        raise RuntimeError("Install Plotly to build the standalone dashboard: pip install plotly") from exc
    data_js = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    bars_js = json.dumps(bars, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    labels_js, rules_js = json.dumps(LABELS, ensure_ascii=False), json.dumps(RULES, ensure_ascii=False)
    body = r'''<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>__TITLE__</title><script>__PLOTLY__</script><style>
:root{--bg:#f3f6fb;--ink:#152238;--muted:#64748b;--line:#e5ebf3}*{box-sizing:border-box}body{margin:0;background:var(--bg);font-family:Inter,"Noto Sans CJK TC","Microsoft JhengHei",system-ui,sans-serif;color:var(--ink)}header{padding:26px max(22px,calc((100vw - 1400px)/2));background:linear-gradient(120deg,#0f2547,#1b4b75);color:white}h1{margin:0 0 7px;font-size:24px}header p{margin:0;color:#d5e4f5;font-size:13px}.wrap{max-width:1400px;margin:auto;padding:20px}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px}.card,.panel{background:white;border:1px solid var(--line);border-radius:14px;box-shadow:0 3px 12px #1a365408}.card{padding:16px}.card .k{font-size:12px;color:var(--muted)}.card .v{font-size:24px;font-weight:750;margin-top:5px}.card .sub{font-size:11px;color:#8290a3;margin-top:3px}.panel{padding:16px;margin-bottom:16px}.panel h2{font-size:16px;margin:0 0 4px}.hint{font-size:12px;color:var(--muted);margin:0 0 10px}.grid{display:grid;grid-template-columns:1.15fr .85fr;gap:15px}.controls{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:10px 0}.controls label{font-size:12px;color:var(--muted)}select,input{border:1px solid #ccd6e4;border-radius:8px;padding:8px 10px;background:white;color:var(--ink);font-size:13px}.toggle{display:flex;gap:7px;align-items:center;font-size:12px;color:var(--muted)}#scatter{height:460px}#heat{height:680px}#bars{height:400px}#breakoutChart{height:590px}.tablewrap{max-height:610px;overflow:auto;border:1px solid var(--line);border-radius:9px}table{width:100%;border-collapse:collapse;white-space:nowrap;font-size:12px}th{position:sticky;top:0;background:#eff4fa;z-index:1;text-align:right;padding:9px;color:#506176;cursor:pointer}th:first-child,td:first-child{text-align:left}td{padding:8px;border-top:1px solid #edf1f6;text-align:right}.top-ema-row td{background:#f1ecff!important}.tag{padding:3px 7px;border-radius:99px;font-weight:650}.yes{background:#e0f5ec;color:#08764c}.no{background:#f1f3f6;color:#6b7280}.foot{font-size:11px;color:#697789;line-height:1.6;padding:0 4px 18px}@media(max-width:900px){.grid{grid-template-columns:1fr}.cards{grid-template-columns:repeat(2,1fr)}.wrap{padding:12px}#heat{height:630px}}
</style></head><body><header><h1>__TITLE__</h1><p>__N__ 檔股票｜資料截至 __ASOF__｜可縮放、懸停查值及切換標的</p></header><main class="wrap"><section class="cards" id="cards"></section>
<section class="panel"><h2>距 EMA10／20／50 最近前五名</h2><p class="hint">依三條 EMA 的絕對距離百分比等權平均排序；紫色標示前五名。均線貼近度不代表趨勢方向或條件通過。</p><div id="emaTop5" class="tablewrap"></div></section>
<section class="panel"><h2>突破／回踩技術圖</h2><p class="hint">切換股票查看日 K、EMA10／20／50、前 20 日高點突破觸發線與前 20 日低點回踩觀察線。均線可能提供回踩參考，但不保證支撐；突破需另外確認成交量與後續延續。</p><div class="controls"><label>股票 <select id="chartSel"></select></label><label class="toggle"><input type="checkbox" id="chartAll">顯示完整歷史</label></div><div id="breakoutChart"></div></section>
<section class="panel"><h2>指標散點比較</h2><p class="hint">切換 X/Y 指標；綠色為核心條件通過，橙色為價格收盤高於前 20 日高點但未通過全部核心條件，灰色為其他；紫色外框為 EMA 前五名。</p><div class="controls"><label>X 軸 <select id="xsel"></select></label><label>Y 軸 <select id="ysel"></select></label><label class="toggle"><input type="checkbox" id="passonly">只看核心通過</label></div><div id="scatter"></div></section>
<section class="grid"><div class="panel"><h2>各條件通過矩陣</h2><p class="hint">綠色為通過；紅色為未通過或資料不足。</p><div id="heat"></div></div><div class="panel"><h2>依單一指標排序</h2><div class="controls"><label>排序指標 <select id="rankSel"></select></label></div><div id="bars"></div></div></section>
<section class="panel"><h2>股票明細</h2><div class="controls"><input id="search" placeholder="搜尋股票名稱或代號…"><label class="toggle"><input type="checkbox" id="tablepass">只看核心通過</label></div><div class="tablewrap"><table id="tbl"><thead></thead><tbody></tbody></table></div></section>
<div class="foot"><b>口徑：</b>ADR20 是平均 (high-low)/close，不是 Wilder ATR。整固幅度為尾端 5–39 根日 K 中最窄高低區間。突破觸發價為前 20 個已完成交易日最高價。依本次使用者條件計算核心 pass/fail；公司類別以 Futu basicinfo + 明確股票類型核驗。部分名稱或 ADR/OTC 股須以原始商品資料核對。圖表及目標線僅為研究視覺化，不構成投資建議。<br><b>資料覆蓋：</b>只包含此次實際取得並驗證的候選股票，不應宣稱為全市場完整掃描。</div></main><script>
const D=__DATA__;const B=__BARS__;const L=__LABELS__;const R=__RULES__;const n=D.length,passes=D.filter(d=>d.pass_core).length,breakouts=D.filter(d=>d.breakout_close).length;const top5=[...D].filter(d=>d.ema_mean_distance_pct!=null).sort((a,b)=>a.ema_mean_distance_pct-b.ema_mean_distance_pct).slice(0,5),topNames=new Set(top5.map(d=>d.name));
document.getElementById('cards').innerHTML=[['篩選股票',n,'按指定證券類別過濾後'],['核心條件通過',passes,'所有已計算核心條件同時成立'],['價格突破',breakouts,'收盤高於前20日高點，不等於確認'],['資料截點','__ASOF__','逐股日期見明細']].map(x=>`<div class="card"><div class="k">${x[0]}</div><div class="v">${x[1]}</div><div class="sub">${x[2]}</div></div>`).join('');
function format(k,v){if(v==null||v==='')return '無資料';if(typeof v==='string')return v;if(k==='turnover50')return '$'+(v/1e6).toFixed(1)+'m';if(k==='close'||k.startsWith('ema'))return '$'+Number(v).toFixed(2);if(k==='best_base_days'||k==='bars')return Number(v).toFixed(0);return Number(v).toFixed(2)+'%'}function axisVal(d,k){return k==='turnover50'?d[k]/1e6:d[k]}function fill(id,keys,def){let e=document.getElementById(id);e.innerHTML=keys.map(k=>`<option value="${k}">${L[k]||k}</option>`).join('');e.value=def}const metrics=['return_63_pct','adr20_pct','turnover50','above_sma200_pct','best_base_pct','trigger_gap_pct','ema10_distance_pct','ema20_distance_pct','ema50_distance_pct','close'];fill('xsel',metrics,'best_base_pct');fill('ysel',metrics,'adr20_pct');fill('rankSel',metrics,'return_63_pct');
function drawTop(){document.getElementById('emaTop5').innerHTML='<table><thead><tr><th>排名</th><th>股票</th><th>EMA10 距離</th><th>EMA20 距離</th><th>EMA50 距離</th><th>平均</th></tr></thead><tbody>'+top5.map((d,i)=>`<tr class="top-ema-row"><td>#${i+1}</td><td><b>${d.name} (${d.code})</b></td><td>${d.ema10_distance_pct.toFixed(2)}%</td><td>${d.ema20_distance_pct.toFixed(2)}%</td><td>${d.ema50_distance_pct.toFixed(2)}%</td><td><b>${d.ema_mean_distance_pct.toFixed(2)}%</b></td></tr>`).join('')+'</tbody></table>'}
function ema(a,p){let o=[a[0]],k=2/(p+1);for(let i=1;i<a.length;i++)o.push(a[i]*k+o[i-1]*(1-k));return o}function drawBreakout(){let code=chartSel.value,all=chartAll.checked,full=B[code]||[],start=all?0:Math.max(0,full.length-70),a=full.slice(start),dates=a.map(x=>String(x.date).slice(0,4)+'-'+String(x.date).slice(4,6)+'-'+String(x.date).slice(6)),close=full.map(x=>x.close),trigger=Math.max(...full.slice(-21,-1).map(x=>x.high)),low20=Math.min(...full.slice(-21,-1).map(x=>x.low)),row=D.find(x=>x.code===code),tr=[{x:dates,open:a.map(x=>x.open),high:a.map(x=>x.high),low:a.map(x=>x.low),close:a.map(x=>x.close),type:'candlestick',name:row.name+' ('+code+')',increasing:{line:{color:'#15966b'}},decreasing:{line:{color:'#d9534f'}}}];for(let p of [10,20,50])tr.push({x:dates,y:ema(close,p).slice(start),type:'scatter',mode:'lines',name:'EMA'+p,line:{width:1.5}});Plotly.react('breakoutChart',tr,{title:{text:row.name+' ('+code+')｜收盤 $'+close.at(-1).toFixed(2)+'｜20日觸發 $'+trigger.toFixed(2),font:{size:14}},margin:{l:70,r:20,t:50,b:55},paper_bgcolor:'white',plot_bgcolor:'white',xaxis:{rangeslider:{visible:false},gridcolor:'#edf1f6'},yaxis:{title:'USD',gridcolor:'#edf1f6'},shapes:[{type:'line',x0:dates[0],x1:dates.at(-1),y0:trigger,y1:trigger,line:{color:'#202020',dash:'dash',width:1.5}},{type:'line',x0:dates[0],x1:dates.at(-1),y0:low20,y1:low20,line:{color:'#d9534f',dash:'dot',width:1.2}}],annotations:[{x:dates.at(-1),y:trigger,text:'前20日高點／突破觸發 $'+trigger.toFixed(2),showarrow:false,xanchor:'right',yshift:10,font:{size:10}},{x:dates.at(-1),y:low20,text:'前20日低點／回踩觀察 $'+low20.toFixed(2),showarrow:false,xanchor:'right',yshift:-10,font:{size:10}}],font:{family:'Arial,sans-serif'}},{responsive:true,displaylogo:false})}
function drawScatter(){let xk=xsel.value,yk=ysel.value,a=D.filter(d=>!passonly.checked||d.pass_core),colors=a.map(d=>d.pass_core?'#14966b':d.breakout_close?'#e69a17':'#8794a7');let tr={x:a.map(d=>axisVal(d,xk)),y:a.map(d=>axisVal(d,yk)),text:a.map(d=>d.name+' ('+d.code+')'),mode:'markers',type:'scatter',marker:{size:a.map(d=>10+(topNames.has(d.name)?5:0)),color:colors,opacity:.88,line:{color:a.map(d=>topNames.has(d.name)?'#7c3aed':'white'),width:a.map(d=>topNames.has(d.name)?3:1)}},customdata:a.map(d=>[d.close,d.return_63_pct,d.adr20_pct,d.turnover50,d.best_base_pct,d.trigger_gap_pct]),hovertemplate:'<b>%{text}</b><br>'+L[xk]+': %{x:.2f}<br>'+L[yk]+': %{y:.2f}<br>收盤: $%{customdata[0]:.2f}<br>63日報酬: %{customdata[1]:.1f}%<br>ADR20: %{customdata[2]:.2f}%<br>50日成交額: $%{customdata[3]:,.0f}<br>整固幅度: %{customdata[4]:.2f}%<br>距觸發: %{customdata[5]:.2f}%<extra></extra>'};Plotly.react('scatter',[tr],{margin:{l:70,r:20,t:10,b:65},paper_bgcolor:'white',plot_bgcolor:'white',xaxis:{title:L[xk],gridcolor:'#edf1f6'},yaxis:{title:L[yk],gridcolor:'#edf1f6'}},{responsive:true,displaylogo:false})}
function drawHeat(){let a=[...D].sort((x,y)=>Number(y.pass_core)-Number(x.pass_core)||(x.trigger_gap_pct??999)-(y.trigger_gap_pct??999)),z=a.map(d=>d.rules.map(v=>v?1:0));Plotly.react('heat',[{z,x:R,y:a.map(d=>d.name+' ('+d.code+')'),type:'heatmap',colorscale:[[0,'#f7d8d8'],[.499,'#f7d8d8'],[.5,'#d9f2e6'],[1,'#d9f2e6']],zmin:0,zmax:1,showscale:false,hovertemplate:'%{y}<br>%{x}: %{z}<extra></extra>',xgap:2,ygap:1}],{margin:{l:190,r:8,t:5,b:110},xaxis:{tickangle:-30,tickfont:{size:10}},yaxis:{autorange:'reversed',tickfont:{size:9}},paper_bgcolor:'white',plot_bgcolor:'white'},{responsive:true,displaylogo:false})}
function drawBars(){let k=rankSel.value,a=D.filter(d=>d[k]!=null).sort((x,y)=>axisVal(y,k)-axisVal(x,k)).slice(0,25).reverse();Plotly.react('bars',[{x:a.map(d=>axisVal(d,k)),y:a.map(d=>d.name+' ('+d.code+')'),type:'bar',orientation:'h',marker:{color:a.map(d=>d.pass_core?'#14966b':d.breakout_close?'#e69a17':'#9aa6b5')},hovertemplate:'%{y}<br>'+L[k]+': %{x:.2f}<extra></extra>'}],{margin:{l:185,r:15,t:5,b:55},xaxis:{title:L[k],gridcolor:'#edf1f6'},yaxis:{tickfont:{size:9}},paper_bgcolor:'white',plot_bgcolor:'white'},{responsive:true,displaylogo:false})}
const cols=[['code','代號'],['name','股票全名'],['US_listing_class','類別'],['date','資料日'],['close','收盤'],['return_63_pct','63日報酬'],['adr20_pct','ADR20'],['turnover50','50日成交額'],['above_sma200_pct','高於SMA200'],['best_base_pct','整固幅度'],['trigger_gap_pct','距觸發'],['ema_mean_distance_pct','三線平均距離'],['pass_core','核心通過'],['failures','未通過項目']];let sort={key:'pass_core',dir:-1};function renderTable(){let q=search.value.toLowerCase(),a=D.filter(d=>(!tablepass.checked||d.pass_core)&&(d.name+' '+d.code).toLowerCase().includes(q)).sort((x,y)=>{let u=x[sort.key],v=y[sort.key];if(u==null)return 1;if(v==null)return -1;return (typeof u==='string'?String(u).localeCompare(String(v)):Number(u)-Number(v))*sort.dir});tbl.querySelector('thead').innerHTML='<tr>'+cols.map(([k,t])=>`<th data-k="${k}">${t} ↕</th>`).join('')+'</tr>';tbl.querySelector('tbody').innerHTML=a.map(d=>'<tr class="'+(topNames.has(d.name)?'top-ema-row':'')+'">'+cols.map(([k])=>{let v=d[k];if(k==='pass_core')return `<td><span class="tag ${v?'yes':'no'}">${v?'通過':'未通過'}</span></td>`;if(k==='date')return `<td>${String(v).slice(0,4)}-${String(v).slice(4,6)}-${String(v).slice(6)}</td>`;if(k==='failures')return `<td>${Array.isArray(v)?v.join('、'):v||''}</td>`;return `<td>${format(k,v)}</td>`}).join('')+'</tr>').join('');tbl.querySelectorAll('th').forEach(th=>th.onclick=()=>{if(sort.key===th.dataset.k)sort.dir*=-1;else{sort.key=th.dataset.k;sort.dir=1}renderTable()})}
chartSel.innerHTML=D.map(d=>`<option value="${d.code}">${d.name} (${d.code})</option>`).join('');chartSel.value=D.find(d=>d.pass_core)?.code||D[0].code;chartSel.onchange=drawBreakout;chartAll.onchange=drawBreakout;xsel.onchange=ysel.onchange=passonly.onchange=drawScatter;rankSel.onchange=drawBars;search.oninput=tablepass.onchange=renderTable;drawTop();drawBreakout();drawScatter();drawHeat();drawBars();renderTable();
</script></body></html>'''
    for key, value in {
        "__TITLE__": title, "__N__": str(len(rows)), "__ASOF__": as_of,
        "__PLOTLY__": plotly_js, "__DATA__": data_js, "__BARS__": bars_js,
        "__LABELS__": labels_js, "__RULES__": rules_js,
    }.items():
        body = body.replace(key, value)
    return body


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--metrics", required=True, help="CSV from analyze_futu_bars.py; include code/name and optionally security-class columns")
    ap.add_argument("--bars-glob", action="append", required=True, help="Glob for saved quote_history_kline JSON files; may be repeated")
    ap.add_argument("--output", required=True, help="Output self-contained HTML path")
    ap.add_argument("--title", default="Futu 突破篩選｜互動式股票比較")
    ap.add_argument("--as-of", default="最新資料日，逐股見明細")
    ap.add_argument("--common-adr-only", action="store_true", help="Keep only positively labelled common/ordinary/ADR/ADS rows; drop ETFs and known fund/preferred/CDI/derivative classes")
    args = ap.parse_args()
    rows, excluded = load_metrics(args.metrics, args.common_adr_only)
    bars = load_bars(rows, args.bars_glob)
    document = build_html(rows, bars, args.title, args.as_of)
    out = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(document)
    print(f"HTML: {out}\nIncluded: {len(rows)} symbols\nExcluded by class filter: {len(excluded)}\nEmbedded daily-bar series: {len(bars)}")
    if excluded:
        print("Excluded:")
        for code, name, cls in excluded:
            print(f"  {code} | {name} | {cls}")

if __name__ == "__main__":
    main()
