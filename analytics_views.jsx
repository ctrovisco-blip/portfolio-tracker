// ─── ANALYTICS VIEWS: Desempenho · Fiscal · Dividendos ─────────────────────
// Injetado em portfolio-template.html por build_html.py (/*__ANALYTICS_VIEWS__*/).
// Dados: const ANALYTICS (data/analytics.json, gerado por build_analytics.py).

const AV = {
  bg:"#131722", panel:"#1a1f2e", panel2:"#1e2438", border:"#2a3042",
  text:"#c8ccd4", strong:"#e0e3eb", muted:"#6b7280", green:"#089981", red:"#ef5350",
  blue:"#5b8af5", amber:"#d9a441", purple:"#9d8fca",
};
const BENCH_COLORS = { spy:"#d9a441", qqq:"#9d8fca", world:"#3ba899" };

const avNum = (v, d=2) => v==null || isNaN(v) ? "—" :
  Number(v).toLocaleString("pt-PT",{minimumFractionDigits:d,maximumFractionDigits:d});
const avEur = (v, d=2) => v==null ? "—" : avNum(v,d) + " €";
const avSEur = (v, d=2) => v==null ? "—" : (v>0?"+":"") + avNum(v,d) + " €";
const avPct = (v, d=2, sign=true) => v==null ? "—" : (sign && v>0?"+":"") + avNum(v,d) + "%";
const avCol = v => v==null ? AV.text : v>0 ? AV.green : v<0 ? AV.red : AV.text;
const avDate = s => s ? s.split("-").reverse().join("/") : "—";

function AvCard({ title, sub, children, style, right }) {
  return (
    <div style={{background:AV.panel,border:`1px solid ${AV.border}`,borderRadius:"8px",
      padding:"12px 14px",minWidth:0,...style}}>
      {(title||right) && <div style={{display:"flex",alignItems:"baseline",gap:"8px",marginBottom:"10px"}}>
        <div style={{fontSize:"11px",fontWeight:"600",color:AV.strong}}>{title}</div>
        {sub && <div style={{fontSize:"10px",color:AV.muted}}>{sub}</div>}
        <div style={{flex:1}}/>{right}
      </div>}
      {children}
    </div>
  );
}

function AvKpi({ label, value, sub, color, hint }) {
  return (
    <div title={hint} style={{background:AV.panel,border:`1px solid ${AV.border}`,borderRadius:"8px",
      padding:"10px 12px",minWidth:0}}>
      <div style={{fontSize:"9px",color:AV.muted,letterSpacing:"0.8px",textTransform:"uppercase",marginBottom:"4px"}}>{label}</div>
      <div style={{fontSize:"17px",fontWeight:"700",color:color||AV.strong,lineHeight:1.15,whiteSpace:"nowrap",overflow:"hidden",textOverflow:"ellipsis"}}>{value}</div>
      {sub && <div style={{fontSize:"10px",color:AV.muted,marginTop:"3px"}}>{sub}</div>}
    </div>
  );
}

const avGrid = (min=150) => ({display:"grid",gridTemplateColumns:`repeat(auto-fit,minmax(${min}px,1fr))`,gap:"10px"});

function AvPills({ options, value, onChange }) {
  return (
    <div style={{display:"flex",gap:"4px",flexWrap:"wrap"}}>
      {options.map(([k,l]) => (
        <button key={k} onClick={()=>onChange(k)} style={{
          padding:"3px 10px",borderRadius:"20px",fontSize:"10px",cursor:"pointer",fontFamily:"'Inter',sans-serif",
          border: value===k ? "1px solid #5a6478" : "1px solid transparent",
          background: value===k ? AV.panel2 : "transparent", color: value===k ? AV.text : AV.muted}}>{l}</button>
      ))}
    </div>
  );
}

// Tabela simples, ordenável. cols: [{k,l,fmt?,align?,color?}]
function AvTable({ cols, rows, initialSort, maxH=420, empty="Sem dados." }) {
  const [sort, setSort] = useState(initialSort || null);
  const sorted = useMemo(() => {
    if (!sort) return rows;
    const [k, dir] = sort;
    return [...rows].sort((a,b) => {
      const x=a[k], y=b[k];
      if (x==null) return 1; if (y==null) return -1;
      return (typeof x==="string" ? x.localeCompare(y) : x-y) * dir;
    });
  }, [rows, sort]);
  if (!rows || !rows.length) return <div style={{color:AV.muted,fontSize:"10px",padding:"6px 0"}}>{empty}</div>;
  return (
    <div style={{overflow:"auto",maxHeight:maxH}}>
      <table style={{width:"100%",borderCollapse:"collapse",fontSize:"10.5px"}}>
        <thead><tr>{cols.map(c => (
          <th key={c.k} onClick={()=>setSort(s => s && s[0]===c.k ? [c.k,-s[1]] : [c.k,-1])}
            style={{position:"sticky",top:0,background:AV.panel,textAlign:c.align||"right",padding:"5px 6px",
              color:AV.muted,fontWeight:"500",fontSize:"9px",letterSpacing:"0.5px",textTransform:"uppercase",
              borderBottom:`1px solid ${AV.border}`,cursor:"pointer",whiteSpace:"nowrap"}}>
            {c.l}{sort && sort[0]===c.k ? (sort[1]>0?" ▲":" ▼") : ""}</th>))}</tr></thead>
        <tbody>{sorted.map((r,i) => (
          <tr key={i} className="row">{cols.map(c => {
            const v = r[c.k];
            return <td key={c.k} style={{textAlign:c.align||"right",padding:"5px 6px",borderBottom:`1px solid ${AV.border}55`,
              color: c.color ? avCol(v) : AV.text, whiteSpace:"nowrap"}}>{c.fmt ? c.fmt(v, r) : (v ?? "—")}</td>;
          })}</tr>))}</tbody>
      </table>
    </div>
  );
}

// Largura real do contentor (para o SVG não deformar o texto dos eixos)
function useWidth(initial=800) {
  const ref = useRef(null);
  const [w, setW] = useState(initial);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(es => { const cw = Math.round(es[0].contentRect.width); if (cw > 0) setW(cw); });
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

// Gráfico de linhas SVG. series: [{key,label,color,dash?}], data: [{d,...}]
function AvLines({ data, series, height=220, fmtY = v => avNum(v,0), zero=false }) {
  const [hover, setHover] = useState(null);
  const ref = useRef(null);
  const [box, W] = useWidth();
  const H = height, P = {l:46, r:10, t:10, b:22};
  const vals = data.flatMap(p => series.map(s => p[s.key])).filter(v => v!=null);
  if (data.length < 2 || !vals.length) return <div style={{color:AV.muted,fontSize:"10px"}}>Histórico insuficiente.</div>;
  let lo = Math.min(...vals, zero?0:Infinity), hi = Math.max(...vals, zero?0:-Infinity);
  if (lo===hi) { lo -= 1; hi += 1; }
  const pad = (hi-lo)*0.06; lo -= pad; hi += pad;
  const x = i => P.l + i*(W-P.l-P.r)/(data.length-1);
  const y = v => P.t + (hi-v)*(H-P.t-P.b)/(hi-lo);
  const ticks = Array.from({length:5},(_,i)=> lo + (hi-lo)*i/4);
  const nx = Math.max(2, Math.min(6, Math.floor(W/140)));
  const xt = Array.from({length:nx}, (_,i) => Math.round(i*(data.length-1)/(nx-1)));
  const onMove = e => {
    const r = ref.current.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width * W;
    setHover(Math.max(0, Math.min(data.length-1, Math.round((px-P.l)/(W-P.l-P.r)*(data.length-1)))));
  };
  return (
    <div ref={box} style={{position:"relative"}}>
      <svg ref={ref} viewBox={`0 0 ${W} ${H}`} width="100%" height={H}
        onMouseMove={onMove} onMouseLeave={()=>setHover(null)} style={{display:"block"}}>
        {ticks.map((t,i) => <g key={i}>
          <line x1={P.l} x2={W-P.r} y1={y(t)} y2={y(t)} stroke={AV.border} strokeWidth="1"/>
          <text x={P.l-6} y={y(t)+3} fontSize="10" fill={AV.muted} textAnchor="end">{fmtY(t)}</text></g>)}
        {lo<0 && hi>0 && <line x1={P.l} x2={W-P.r} y1={y(0)} y2={y(0)} stroke="#5a6478" strokeWidth="1"/>}
        {xt.map((i,j) => <text key={i} x={x(i)} y={H-6} fontSize="10" fill={AV.muted} textAnchor={j===0?"start":j===xt.length-1?"end":"middle"}>{avDate(data[i].d).slice(3)}</text>)}
        {series.map(s => {
          let path = "", pen = false;
          data.forEach((p,i) => { const v=p[s.key]; if (v==null) { pen=false; return; }
            path += (pen?"L":"M") + x(i).toFixed(1) + "," + y(v).toFixed(1); pen = true; });
          return <path key={s.key} d={path} fill="none" stroke={s.color} strokeWidth={s.width||1.6}
            strokeDasharray={s.dash||""} vectorEffect="non-scaling-stroke"/>;
        })}
        {hover!=null && <line x1={x(hover)} x2={x(hover)} y1={P.t} y2={H-P.b} stroke="#5a6478" strokeDasharray="3,3"/>}
      </svg>
      <div style={{display:"flex",gap:"12px",flexWrap:"wrap",marginTop:"6px",fontSize:"10px"}}>
        {hover!=null && <span style={{color:AV.muted}}>{avDate(data[hover].d)}</span>}
        {series.map(s => <span key={s.key} style={{color:s.color}}>
          ● {s.label}{hover!=null && data[hover][s.key]!=null ? `: ${s.fmt ? s.fmt(data[hover][s.key]) : avNum(data[hover][s.key])}` : ""}</span>)}
      </div>
    </div>
  );
}

// Barras SVG. data: [{label, value, value2?, color?}]
function AvBars({ data, height=160, fmt = v => avNum(v,0), color=AV.blue }) {
  const [box, W] = useWidth();
  if (!data.length) return <div style={{color:AV.muted,fontSize:"10px"}}>Sem dados.</div>;
  const H = height, P = {l:36, r:6, t:8, b:20};
  const hi = Math.max(...data.map(d => Math.max(d.value||0, d.value2||0)), 1);
  const bw = (W-P.l-P.r)/data.length;
  const y = v => P.t + (hi-v)*(H-P.t-P.b)/hi;
  return (
    <div ref={box}><svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} style={{display:"block"}}>
      {[0, hi/2, hi].map((t,i) => <g key={i}><line x1={P.l} x2={W-P.r} y1={y(t)} y2={y(t)} stroke={AV.border}/>
        <text x={P.l-4} y={y(t)+3} fontSize="10" fill={AV.muted} textAnchor="end">{fmt(t)}</text></g>)}
      {data.map((d,i) => <g key={i}>
        <rect x={P.l+i*bw+bw*0.15} y={y(d.value||0)} width={bw*0.7} height={Math.max(0,y(0)-y(d.value||0))}
          fill={d.color||color} rx="1.5"><title>{`${d.label}: ${fmt(d.value)}`}</title></rect>
        {(i % Math.ceil(data.length / Math.max(2, Math.floor(W/70))) === 0) &&
          <text x={P.l+i*bw+bw/2} y={H-6} fontSize="10" fill={AV.muted} textAnchor="middle">{d.label}</text>}
      </g>)}
    </svg></div>
  );
}

function AvNote({ children, warn }) {
  return <div style={{fontSize:"10px",color:warn?AV.amber:AV.muted,lineHeight:1.5,padding:"8px 10px",
    background:warn?"#d9a44112":"transparent",border:`1px solid ${warn?"#d9a44144":AV.border}`,borderRadius:"6px"}}>{children}</div>;
}

function AvEmpty() {
  return (
    <div style={{padding:"40px 16px",maxWidth:560,margin:"0 auto",color:AV.text,lineHeight:1.6,fontSize:"12px"}}>
      <div style={{fontSize:"15px",fontWeight:"700",color:AV.strong,marginBottom:"8px"}}>Ainda sem histórico de transações</div>
      <div>{(ANALYTICS && ANALYTICS.motivo) || "O ficheiro data/analytics.json ainda não foi gerado."}</div>
      <div style={{marginTop:"10px",color:AV.muted,fontSize:"11px"}}>
        O workflow <b>Update Portfolio Data</b> descarrega o extrato da Trading 212 (fetch_history.py), os preços históricos
        (fetch_price_history.py) e calcula estes separadores (build_analytics.py). Em alternativa, coloca os CSV exportados
        da Trading 212 em <code>data/statements/</code>.
      </div>
    </div>
  );
}

function AvShell({ children }) {
  return <div style={{flex:1,overflowY:"auto",padding:"14px 16px 40px",display:"flex",flexDirection:"column",gap:"12px"}}>{children}</div>;
}

function AvQuality() {
  const q = ANALYTICS.dataQuality || {};
  const issues = [];
  if (!q.temPrecosHistoricos) issues.push("Sem histórico de preços: TWR, risco e gráficos usam só os preços das transações.");
  if (q.semCotacaoYahoo && q.semCotacaoYahoo.length) issues.push(`Sem cotação no Yahoo (valorizados ao último preço de transação): ${q.semCotacaoYahoo.join(", ")}. Corrige em data/symbol_map.json.`);
  if (q.quantidadesDiferentes && q.quantidadesDiferentes.length) issues.push(`Quantidades do ledger diferentes da corretora: ${q.quantidadesDiferentes.map(m=>m.ticker).join(", ")}.`);
  if (q.dividendosBrutoEstimado) issues.push("O bruto de alguns dividendos foi estimado pelo câmbio do dia (a fonte não traz a retenção).");
  (q.avisos||[]).slice(0,5).forEach(a => issues.push(a));
  if (!issues.length) return null;
  return <AvNote warn><b>Qualidade dos dados</b> · {q.eventos} eventos de {avDate(q.primeiroEvento)} a {avDate(q.ultimoEvento)}
    <ul style={{margin:"4px 0 0 16px"}}>{issues.map((t,i)=><li key={i}>{t}</li>)}</ul></AvNote>;
}

// ═══ DESEMPENHO ════════════════════════════════════════════════════════════
const MONTHS = ["jan","fev","mar","abr","mai","jun","jul","ago","set","out","nov","dez"];

function heat(v) {
  if (v==null) return "transparent";
  const a = Math.min(Math.abs(v)/8, 1)*0.55 + 0.08;
  return v>=0 ? `rgba(8,153,129,${a})` : `rgba(239,83,80,${a})`;
}

function PerformanceView() {
  return (ANALYTICS && ANALYTICS.available) ? <PerformanceViewInner/> : <AvEmpty/>;
}

function PerformanceViewInner() {
  const P = ANALYTICS.performance, T = P.totais, R = P.risco;
  const [mode, setMode] = useState("twr");
  const [posFilter, setPosFilter] = useState("aberta");
  const bench = P.benchmarks || {};
  const chartSeries = mode === "twr"
    ? [{key:"twr",label:"Carteira (TWR)",color:AV.blue,width:2.2,fmt:v=>avPct(v,1)},
       ...Object.keys(bench).map(k => ({key:k,label:bench[k],color:BENCH_COLORS[k],dash:"4,3",fmt:v=>avPct(v,1)}))]
    : mode === "valor"
    ? [{key:"t",label:"Valor total",color:AV.blue,width:2.2,fmt:v=>avEur(v,0)},
       {key:"dep",label:"Capital depositado",color:AV.muted,dash:"4,3",fmt:v=>avEur(v,0)}]
    : [{key:"pnl",label:"Retorno total (€)",color:AV.green,width:2.2,fmt:v=>avSEur(v,0)}];
  const years = Object.keys(P.monthlyMatrix||{}).sort();
  const positions = (P.porPosicao||[]).filter(p => posFilter==="todas" || p.status===posFilter);
  const F = P.fechadas || {};
  const rep = P.seInvestidoNoIndice || {};

  return (
    <AvShell>
      <AvQuality/>
      <div style={avGrid(140)}>
        <AvKpi label="Valor total" value={avEur(T.totalValueEur,0)} sub={`posições ${avEur(T.positionsValueEur,0)} · caixa ${avEur(T.cashEur,0)}`}/>
        <AvKpi label="Retorno total" value={avSEur(T.totalReturnEur,0)} color={avCol(T.totalReturnEur)}
          sub={`${avPct(T.totalReturnPct)} sobre ${avEur(T.netDepositsEur,0)} depositados`} hint="Valor total da conta menos o capital líquido depositado"/>
        <AvKpi label="IRR" value={avPct(T.irrPct)} color={avCol(T.irrPct)} sub={`conta: ${avPct(T.irrAccountPct)} /ano`}
          hint="Retorno anual do teu dinheiro (money-weighted): conta quando e quanto investiste"/>
        <AvKpi label="TWR" value={avPct(T.twrPct)} color={avCol(T.twrPct)} sub={`desde ${avDate(P.inicio)}`}
          hint="Retorno das escolhas, imune a reforços e levantamentos (só títulos, sem caixa nem dividendos)"/>
        <AvKpi label="CAGR" value={avPct(T.cagrPct)} color={avCol(T.cagrPct)} sub={`S&P 500 ${avPct(T.benchmarkCagrPct?.spy)}`}/>
        <AvKpi label="YTD" value={avPct(T.ytdPct)} color={avCol(T.ytdPct)} sub="TWR do ano"/>
      </div>

      <AvCard title="Evolução" sub={mode==="twr" ? "retorno acumulado, time-weighted, em EUR" : ""}
        right={<AvPills value={mode} onChange={setMode} options={[["twr","Retorno vs índices"],["valor","Valor vs depositado"],["pnl","Retorno em €"]]}/>}>
        <AvLines data={P.chart||[]} series={chartSeries} height={240}
          fmtY={mode==="twr" ? v=>avNum(v,0)+"%" : v=>avNum(v/1000,1)+"k"} zero={mode!=="valor"}/>
      </AvCard>

      <div style={avGrid(300)}>
        <AvCard title="Risco" sub="em EUR, dias úteis, taxa sem risco 2%">
          <div style={avGrid(110)}>
            <AvKpi label="Volatilidade" value={avPct(R.volatilityPct,1,false)}/>
            <AvKpi label="Sharpe" value={avNum(R.sharpe)}/>
            <AvKpi label="Sortino" value={avNum(R.sortino)}/>
            <AvKpi label="Máx. drawdown" value={avPct(R.maxDrawdownPct,1)} color={AV.red} sub={`S&P 500 ${avPct(R.benchmarkMaxDrawdownPct?.spy,1)}`}/>
            <AvKpi label="Calmar" value={avNum(R.calmar)}/>
            <AvKpi label="Beta" value={avNum(R.beta)} sub="vs S&P 500"/>
            <AvKpi label="Alpha ajustado" value={avPct(R.alphaAdjustedPct)} color={avCol(R.alphaAdjustedPct)} hint="CAGR menos o que uma carteira passiva com o teu beta daria"/>
            <AvKpi label="Captura" value={`${avNum(R.captureVsSpyPct?.emAlta,0)} / ${avNum(R.captureVsSpyPct?.emBaixa,0)}`} sub="em alta / em baixa (%)"/>
          </div>
        </AvCard>
        <AvCard title="Se o mesmo dinheiro fosse para o índice" sub="mesmas datas, mesmos montantes">
          <AvTable cols={[{k:"l",l:"",align:"left"},{k:"eur",l:"Ganho",fmt:v=>avSEur(v,0),color:true},{k:"pct",l:"% do depositado",fmt:v=>avPct(v),color:true}]}
            rows={[{l:"A tua carteira",...rep.teu}, ...Object.keys(bench).filter(k=>rep[k]).map(k => ({l:bench[k],...rep[k]}))]}/>
          <div style={{marginTop:"10px"}}><AvNote>Cada compra compra o índice; cada venda e cada dividendo vende-o. A diferença mede a escolha dos títulos, não o dinheiro parado.</AvNote></div>
          <div style={{...avGrid(120),marginTop:"10px"}}>
            <AvKpi label="Máximo da carteira" value={avEur(P.maximos?.carteira?.maximoEur,0)} sub={`${avDate(P.maximos?.carteira?.data)} · hoje ${avPct(P.maximos?.carteira?.vsMaximoPct,1)}`}/>
            <AvKpi label="Máximo do retorno" value={avSEur(P.maximos?.retornoTotal?.maximoEur,0)} sub={`${avDate(P.maximos?.retornoTotal?.data)} · falta ${avEur(P.maximos?.retornoTotal?.faltaRecuperarEur,0)}`}/>
          </div>
        </AvCard>
      </div>

      <AvCard title="Retornos mensais" sub="TWR · verde sobe, vermelho desce">
        <div style={{overflowX:"auto"}}>
          <table style={{borderCollapse:"separate",borderSpacing:"3px",fontSize:"10px",width:"100%"}}>
            <thead><tr><th/>{MONTHS.map(m => <th key={m} style={{color:AV.muted,fontWeight:"500",textTransform:"capitalize"}}>{m}</th>)}
              <th style={{color:AV.muted,fontWeight:"500"}}>Ano</th></tr></thead>
            <tbody>{years.map(y => {
              const a = (P.annual||[]).find(r => String(r.year)===y);
              return <tr key={y}><td style={{color:AV.muted,paddingRight:"6px"}}>{y}</td>
                {MONTHS.map(m => { const v = P.monthlyMatrix[y][m];
                  return <td key={m} style={{background:heat(v),textAlign:"center",padding:"5px 2px",borderRadius:"3px",color:v==null?AV.muted:AV.strong}}>{v==null?"":avNum(v,1)}</td>; })}
                <td style={{textAlign:"center",fontWeight:"700",color:avCol(a?.portfolioPct)}}>{a ? avPct(a.portfolioPct,1) : ""}</td></tr>;
            })}</tbody>
          </table>
        </div>
        <div style={{display:"flex",gap:"16px",flexWrap:"wrap",marginTop:"8px",fontSize:"10px",color:AV.muted}}>
          {P.bestMonth && <span>Melhor mês: <b style={{color:AV.green}}>{P.bestMonth.ym} {avPct(P.bestMonth.pct,1)}</b></span>}
          {P.worstMonth && <span>Pior mês: <b style={{color:AV.red}}>{P.worstMonth.ym} {avPct(P.worstMonth.pct,1)}</b></span>}
          {P.currentStreak?.months > 0 && <span>Sequência: {P.currentStreak.months} meses a {P.currentStreak.direction==="up"?"subir":"descer"}</span>}
          {R.monthsBeatingSpyPct!=null && <span>Meses acima do S&P 500: {R.monthsBeatingSpyPct}%</span>}
        </div>
      </AvCard>

      <div style={avGrid(300)}>
        <AvCard title="Ano a ano vs índices" sub="TWR em EUR">
          <AvTable cols={[{k:"year",l:"Ano",align:"left"},{k:"portfolioPct",l:"Carteira",fmt:v=>avPct(v,1),color:true},
            ...Object.keys(bench).map(k => ({k:`${k}Pct`,l:bench[k],fmt:v=>avPct(v,1),color:true}))]} rows={P.annual||[]}/>
        </AvCard>
        <AvCard title="Sazonalidade" sub="média por mês do ano (meses completos)">
          <AvBars data={(P.seasonality||[]).map(s => ({label:s.label, value:Math.abs(s.avgPct), color:s.avgPct>=0?AV.green:AV.red}))}
            fmt={v=>avNum(v,1)+"%"} height={150}/>
        </AvCard>
      </div>

      <AvCard title="Resultado por posição" sub="realizado + não realizado + dividendos"
        right={<AvPills value={posFilter} onChange={setPosFilter} options={[["aberta","Abertas"],["fechada","Fechadas"],["todas","Todas"]]}/>}>
        <AvTable initialSort={["pnlEur",-1]} rows={positions} cols={[
          {k:"display",l:"Título",align:"left",fmt:(v,r)=><span title={r.name}>{v || r.ticker}</span>},
          {k:"investedEur",l:"Investido",fmt:v=>avEur(v,0)},
          {k:"valueEur",l:"Valor",fmt:v=>v?avEur(v,0):"—"},
          {k:"proceedsEur",l:"Vendido",fmt:v=>v?avEur(v,0):"—"},
          {k:"dividendsNetEur",l:"Dividendos",fmt:v=>v?avEur(v,2):"—"},
          {k:"pnlEur",l:"Resultado",fmt:v=>avSEur(v,0),color:true},
          {k:"roiPct",l:"ROI",fmt:v=>avPct(v,1),color:true},
          {k:"irrPct",l:"IRR",fmt:v=>avPct(v,1),color:true},
          {k:"heldDays",l:"Dias",fmt:v=>v},
        ]}/>
        {posFilter!=="aberta" && F.count > 0 && <div style={{...avGrid(120),marginTop:"10px"}}>
          <AvKpi label="Fechadas" value={F.count} sub={`${avNum(F.winRatePct,0)}% com ganho`}/>
          <AvKpi label="Resultado" value={avSEur(F.totalPnlEur,0)} color={avCol(F.totalPnlEur)}/>
          <AvKpi label="Ganho médio" value={avPct(F.avgWinPct,1)} color={AV.green}/>
          <AvKpi label="Perda média" value={avPct(F.avgLossPct,1)} color={AV.red}/>
          <AvKpi label="Detenção média" value={`${F.avgHeldDays} dias`}/>
        </div>}
      </AvCard>

      <AvNote>IRR e retorno total contam o dinheiro (datas e montantes); TWR, CAGR e risco contam as escolhas e ignoram a caixa parada
        e os dividendos. Benchmarks em EUR com dividendos reinvestidos (SPY, QQQ, URTH). Os impostos por pagar não estão descontados.</AvNote>
    </AvShell>
  );
}

// ═══ FISCAL ════════════════════════════════════════════════════════════════
function FiscalView() {
  return (ANALYTICS && ANALYTICS.available) ? <FiscalViewInner/> : <AvEmpty/>;
}


// ═══ RETENÇÃO NA FONTE A RECUPERAR ═════════════════════════════════════════
// Estados dos pedidos: guardados neste browser e, se houver token do GitHub
// (o mesmo do botão Deploy), também em data/cdti_status.json no repositório.
const REC_ESTADOS = [
  ["por_reclamar", "Por reclamar",                 "#5b8af5"],
  ["pedido",       "Pedido de reembolso enviado",  "#d9a441"],
  ["recebido",     "Reembolso recebido",           "#089981"],
  ["recusado",     "Reembolso recusado",           "#ef5350"],
  ["dispensado",   "Dispensar (não vou reclamar)", "#6b7280"],
];
const REC_CURTO = { por_reclamar:"Por reclamar", pedido:"Pedido", recebido:"Recebido", recusado:"Recusado", dispensado:"Dispensado" };
const REC_COR = Object.fromEntries(REC_ESTADOS.map(([k,,c]) => [k,c]));
const REC_LS = "cdti_status";
const REC_FILE = "data/cdti_status.json";

const flagEmoji = cc => cc && cc.length === 2 ? String.fromCodePoint(...[...cc.toUpperCase()].map(c => 127397 + c.charCodeAt(0))) : "🏳️";
const b64utf8 = str => btoa(unescape(encodeURIComponent(str)));
const utf8b64 = b64 => decodeURIComponent(escape(atob(b64.replace(/\n/g, ""))));

function recLoadLocal() {
  try { return JSON.parse(localStorage.getItem(REC_LS) || "{}"); } catch (e) { return {}; }
}

async function recSyncRepo(estados) {
  const pat = (() => { try { return localStorage.getItem("gh_pat"); } catch (e) { return null; } })();
  if (!pat) return "local";
  const api = `https://api.github.com/repos/${GH_REPO}/contents/${REC_FILE}`;
  const h = { "Authorization": `Bearer ${pat}`, "Accept": "application/vnd.github+json" };
  let sha, atual = {};
  const g = await fetch(api + "?ref=main", { headers: h });
  if (g.ok) { const j = await g.json(); sha = j.sha; try { atual = JSON.parse(utf8b64(j.content)).estados || {}; } catch (e) {} }
  else if (g.status !== 404) throw new Error(`GitHub ${g.status}`);
  const merged = { ...atual };
  Object.entries(estados).forEach(([k, v]) => {
    if (!merged[k] || (v.atualizado || "") >= (merged[k].atualizado || "")) merged[k] = v;
  });
  const body = { message: "chore: estado dos pedidos de reembolso de retenção [skip ci]",
    content: b64utf8(JSON.stringify({ estados: merged }, null, 1) + "\n"), branch: "main", ...(sha ? { sha } : {}) };
  const p = await fetch(api, { method: "PUT", headers: { ...h, "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!p.ok) throw new Error(`GitHub ${p.status}`);
  return "repo";
}

function RecoverySection({ data }) {
  const [local, setLocal] = useState(recLoadLocal);
  const [filtro, setFiltro] = useState("ativos");     // ativos | tudo
  const [estadoFiltro, setEstadoFiltro] = useState(null);
  const [aberto, setAberto] = useState(null);        // linha no modal
  const [escolha, setEscolha] = useState(null);
  const [msg, setMsg] = useState("");
  if (!data || !data.linhas) return null;

  const estadoDe = l => {
    const lo = local[l.id];
    if (lo && (lo.atualizado || "") >= (l.estadoAtualizado || "")) return lo.estado;
    return l.estado || "por_reclamar";
  };
  const linhas = data.linhas.map(l => ({ ...l, est: estadoDe(l) }));
  const soma = ks => linhas.filter(l => ks.includes(l.est)).reduce((s, l) => s + (l.recuperarEur || 0), 0);
  const conta = k => linhas.filter(l => l.est === k).length;
  const visiveis = linhas.filter(l => estadoFiltro ? l.est === estadoFiltro
    : filtro === "tudo" || ["por_reclamar", "pedido"].includes(l.est));

  const guardar = async () => {
    const novo = { ...local, [aberto.id]: { estado: escolha, atualizado: new Date().toISOString() } };
    setLocal(novo);
    try { localStorage.setItem(REC_LS, JSON.stringify(novo)); } catch (e) {}
    setAberto(null);
    setMsg("A guardar…");
    try {
      const onde = await recSyncRepo({ [aberto.id]: novo[aberto.id] });
      setMsg(onde === "repo" ? "Guardado neste dispositivo e no repositório." : "Guardado neste dispositivo. Configura o token do Deploy para sincronizar entre dispositivos.");
    } catch (e) {
      setMsg(`Guardado neste dispositivo; não foi possível sincronizar com o GitHub (${e.message}).`);
    }
    setTimeout(() => setMsg(""), 6000);
  };

  const Linha = ({ k, label }) => (
    <button onClick={() => setEstadoFiltro(estadoFiltro === k ? null : k)} style={{display:"flex",alignItems:"center",
      width:"100%",gap:"8px",padding:"8px 10px",borderRadius:"6px",cursor:"pointer",fontFamily:"'Inter',sans-serif",
      border:`1px solid ${estadoFiltro === k ? REC_COR[k] : AV.border}`,background:AV.panel2,color:AV.text,fontSize:"10px"}}>
      <span style={{color:REC_COR[k]}}>●</span><span style={{textTransform:"uppercase",letterSpacing:"0.6px"}}>{label}</span>
      <span style={{flex:1}}/><b style={{color:REC_COR[k],fontSize:"12px"}}>{avEur(soma([k]))}</b>
      <span style={{color:AV.muted}}>· {conta(k)} {conta(k) === 1 ? "caso" : "casos"}</span>
    </button>
  );

  return (
    <AvCard title="Retenção na fonte a recuperar" sub="imposto retido lá fora acima do limite da convenção">
      {!linhas.length
        ? <div style={{fontSize:"10px",color:AV.muted}}>Não há retenção a recuperar: em nenhum país a retenção passou o limite da convenção.</div>
        : <>
        <div style={{display:"flex",alignItems:"center",gap:"10px",flexWrap:"wrap"}}>
          <div>
            <div style={{fontSize:"9px",color:AV.muted,letterSpacing:"0.8px",textTransform:"uppercase"}}>A recuperar · em aberto</div>
            <div style={{fontSize:"22px",fontWeight:"700",color:AV.blue}}>{avEur(soma(["por_reclamar","pedido"]))}</div>
          </div>
          <div style={{flex:1}}/>
          <AvPills value={estadoFiltro ? "" : filtro} onChange={v => { setEstadoFiltro(null); setFiltro(v); }}
            options={[["ativos","Só ativos"],["tudo","Tudo"]]}/>
        </div>
        <div style={{display:"flex",gap:"6px",flexWrap:"wrap",margin:"8px 0"}}>
          {["por_reclamar","pedido"].map(k => (
            <button key={k} onClick={() => setEstadoFiltro(estadoFiltro === k ? null : k)} style={{fontSize:"10px",padding:"3px 10px",
              borderRadius:"20px",cursor:"pointer",fontFamily:"'Inter',sans-serif",background:"transparent",color:AV.text,
              border:`1px solid ${estadoFiltro === k ? REC_COR[k] : AV.border}`}}>
              <span style={{color:REC_COR[k]}}>●</span> {REC_CURTO[k]} · {conta(k)}</button>))}
        </div>
        <div style={{display:"flex",flexDirection:"column",gap:"6px",marginBottom:"10px"}}>
          <Linha k="recebido" label="Recebido"/><Linha k="recusado" label="Recusado"/><Linha k="dispensado" label="Dispensado"/>
        </div>
        {estadoFiltro && <div style={{fontSize:"10px",color:AV.muted,marginBottom:"8px"}}>A mostrar {REC_CURTO[estadoFiltro]} ·{" "}
          <a href="#" onClick={e => { e.preventDefault(); setEstadoFiltro(null); }} style={{color:AV.blue}}>limpar filtro</a></div>}
        <div style={avGrid(240)}>
          {visiveis.map(l => (
            <div key={l.id} style={{background:AV.bg,border:`1px solid ${AV.border}`,borderLeft:`3px solid ${REC_COR[l.est]}`,borderRadius:"8px",padding:"10px 12px"}}>
              <div style={{display:"flex",alignItems:"center",gap:"8px"}}>
                <span style={{fontSize:"20px"}}>{flagEmoji(l.pais)}</span>
                <div><div style={{fontSize:"12px",fontWeight:"600",color:AV.strong}}>{l.paisNome}</div>
                  <div style={{fontSize:"10px",color:AV.muted}}>{l.ano} · {l.empresas} {l.empresas === 1 ? "empresa" : "empresas"}</div></div>
                <div style={{flex:1}}/>
                <span style={{fontSize:"10px",color:REC_COR[l.est]}}>● {REC_CURTO[l.est]}</span>
              </div>
              <div style={{fontSize:"9px",color:AV.muted,letterSpacing:"0.8px",textTransform:"uppercase",marginTop:"8px"}}>A recuperar</div>
              <div style={{fontSize:"18px",fontWeight:"700",color:AV.blue}}>{avEur(l.recuperarEur)}</div>
              <table style={{width:"100%",fontSize:"10.5px",margin:"6px 0",borderCollapse:"collapse"}}><tbody>
                {[["Dividendos", l.brutoEur], ["Retido", l.retidoEur], [`Limite · ${l.limitePct}%`, l.limiteEur]].map(([k, v]) => (
                  <tr key={k}><td style={{color:AV.muted,padding:"3px 0",borderBottom:`1px solid ${AV.border}55`}}>{k}</td>
                    <td style={{textAlign:"right",padding:"3px 0",borderBottom:`1px solid ${AV.border}55`}}>{avEur(v)}</td></tr>))}
              </tbody></table>
              <div style={{display:"flex",alignItems:"center",gap:"8px"}}>
                <button className="cb" onClick={() => { setAberto(l); setEscolha(l.est); }} style={{fontSize:"11px",fontWeight:"600",
                  padding:"6px 14px",borderRadius:"6px",border:"1px solid #2962ff",background:"#2962ff22",color:AV.strong,
                  fontFamily:"'Inter',sans-serif",cursor:"pointer"}}>Reclamar</button>
                <span style={{fontSize:"10px",color:l.prazoPassado ? AV.red : AV.muted}}>
                  {l.prazoPassado ? "prazo terminou a " : "até "}{avDate(l.prazo)}</span>
              </div>
            </div>))}
        </div>
        {!visiveis.length && <div style={{fontSize:"10px",color:AV.muted}}>Nada neste filtro.</div>}
        {msg && <div style={{fontSize:"10px",color:AV.green,marginTop:"8px"}}>{msg}</div>}
        <div style={{marginTop:"10px"}}><AvNote>Calculado por pagamento: retido − {"limite da convenção"} × bruto, só nos dividendos com retenção.
          Ficam de fora {Object.entries(data.excluidos || {}).map(([c, m]) => `${COUNTRY_PT[c] || c} (${m})`).join("; ")}. {data.requisito}
          Valores estimados ao câmbio da corretora; prazos e formulários a confirmar no site oficial.</AvNote></div>
      </>}

      {aberto && (
        <div onClick={() => setAberto(null)} style={{position:"fixed",inset:0,background:"#000a",zIndex:500,display:"flex",
          alignItems:"center",justifyContent:"center",padding:"16px"}}>
          <div onClick={e => e.stopPropagation()} style={{background:AV.panel,border:`1px solid ${AV.border}`,borderRadius:"12px",
            width:"100%",maxWidth:"420px",maxHeight:"90vh",overflowY:"auto",boxShadow:"0 12px 40px #000c"}}>
            <div style={{display:"flex",alignItems:"center",gap:"10px",padding:"14px 16px",borderBottom:`1px solid ${AV.border}`}}>
              <span style={{fontSize:"24px"}}>{flagEmoji(aberto.pais)}</span>
              <div style={{fontSize:"14px",fontWeight:"700",color:AV.strong}}>{aberto.paisNome}<br/>{aberto.ano}</div>
              <div style={{flex:1}}/>
              <div style={{textAlign:"right"}}><div style={{fontSize:"9px",color:AV.muted,letterSpacing:"0.8px"}}>A RECUPERAR</div>
                <div style={{fontSize:"13px",color:AV.text}}>{avEur(aberto.recuperarEur)}</div></div>
            </div>
            <div style={{padding:"14px 16px",display:"flex",flexDirection:"column",gap:"8px"}}>
              <div style={{fontSize:"11px",color:AV.text,marginBottom:"2px"}}>Em que ponto está este pedido?</div>
              {REC_ESTADOS.map(([k, label, cor], i) => (
                <React.Fragment key={k}>
                  {k === "dispensado" && <div style={{borderTop:`1px solid ${AV.border}`,margin:"4px 0"}}/>}
                  <label style={{display:"flex",alignItems:"center",gap:"10px",padding:"10px 12px",borderRadius:"8px",cursor:"pointer",
                    border:`1px solid ${escolha === k ? "#2962ff" : AV.border}`,background:escolha === k ? "#2962ff1a" : "transparent",
                    fontSize:"12px",color:AV.strong}}>
                    <input type="radio" name="rec-estado" checked={escolha === k} onChange={() => setEscolha(k)} style={{accentColor:"#2962ff"}}/>
                    <span style={{color:cor}}>●</span>{label}
                  </label>
                </React.Fragment>))}
              <div style={{borderTop:`1px solid ${AV.border}`,margin:"6px 0 2px"}}/>
              <div style={{fontSize:"11px",color:AV.text,lineHeight:1.5}}>
                O reembolso pede-se à autoridade fiscal do país da empresa
                {aberto.formulario ? <>: <b>{aberto.formulario}</b>.</> : "."}</div>
              {data.requisito && <div style={{fontSize:"10px",color:AV.muted,lineHeight:1.5}}>{data.requisito}</div>}
              {aberto.url && <a href={aberto.url} target="_blank" rel="noopener" style={{display:"block",textAlign:"center",
                padding:"10px",borderRadius:"8px",background:"#2962ff",color:"#fff",fontWeight:"600",fontSize:"12px",
                textDecoration:"none"}}>{aberto.linkVerificado ? "Abrir formulário oficial ↗" : "Abrir site da autoridade fiscal ↗"}</a>}
              {aberto.urlInfo && <a href={aberto.urlInfo} target="_blank" rel="noopener" style={{display:"block",textAlign:"center",
                padding:"8px",borderRadius:"8px",border:"1px solid #2962ff",color:"#5b8af5",fontWeight:"600",fontSize:"11px",
                textDecoration:"none"}}>Instruções oficiais ↗</a>}
              {aberto.url && !aberto.linkVerificado && <div style={{fontSize:"10px",color:AV.amber,lineHeight:1.5}}>
                Para este país só temos a página principal da autoridade fiscal: procura lá o pedido de reembolso
                de imposto retido sobre dividendos de não residentes.</div>}
            </div>
            <div style={{display:"flex",justifyContent:"space-between",gap:"10px",padding:"12px 16px",borderTop:`1px solid ${AV.border}`}}>
              <button className="cb" onClick={() => setAberto(null)} style={{fontSize:"12px",padding:"8px 16px",borderRadius:"8px",
                border:`1px solid ${AV.border}`,background:AV.panel2,color:AV.text,fontFamily:"'Inter',sans-serif",cursor:"pointer"}}>Cancelar</button>
              <button className="cb" onClick={guardar} style={{fontSize:"12px",fontWeight:"600",padding:"8px 18px",borderRadius:"8px",
                border:"1px solid #2962ff",background:"#2962ff",color:"#fff",fontFamily:"'Inter',sans-serif",cursor:"pointer"}}>Guardar</button>
            </div>
          </div>
        </div>
      )}
    </AvCard>
  );
}

const COUNTRY_PT = { PT:"Portugal", US:"EUA", GB:"Reino Unido" };

function FiscalViewInner() {
  const F = ANALYTICS.fiscal;
  const years = (F.byYear||[]).map(y => y.ano).sort((a,b)=>b-a);
  const [year, setYear] = useState(years[0]);
  const [lotView, setLotView] = useState("posicao");
  const Y = (F.byYear||[]).find(y => y.ano===year) || {};
  const sales = (F.vendasPorLote||[]).filter(s => s.sellDate.startsWith(String(year)));
  const decl = (F.declaracaoRascunho||{})[String(year)] || [];
  const divDecl = (F.dividendosPorPais||{})[String(year)] || [];
  const L = F.lei31 || {}, S = F.seVenderTudoHoje || {}, TLH = F.taxLossHarvest || {};
  const lots = F.lotesAbertos || [];
  const byPos = useMemo(() => {
    const m = {};
    lots.forEach(l => { const p = m[l.key] || (m[l.key] = {ticker:l.ticker,name:l.name,tipo:l.tipo,costEur:0,valueEur:0,gainEur:0,lots:0,next:null,nextRate:null,saving:0});
      p.costEur += l.costEur||0; p.valueEur += l.valueEur||0; p.gainEur += l.gainEur||0; p.lots++;
      if (l.nextTierDate && (!p.next || l.nextTierDate < p.next)) { p.next = l.nextTierDate; p.nextRate = l.nextTierRatePct; }
      p.saving += l.savingAtNextTierEur||0; });
    return Object.values(m);
  }, [lots]);
  const isCur = year === new Date().getFullYear();

  return (
    <AvShell>
      <AvQuality/>
      <div style={{display:"flex",alignItems:"center",gap:"10px",flexWrap:"wrap"}}>
        <div style={{fontSize:"13px",fontWeight:"700",color:AV.strong}}>IRS · {year}{isCur ? " (ano em curso)" : ""}</div>
        <AvPills value={year} onChange={setYear} options={years.map(y => [y, String(y)])}/>
      </div>
      <div style={avGrid(140)}>
        <AvKpi label="IRS estimado" value={avEur(Y.irsEstimateEur)} color={AV.amber} sub="mais-valias + dividendos + juros"/>
        <AvKpi label="Mais-valias (saldo)" value={avSEur(Y.netRealizedEur)} color={avCol(Y.netRealizedEur)}
          sub={`ganhos ${avEur(Y.realizedGainsEur,0)} · perdas ${avEur(Y.realizedLossesEur,0)}`}/>
        <AvKpi label="IRS mais-valias" value={avEur(Y.irsRealizedEur)} sub={Y.prejuizoAReportarEur ? `prejuízo ${avEur(Y.prejuizoAReportarEur)} (reporte só com englobamento)` : `${Y.vendas||0} parcelas vendidas`}/>
        <AvKpi label="Dividendos brutos" value={avEur(Y.dividendsGrossEur)} sub={`retido lá fora ${avEur(Y.dividendTaxEur)} · IRS ${avEur(Y.irsDividendsEur)}`}/>
        <AvKpi label="Juros" value={avEur(Y.jurosBrutosEur)} sub={`IRS ${avEur(Y.irsJurosEur)}`}/>
        <AvKpi label="Comissões e taxas" value={avEur(Y.commissionsEur)} sub={`${Y.orderCount||0} ordens`}/>
      </div>

      <div style={avGrid(300)}>
        <AvCard title="Mais-valias por escalão" sub="Lei 31/2024 · por tempo de detenção">
          <AvTable rows={Y.byTier||[]} empty="Sem vendas neste ano." cols={[
            {k:"label",l:"Escalão",align:"left"},{k:"ratePct",l:"Taxa",fmt:v=>avNum(v,1)+"%"},
            {k:"gainsEur",l:"Ganhos",fmt:v=>avEur(v)},{k:"lossesEur",l:"Perdas",fmt:v=>avEur(v)},
            {k:"baseEur",l:"Saldo",fmt:v=>avSEur(v),color:true},{k:"irsEur",l:"IRS",fmt:v=>avEur(v)}]}/>
          <div style={{display:"flex",gap:"6px",flexWrap:"wrap",marginTop:"10px"}}>
            {(L.escalas||[]).map(e => <span key={e.label} style={{fontSize:"10px",padding:"3px 8px",borderRadius:"12px",background:AV.panel2,color:AV.text}}>{e.label}: <b>{avNum(e.ratePct,1)}%</b></span>)}
          </div>
          {Y.correcaoMonetariaEur ? <div style={{fontSize:"10px",color:AV.muted,marginTop:"6px"}}>Correção monetária (ações &gt; 24 meses): {avEur(Y.correcaoMonetariaEur)}</div> : null}
        </AvCard>
        <AvCard title="Se vendesses tudo hoje" sub="aos preços atuais, com as vendas já feitas este ano">
          <div style={avGrid(120)}>
            <AvKpi label="Valor de mercado" value={avEur(S.valorDeMercadoEur,0)}/>
            <AvKpi label="Ganho" value={avSEur(S.ganhoEur,0)} color={avCol(S.ganhoEur)}/>
            <AvKpi label="IRS da venda" value={avEur(S.irsDaVendaEur)} color={AV.amber} sub={`ano: ${avEur(S.irsDoAnoSemVenderEur,0)} → ${avEur(S.irsDoAnoVendendoEur,0)}`}/>
            <AvKpi label="Ficavas com" value={avEur(S.valorLiquidoEur,0)}/>
          </div>
          {L.proximaTransicao && <div style={{marginTop:"10px"}}><AvNote>
            Próxima mudança de escalão: <b>{L.proximaTransicao.ticker}</b> a {avDate(L.proximaTransicao.date)} ({L.proximaTransicao.dias} dias)
            passa para {avNum(L.proximaTransicao.toRatePct,1)}%{L.proximaTransicao.savingEur ? `, poupança estimada ${avEur(L.proximaTransicao.savingEur)}` : ""}.
            Poupança atual da Lei 31/2024 nos lotes em ganho: {avEur(L.poupancaEstimadaEur)}.</AvNote></div>}
        </AvCard>
      </div>

      <AvCard title="Otimização por perdas" sub="posições abertas em prejuízo">
        <div style={avGrid(140)}>
          <AvKpi label="Perda por realizar" value={avSEur(TLH.perdaPorRealizarEur,0)} color={AV.red}/>
          <AvKpi label="IRS do ano hoje" value={avEur(TLH.irsDoAnoAtualEur)}/>
          <AvKpi label="Vendendo as perdas" value={avEur(TLH.irsVendendoAsPerdasEur)}/>
          <AvKpi label="Poupança possível" value={avEur(TLH.poupancaPossivelEur)} color={AV.green}/>
        </div>
        <div style={{marginTop:"10px"}}><AvTable rows={TLH.posicoesEmPerda||[]} empty="Nenhuma posição em perda." maxH={200} cols={[
          {k:"ticker",l:"Título",align:"left",fmt:(v,r)=><span title={r.name}>{v}</span>},{k:"name",l:"Nome",align:"left"},{k:"perdaEur",l:"Perda",fmt:v=>avSEur(v),color:true}]}/></div>
        <div style={{marginTop:"8px"}}><AvNote>{TLH.nota}</AvNote></div>
      </AvCard>

      <AvCard title="Lotes em carteira" sub="FIFO, a preços atuais"
        right={<AvPills value={lotView} onChange={setLotView} options={[["posicao","Por posição"],["lote","Por lote"]]}/>}>
        {lotView==="posicao"
          ? <AvTable initialSort={["gainEur",-1]} rows={byPos} cols={[
              {k:"ticker",l:"Título",align:"left",fmt:(v,r)=><span title={r.name}>{v}</span>},{k:"tipo",l:"Tipo",align:"left",fmt:v=>v==="etf"?"ETF":"Ação"},{k:"lots",l:"Lotes"},
              {k:"costEur",l:"Custo",fmt:v=>avEur(v,0)},{k:"valueEur",l:"Valor",fmt:v=>avEur(v,0)},{k:"gainEur",l:"Ganho",fmt:v=>avSEur(v,0),color:true},
              {k:"next",l:"Próx. escalão",fmt:(v,r)=>v?`${avDate(v)} → ${avNum(r.nextRate,1)}%`:"—"},{k:"saving",l:"Poupança",fmt:v=>v?avEur(v):"—"}]}/>
          : <AvTable initialSort={["date",1]} rows={lots} cols={[
              {k:"ticker",l:"Título",align:"left"},{k:"date",l:"Compra",fmt:avDate},{k:"qty",l:"Unid.",fmt:v=>avNum(v,4)},
              {k:"costEur",l:"Custo",fmt:v=>avEur(v)},{k:"valueEur",l:"Valor",fmt:v=>avEur(v)},{k:"gainEur",l:"Ganho",fmt:v=>avSEur(v),color:true},
              {k:"holdingYears",l:"Anos",fmt:v=>avNum(v,2)},{k:"ratePct",l:"Taxa hoje",fmt:v=>avNum(v,1)+"%"},
              {k:"daysToNextTier",l:"Faltam",fmt:(v,r)=>v!=null?`${v} d → ${avNum(r.nextTierRatePct,1)}%`:"—"}]}/>}
      </AvCard>

      <AvCard title={`Vendas de ${year}, lote a lote`} sub="custo FIFO com encargos · compara com o resultado da corretora (custo médio)">
        <AvTable initialSort={["sellDate",-1]} rows={sales} empty="Sem vendas neste ano." cols={[
          {k:"ticker",l:"Título",align:"left",fmt:(v,r)=><span title={r.name}>{v}</span>},{k:"buyDate",l:"Compra",fmt:avDate},{k:"sellDate",l:"Venda",fmt:avDate},
          {k:"qty",l:"Unid.",fmt:v=>avNum(v,4)},{k:"costEur",l:"Custo",fmt:v=>avEur(v)},{k:"proceedsEur",l:"Venda",fmt:v=>avEur(v)},
          {k:"gainEur",l:"Mais-valia",fmt:v=>avSEur(v),color:true},{k:"brokerResultEur",l:"Corretora",fmt:v=>avSEur(v),color:true},
          {k:"tier",l:"Escalão",align:"left"},{k:"anexo",l:"Anexo",align:"left"}]}/>
      </AvCard>

      <AvCard title={`Rascunho para a declaração · ${year}`} sub="câmbio da corretora; a AT usa o do Banco de Portugal">
        <AvTable rows={decl} maxH={300} empty="Sem vendas neste ano." cols={[
          {k:"anexo",l:"Anexo",align:"left"},{k:"codigo",l:"Cód.",align:"left"},{k:"pais",l:"País",align:"left",fmt:(v,r)=>`${v} ${r.paisNome||""}`},
          {k:"ticker",l:"Título",align:"left"},{k:"realizacaoData",l:"Realização",fmt:avDate},{k:"realizacaoValorEur",l:"Valor",fmt:v=>avEur(v)},
          {k:"aquisicaoData",l:"Aquisição",fmt:avDate},{k:"aquisicaoValorEur",l:"Valor",fmt:v=>avEur(v)},{k:"despesasEncargosEur",l:"Encargos",fmt:v=>avEur(v)}]}/>
        <div style={{marginTop:"10px",fontSize:"10px",color:AV.muted,fontWeight:"600"}}>Dividendos por país</div>
        <AvTable rows={divDecl} maxH={220} empty="Sem dividendos neste ano." cols={[
          {k:"anexo",l:"Anexo",align:"left"},{k:"codigo",l:"Cód.",align:"left"},{k:"pais",l:"País",align:"left",fmt:(v,r)=>`${v} ${r.paisNome||""}`},
          {k:"brutoEur",l:"Bruto",fmt:v=>avEur(v)},{k:"impostoPagoEstrangeiroEur",l:"Imposto estrangeiro",fmt:v=>avEur(v)},{k:"creditoAdmitidoEur",l:"Crédito admitido",fmt:v=>avEur(v)}]}/>
        <div style={{marginTop:"8px"}}><AvNote>Declara também a conta na corretora estrangeira no {F.anexos?.contaEstrangeiro || "Anexo J · Quadro 11"}.
          Confirma os valores com o extrato oficial antes de submeter: o câmbio oficial pode mudar alguns cêntimos.</AvNote></div>
      </AvCard>

      <RecoverySection data={F.retencaoARecuperar}/>

      <AvCard title="Histórico">
        <AvTable rows={F.byYear||[]} cols={[
          {k:"ano",l:"Ano",align:"left"},{k:"netRealizedEur",l:"Mais-valias",fmt:v=>avSEur(v),color:true},{k:"irsRealizedEur",l:"IRS MV",fmt:v=>avEur(v)},
          {k:"dividendsGrossEur",l:"Div. brutos",fmt:v=>avEur(v)},{k:"irsDividendsEur",l:"IRS div.",fmt:v=>avEur(v)},
          {k:"jurosBrutosEur",l:"Juros",fmt:v=>avEur(v)},{k:"commissionsEur",l:"Comissões",fmt:v=>avEur(v)},{k:"irsEstimateEur",l:"IRS total",fmt:v=>avEur(v)}]}/>
      </AvCard>

      <AvNote><b>Estimativa informativa, não prescrição.</b> {(F.basesLegais||[]).join(" · ")}. Englobamento não simulado.
        Parâmetros em data/fiscal_config.json.</AvNote>
    </AvShell>
  );
}

// ═══ DIVIDENDOS ════════════════════════════════════════════════════════════
function DividendsView() {
  return (ANALYTICS && ANALYTICS.available) ? <DividendsViewInner/> : <AvEmpty/>;
}

function DividendsViewInner() {
  const D = ANALYTICS.dividends, R = D.recebido, Pv = D.previsao;
  const [tab, setTab] = useState("previsao");
  // Barras: 24 meses recebidos + 12 meses previstos
  const bars = useMemo(() => {
    const out = [], now = new Date();
    for (let i = 23; i >= 0; i--) {
      const d = new Date(now.getFullYear(), now.getMonth()-i, 1);
      const v = ((R.porMes||{})[String(d.getFullYear())]||{})[MONTHS[d.getMonth()]] || 0;
      out.push({label:`${MONTHS[d.getMonth()]} ${String(d.getFullYear()).slice(2)}`, value:v, color:AV.green});
    }
    for (let i = 1; i <= 12; i++) {
      const d = new Date(now.getFullYear(), now.getMonth()+i, 1);
      const k = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}`;
      out.push({label:`${MONTHS[d.getMonth()]} ${String(d.getFullYear()).slice(2)}`, value:(Pv.porMes||{})[k]?.netEur || 0, color:"#5b8af588"});
    }
    return out;
  }, []);
  const A = Pv.anoAtual || {};

  return (
    <AvShell>
      <AvQuality/>
      <div style={avGrid(140)}>
        <AvKpi label="Recebido (sempre)" value={avEur(R.totalNetEur)} color={AV.green} sub={`bruto ${avEur(R.totalGrossEur)} · retido ${avEur(R.totalTaxEur)}`}/>
        <AvKpi label={`Este ano`} value={avEur(A.recebidoEur)} sub={`faltam ~${avEur(A.faltaReceberEur)} → ${avEur(A.totalPrevistoEur)}`}/>
        <AvKpi label="Previsão anual" value={avEur(Pv.estimatedAnnualIncomeNetEur)} sub={`líquido · bruto ${avEur(Pv.estimatedAnnualIncomeEur)}`} hint="Estimativa a partir do historial de cada emitente"/>
        <AvKpi label="Média mensal" value={avEur(Pv.estimatedMonthlyAverageNetEur)} sub="líquida, estimada"/>
        <AvKpi label="Yield da carteira" value={avPct(Pv.portfolioYieldPct,2,false)} sub={`sobre o custo ${avPct(Pv.yieldOnCostPct,2,false)}`}/>
        <AvKpi label="Pagadoras" value={`${Pv.payingPositions}/${Pv.totalPositions}`} sub={Pv.topPayerSharePct ? `a maior: ${avNum(Pv.topPayerSharePct,0)}% do rendimento` : ""}/>
      </div>

      <AvCard title="Rendimento mensal" sub="verde: recebido (24 meses) · azul: previsto (12 meses)">
        <AvBars data={bars} fmt={v=>avNum(v,0)+"€"} height={170}/>
      </AvCard>

      <AvCard right={<AvPills value={tab} onChange={setTab} options={[["previsao","Previsão por posição"],["calendario","Calendário"],["recebido","Recebido por posição"],["anos","Por ano"]]}/>}
        title={{previsao:"Previsão por posição",calendario:"Próximos pagamentos",recebido:"Recebido por posição",anos:"Recebido por ano"}[tab]}>
        {tab==="previsao" && <AvTable initialSort={["estimatedAnnualIncomeNetEur",-1]} rows={Pv.posicoes||[]} cols={[
          {k:"ticker",l:"Título",align:"left",fmt:(v,r)=><span title={r.name}>{v}</span>},{k:"frequencyLabel",l:"Freq.",align:"left"},
          {k:"estimatedAnnualIncomeNetEur",l:"Anual líq.",fmt:v=>avEur(v)},{k:"withholdingRateAppliedPct",l:"Retenção",fmt:v=>avNum(v,0)+"%"},
          {k:"currentYieldPct",l:"Yield",fmt:v=>avPct(v,2,false)},{k:"yieldOnCostPct",l:"YoC",fmt:v=>avPct(v,2,false)},
          {k:"dpsCagr5yPct",l:"Cresc. 5a",fmt:(v,r)=>avPct(v ?? r.dpsCagr3yPct,1),color:true},
          {k:"stability",l:"Estab.",fmt:v=>v!=null?v:"—"},
          {k:"payoutRatioPct",l:"Payout",fmt:v=>v!=null?<span style={{color:v>100?AV.red:v>80?AV.amber:AV.text}}>{avNum(v,0)}%</span>:"—"},
          {k:"nextExDate",l:"Próx. ex-div.",fmt:v=>v?avDate(v)+" *":"—"},{k:"shareOfIncomePct",l:"Peso",fmt:v=>avNum(v,1)+"%"}]}/>}
        {tab==="calendario" && <AvTable rows={(Pv.calendario||[]).slice(0,60)} cols={[
          {k:"exDate",l:"Ex-dividendo",align:"left",fmt:v=>avDate(v)+" *"},{k:"payDate",l:"Pagamento",align:"left",fmt:v=>avDate(v)+" *"},
          {k:"ticker",l:"Título",align:"left"},{k:"brutoEur",l:"Bruto",fmt:v=>avEur(v)},{k:"liquidoEur",l:"Líquido",fmt:v=>avEur(v)}]}/>}
        {tab==="recebido" && <AvTable initialSort={["netEur",-1]} rows={R.porPosicao||[]} cols={[
          {k:"ticker",l:"Título",align:"left",fmt:(v,r)=><span title={r.name}>{v}{r.aberta?"":" ·"}</span>},{k:"pagamentos",l:"Pag."},
          {k:"grossEur",l:"Bruto",fmt:v=>avEur(v)},{k:"taxEur",l:"Retido",fmt:v=>avEur(v)},{k:"withholdingPct",l:"Taxa",fmt:v=>avNum(v,0)+"%"},
          {k:"netEur",l:"Líquido",fmt:v=>avEur(v)},{k:"costRecoveredPct",l:"Custo recuperado",fmt:v=>avPct(v,2,false)},{k:"shareOfTotalPct",l:"Peso",fmt:v=>avNum(v,1)+"%"}]}/>}
        {tab==="anos" && <>
          <AvTable rows={R.porAno||[]} cols={[{k:"ano",l:"Ano",align:"left",fmt:(v,r)=>`${v}${r.parcial?" (parcial)":""}`},{k:"pagamentos",l:"Pagamentos"},
            {k:"grossEur",l:"Bruto",fmt:v=>avEur(v)},{k:"taxEur",l:"Retido",fmt:v=>avEur(v)},{k:"netEur",l:"Líquido",fmt:v=>avEur(v)},
            {k:"variacaoPct",l:"Variação",fmt:v=>avPct(v,1),color:true}]}/>
          {R.variacaoAnual && <div style={{marginTop:"10px"}}>
            <div style={{fontSize:"10px",color:AV.muted,marginBottom:"4px"}}>De {R.variacaoAnual.de} para {R.variacaoAnual.para}: {avSEur(R.variacaoAnual.deltaEur)} — quem contribuiu</div>
            <AvTable rows={R.variacaoAnual.porPosicao||[]} maxH={220} cols={[{k:"ticker",l:"Título",align:"left"},{k:"de",l:String(R.variacaoAnual.de),fmt:v=>avEur(v)},
              {k:"para",l:String(R.variacaoAnual.para),fmt:v=>avEur(v)},{k:"deltaEur",l:"Δ",fmt:v=>avSEur(v),color:true},{k:"motivo",l:"Motivo",align:"left"}]}/></div>}
        </>}
      </AvCard>

      <AvNote>* Datas previstas pela cadência dos pagamentos anteriores (o pagamento é estimado a +21 dias do ex-dividendo). A previsão
        é uma estimativa: o emitente pode cortar, aumentar ou suspender o dividendo. Os recebidos são exatos, do extrato da corretora.
        · = posição já fechada.</AvNote>
    </AvShell>
  );
}
