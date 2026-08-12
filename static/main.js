
// Mes ativo do dashboard (?mes=YYYY-MM). Threaded nos AJAX pra os cards repintarem
// com os numeros DO mes exibido (nao do total).
window.__mesAtivo = new URLSearchParams(location.search).get("mes") || ""
window._mesQS = function(sep){ return window.__mesAtivo ? sep + "mes=" + encodeURIComponent(window.__mesAtivo) : "" }

// Remove a "/" da EXIBIÇÃO (vira espaço). O dado original mantém a "/" pra detecção interna.
window.semBarra = function(txt){ return String(txt||"").replace(/\s*\/\s*/g, " ").replace(/\s+/g, " ").trim() }

function limparApostaDuplicadaVisual(){
    document.querySelectorAll("tbody tr").forEach(tr=>{
        const jogoEl = tr.querySelector(".jogo-cell")
        const apostaEl = tr.querySelector(".aposta-cell")
        if(!jogoEl || !apostaEl) return
        let aposta = apostaEl.innerText.trim()
        if(!aposta) return

        // Se a aposta contém " - " e o trecho antes dele parece um jogo (tem " x " ou " vs ")
        // ex: "PSG x Arsenal - PSG PARA GANHAR" → "PSG PARA GANHAR"
        const dashIdx = aposta.indexOf(" - ")
        if(dashIdx > 0){
            const prefix = aposta.slice(0, dashIdx)
            if(/\s(x|vs\.?)\s/i.test(prefix)){
                const resto = aposta.slice(dashIdx + 3).trim()
                if(resto){
                    apostaEl.innerText = resto
                    apostaEl.title = aposta
                    return
                }
            }
        }

        // Fallback: match exato com o nome do jogo
        const jogo = jogoEl.innerText.trim()
        if(jogo && aposta.toLowerCase().startsWith((jogo + " - ").toLowerCase())){
            apostaEl.innerText = aposta.slice(jogo.length + 3).trim()
            apostaEl.title = aposta
        }
    })
}
function formatarLinhaApostaNova(b){
    const apostaVisual = window.semBarra((b.jogo && b.aposta && b.aposta.toLowerCase().startsWith((b.jogo + " - ").toLowerCase()))
        ? b.aposta.slice(b.jogo.length + 3)
        : (b.aposta || ""))
    const valor = parseFloat(b.valor || 0).toFixed(2)
    const lucro = parseFloat(b.lucro || 0).toFixed(2)
    return `
    <tr class="bet-row">
        <td class="data-cell">${b.data || ""}</td>
        <td class="casa-cell">${b.casa || ""}</td>
        <td class="esporte-cell">${b.esporte || ""}</td>
        <td class="jogo-cell">${window.semBarra(b.jogo || "")}</td>
        <td class="aposta-cell" title="${b.aposta || ""}">${apostaVisual}</td>
        <td class="odd-cell">${b.odd || ""}</td>
        <td class="valor-cell">${valor}</td>
        <td class="status-cell"><span class="badge yellow">Pendente</span></td>
        <td>R$ ${lucro}</td>
        <td class="api-cell">${b.api_status || ""}</td>
        <td class="actions">
            <a href="/resultado/${b.id}/ganha"><button class="green">✔</button></a>
            <a href="/resultado/${b.id}/perdida"><button class="red">✖</button></a>
            <a href="/resultado/${b.id}/anulada"><button class="gray">↺</button></a>
            <button class="blue" onclick="abrirEditar(this)" data-id="${b.id}" data-estado="" data-horario="${b.horario_jogo_iso || ""}">✎</button>
            <a href="/remover/${b.id}"><button class="dark">🗑</button></a>
        </td>
    </tr>`
}

function formatarLinhaApostaNovaV39(b){
    const valor = parseFloat(b.valor || 0).toFixed(2)
    const lucro = parseFloat(b.lucro || 0).toFixed(2)
    const apostaVisual = b.aposta_display || b.aposta || ""
    return `
    <tr class="bet-row">
        <td class="data-cell">${b.data || ""}</td>
        <td class="casa-cell">${b.casa || ""}</td>
        <td class="esporte-cell">${b.esporte || ""}</td>
        <td class="jogo-cell">${b.jogo || ""}</td>
        <td class="aposta-cell" title="${b.aposta || ""}">${apostaVisual}</td>
        <td class="odd-cell">${b.odd || ""}</td>
        <td class="valor-cell">${valor}</td>
        <td class="status-cell"><span class="badge yellow">Pendente</span></td>
        <td>R$ ${lucro}</td>
        <td class="api-cell">${b.api_status || ""}</td>
        <td class="actions">
            <a href="/resultado/${b.id}/ganha"><button class="green">✔</button></a>
            <a href="/resultado/${b.id}/perdida"><button class="red">✖</button></a>
            <a href="/resultado/${b.id}/anulada"><button class="gray">↺</button></a>
            <button class="blue" onclick="abrirEditar(this)" data-id="${b.id}" data-estado="" data-horario="${b.horario_jogo_iso || ""}">✎</button>
            <a href="/remover/${b.id}"><button class="dark">🗑</button></a>
        </td>
    </tr>`
}

function dinheiroBR(v){
    const n = parseFloat(v || 0)
    return "R$ " + n.toFixed(2)
}

function atualizarMetricasV43(m){
    if(!m) return
    const banca = document.getElementById("metric-banca")
    const saldo = document.getElementById("metric-valor-aberto")
    const lucro = document.getElementById("metric-lucro")
    const roi = document.getElementById("metric-roi")
    const taxa = document.getElementById("metric-taxa")
    const total = document.getElementById("metric-total")
    const pend = document.getElementById("metric-pendentes")
    if(banca) banca.innerText = dinheiroBR(m.banca_atual)
    if(saldo) saldo.innerText = dinheiroBR(m.valor_em_aberto !== undefined ? m.valor_em_aberto : 0)
    if(lucro){
        lucro.innerText = dinheiroBR(m.lucro_total)
        lucro.classList.remove("green-text", "red-text")
        lucro.classList.add(parseFloat(m.lucro_total || 0) >= 0 ? "green-text" : "red-text")
    }
    if(roi) roi.innerText = parseFloat(m.roi || 0).toFixed(2) + "%"
    if(taxa) taxa.innerText = parseFloat(m.taxa || 0).toFixed(2) + "%"
    if(total) total.innerText = m.total
    if(pend) pend.innerText = m.pendentes
}

function badgeStatusV43(estado){
    if(estado === "ganha") return '<span class="badge green">Ganha</span>'
    if(estado === "perdida") return '<span class="badge red">Perdida</span>'
    if(estado === "anulada") return '<span class="badge gray">Anulada</span>'
    return '<span class="badge yellow">Pendente</span>'
}

function atualizarLinhaResultadoV43(tr, b){
    if(!tr || !b) return
    const statusCell = tr.querySelector(".status-cell")
    if(statusCell) statusCell.innerHTML = badgeStatusV43(b.estado || "")
    const lucroCell = tr.children[12]
    if(lucroCell){
        const lucro = parseFloat(b.lucro || 0)
        lucroCell.innerText = dinheiroBR(lucro)
        lucroCell.classList.remove("green-text", "red-text")
        if(lucro > 0) lucroCell.classList.add("green-text")
        if(lucro < 0) lucroCell.classList.add("red-text")
    }
    const apiCell = tr.querySelector(".api-cell")
    if(apiCell && b.api_status !== undefined) apiCell.innerText = b.api_status || ""
    const editBtn = tr.querySelector('button.blue[data-id]')
    if(editBtn) editBtn.dataset.estado = b.estado || ""
}

window.apostasPreview = window.apostasPreview || []

function escapeHtmlPreview(value){
    return String(value ?? "").replaceAll("&","&amp;").replaceAll('"',"&quot;").replaceAll("<","&lt;").replaceAll(">","&gt;")
}

function toggleSidebar(){
    document.body.classList.toggle("sidebar-collapsed")
    const collapsed = document.body.classList.contains("sidebar-collapsed")
    localStorage.setItem("sidebarCollapsed", collapsed ? "1" : "0")
    const btn = document.querySelector(".sidebar-toggle")
    if(btn) btn.innerText = collapsed ? "›" : "‹"
}
let painelAtual = "banca"
function mostrarPainelDashboard(tipo){
    const banca = document.getElementById("aba-banca")
    const feed = document.getElementById("aba-feed")
    const btnBanca = document.getElementById("tabBancaBtn")
    const btnFeed = document.getElementById("tabFeedBtn")
    painelAtual = tipo
    if(tipo === "feed"){
        banca.classList.remove("active"); feed.classList.add("active")
        btnBanca.classList.remove("active"); btnFeed.classList.add("active")
        carregarFeedApostas(true)
    } else {
        feed.classList.remove("active"); banca.classList.add("active")
        btnFeed.classList.remove("active"); btnBanca.classList.add("active")
    }
}

function carregarFeedApostas(force=false){
    const div = document.getElementById("feed-apostas")
    if(!div) return
    const idsAntes = new Set(Array.from(div.querySelectorAll(".feed-card[data-id]")).map(el=>el.dataset.id))
    if(force || div.dataset.loaded !== "1") div.innerHTML = `<div class="feed-empty">Carregando últimas apostas...</div>`
    fetch("/ultimas_apostas", {cache:"no-store"})
    .then(r=>r.json())
    .then(d=>{
        div.dataset.loaded = "1"; div.innerHTML = ""
        if(!d || d.length === 0){ div.innerHTML = `<div class="feed-empty">Nenhuma aposta pública encontrada.</div>`; return }
        d.forEach((a,idx)=>{
            const payload = encodeURIComponent(JSON.stringify(a))
            const id = a.id || `${a.jogo}-${a.aposta}-${a.odd}-${a.valor}`
            const isNew = idsAntes.size > 0 && !idsAntes.has(String(id)) && idx === 0
            div.innerHTML += `<div class="feed-card ${isNew?"feed-new":""}" data-id="${id}"><div class="feed-card-main"><div class="feed-title-line"><strong>${a.jogo||"Jogo não informado"}</strong>${isNew?'<span class="novo-badge">NOVO</span>':''}</div><span>${a.aposta||""}</span><div class="feed-meta">${a.casa||"Casa"} • ${a.esporte||"Esporte"} • Odd ${a.odd||"-"} • R$ ${a.valor||"-"} ${a.horario_jogo?"• Jogo: "+a.horario_jogo:""} ${a.data?"• "+a.data:""}</div></div><button type="button" class="copy-bet-btn" data-payload="${payload}" onclick="copiarApostaComunidade(this)">Copiar</button></div>`
        })
    })
    .catch(()=>{ if(div.dataset.loaded !== "1") div.innerHTML = `<div class="feed-empty">Erro ao carregar últimas apostas.</div>` })
}

function copiarApostaComunidade(btn){
    const data = JSON.parse(decodeURIComponent(btn.dataset.payload || "{}"))
    const fields = {
        aposta: document.querySelector('input[name="aposta"]'),
        casa: document.querySelector('input[name="casa"]'),
        esporte: document.querySelector('input[name="esporte"]'),
        jogo: document.querySelector('input[name="jogo"]'),
        odd: document.querySelector('input[name="odd"]'),
        valor: document.querySelector('input[name="valor"]')
    }
    if(fields.aposta) fields.aposta.value = data.aposta || ""
    if(fields.casa) fields.casa.value = data.casa || ""
    if(fields.esporte) fields.esporte.value = data.esporte || ""
    if(fields.jogo) fields.jogo.value = data.jogo || ""
    if(fields.odd) fields.odd.value = data.odd || ""
    if(fields.valor) fields.valor.value = data.valor || ""
    const copiedFlag = document.getElementById("copiadaComunidade"); if(copiedFlag) copiedFlag.value = "1"
    const src = document.getElementById("sourceOriginalId"); if(src) src.value = data.source_original_id || data.id || ""
    const hj = document.getElementById("horarioJogo"); if(hj) hj.value = data.horario_jogo || ""
    btn.classList.add("copied"); btn.innerText = "Copiado"
    setTimeout(()=>{ btn.classList.remove("copied"); btn.innerText = "Copiar" }, 1200)
    document.querySelector('input[name="aposta"]')?.focus()
}

function mostrarEditarBanca(){
    document.getElementById("banca-view").style.display="none"
    document.getElementById("banca-form").style.display="flex"
}
function cancelarEditarBanca(){
    document.getElementById("banca-form").style.display="none"
    document.getElementById("banca-view").style.display="flex"
}

function toggleDropdown(dropdownId, inputId){
    const dropdown = document.getElementById(dropdownId)
    dropdown.classList.toggle("open")
    if(dropdown.classList.contains("open")) setTimeout(()=>document.getElementById(inputId).focus(), 80)
}
function filtrarLista(selector, inputId){
    const busca = document.getElementById(inputId).value.toLowerCase()
    document.querySelectorAll(selector).forEach(item=>{ item.style.display = item.innerText.toLowerCase().includes(busca) ? "flex" : "none" })
}
function selecionarVisiveis(selector, checked){
    document.querySelectorAll(selector).forEach(item=>{ if(item.style.display !== "none") item.querySelector("input").checked = checked })
    filtrarApostas()
}
function valoresSelecionados(selector){
    return Array.from(document.querySelectorAll(selector + " input:checked")).map(i=>i.value.toLowerCase())
}
function converterDataBR(dataTexto){
    const partes = dataTexto.split(" ")[0].split("/")
    if(partes.length < 3) return null
    return new Date(parseInt(partes[2]), parseInt(partes[1])-1, parseInt(partes[0]))
}
function _limparSeparadores(){
    // Um separador de dia só aparece se houver aposta visível abaixo dele.
    // (Regra única e sempre correta — segue o que filtrarApostas deixou visível.)
    const rows = Array.from(document.querySelectorAll("#betsMainTable tbody tr"))
    let i = 0
    while(i < rows.length){
        const r = rows[i]
        if(r.classList.contains("day-separator-row-v136")){
            let hasVisible = false
            let j = i + 1
            while(j < rows.length && !rows[j].classList.contains("day-separator-row-v136")){
                const n = rows[j]
                if(n.classList.contains("bet-row") && getComputedStyle(n).display !== "none"){
                    hasVisible = true; break
                }
                j++
            }
            r.style.display = hasVisible ? "table-row" : "none"
        } else if(r.classList.contains("game-group-row-v136")){
            let hasVisible = false
            let j = i + 1
            while(j < rows.length && !rows[j].classList.contains("day-separator-row-v136") && !rows[j].classList.contains("game-group-row-v136")){
                if(rows[j].classList.contains("bet-row") && getComputedStyle(rows[j]).display !== "none"){ hasVisible=true; break }
                j++
            }
            r.style.display = hasVisible ? "" : "none"
        }
        i++
    }
}
let _eyeAberto = false
function toggleEye(){
    _eyeAberto = !_eyeAberto
    document.getElementById("eyeIconOpen").style.display = _eyeAberto ? "" : "none"
    document.getElementById("eyeIconClosed").style.display = _eyeAberto ? "none" : ""
    const btn = document.getElementById("eyeToggleBtn")
    if(btn) btn.classList.toggle("eye-active", _eyeAberto)
    filtrarApostas()
}
function onDatePickerChange(){
    const dp=document.getElementById("datePicker"),cb=document.getElementById("clearDateBtn")
    if(cb) cb.style.display=dp?.value?"inline-flex":"none"
    filtrarApostas()
}
function clearDatePicker(){
    const dp=document.getElementById("datePicker"),cb=document.getElementById("clearDateBtn")
    if(dp) dp.value=""
    if(cb) cb.style.display="none"
    filtrarApostas()
}
function filtrarApostas(){
    const activePill = document.querySelector('#betStatusPills .bet-pill.active')
    const pillStatus = activePill ? activePill.dataset.status : null
    const busca = (document.getElementById("searchInput")?.value || "").toLowerCase()
    const status = pillStatus || document.getElementById("statusFilter")?.value || "todos"
    const datePicker = document.getElementById("datePicker")?.value || ""
    const casasChecked = Array.from(document.querySelectorAll("#casasDrop input[type=checkbox]:not([value=__todos]):checked")).map(c=>c.value.toLowerCase())
    const esporteFiltro = (document.getElementById("esporteSelect")?.value || "").toLowerCase()
    const hoje = new Date(); hoje.setHours(0,0,0,0)
    const ontem = new Date(hoje); ontem.setDate(hoje.getDate()-1)
    const amanha = new Date(hoje); amanha.setDate(hoje.getDate()+1)
    const mostrarFinalizadas = status === "finalizadas"
    // Busca por texto ou data específica ignora a janela ±1 dia (procura em todas as apostas)
    const deveVerHistorico = _eyeAberto || !!busca || ["finalizadas","ganha","perdida","anulada"].includes(status)
document.querySelectorAll("tbody tr.bet-row").forEach(linha=>{
        const texto = linha.innerText.toLowerCase()
        const statusTexto = (linha.querySelector(".status-cell")?.innerText || "").toLowerCase()
        const casaTexto = (linha.querySelector(".casa-cell")?.innerText || "").toLowerCase().trim()
        const esporteTexto = (linha.querySelector(".esporte-cell")?.innerText || "").toLowerCase().trim()
        // Prefer game date (ISO) so bets appear in the window when the GAME happens
        const isoHorario = linha.dataset.horarioJogoIso || ""
        let dataAposta = null
        if(isoHorario){ const _d=new Date(isoHorario);if(!isNaN(_d.getTime())) dataAposta=new Date(_d.getFullYear(),_d.getMonth(),_d.getDate()) }
        if(!dataAposta){ const dataTexto=linha.dataset.data||""; dataAposta=converterDataBR(dataTexto) }
        const isFinished = statusTexto.includes("ganha")||statusTexto.includes("perdida")||statusTexto.includes("anulada")
        let mostrar = true
        if(busca && !texto.includes(busca)) mostrar = false
        if(casasChecked.length > 0 && !casasChecked.includes(casaTexto)) mostrar = false
        if(esporteFiltro && esporteFiltro !== "todos" && esporteTexto !== esporteFiltro) mostrar = false
        // Filtro de data: default mostra hoje, amanhã e pendentes passadas (jogo aconteceu
        // mas sem resultado). Oculta resolvidas fora da janela e futuras além de amanhã.
        // Olhinho aberto ou busca/status específico libera tudo.
        if(datePicker){
            if(dataAposta){ const p=n=>String(n).padStart(2,"0");const ds=`${dataAposta.getFullYear()}-${p(dataAposta.getMonth()+1)}-${p(dataAposta.getDate())}`;if(ds!==datePicker) mostrar=false }
        } else if(!deveVerHistorico && dataAposta){
            const isHoje    = dataAposta.getTime()===hoje.getTime()
            const isAmanha  = dataAposta.getTime()===amanha.getTime()
            // Pendente de QUALQUER data (passada ou futura) fica visivel — agrupada no
            // dia do JOGO. Assim aposta feita hoje pra jogo de sexta aparece em sexta.
            const isPend    = !isFinished
            if(!isHoje && !isAmanha && !isPend) mostrar=false
        }
        if(mostrarFinalizadas){ if(!isFinished) mostrar = false }
        else { if(status !== "todos" && !statusTexto.includes(status)) mostrar = false }
        if(mostrar){
            // só mexe na classe se ela existe (evita mutação/reflow à toa)
            if(linha.classList.contains("v149-historico-hidden")) linha.classList.remove("v149-historico-hidden")
            if(linha.classList.contains("group-collapsed-v136")) linha.classList.remove("group-collapsed-v136")
            let prev = linha.previousElementSibling
            while(prev && !prev.classList.contains("day-separator-row-v136")){
                if(prev.classList.contains("game-group-row-v136")){ if(prev.style.display!=="") prev.style.display=""; break }
                prev = prev.previousElementSibling
            }
        }
        const novoDisplay = mostrar ? "table-row" : "none"
        if(linha.style.display !== novoDisplay) linha.style.display = novoDisplay
        const fv = mostrar ? "1" : "0"
        if(linha.dataset.v147Filtered !== fv) linha.dataset.v147Filtered = fv
    })
    filtrarHistoricoPanel(busca, casasChecked, esporteFiltro, datePicker)
    _limparSeparadores()
    if(window.v155SyncSubtotals) window.v155SyncSubtotals()
}

// v161: a busca/filtros tambem varrem o painel de HISTORICO (finalizadas de dias
// anteriores, classe .bet-row-historico). Sem isso, pesquisar um jogo ja' encerrado
// nao achava nada (regressao do split). So' roda quando ha' filtro ativo — no view
// padrao faz early-return (preserva a performance de nao processar as antigas).
function filtrarHistoricoPanel(busca, casasChecked, esporteFiltro, datePicker){
    const det = document.getElementById("historicoSection")
    if(!det) return
    const rows = det.querySelectorAll("tr.bet-row-historico")
    if(!rows.length) return
    const filtroAtivo = !!busca || (casasChecked && casasChecked.length > 0) || (esporteFiltro && esporteFiltro !== "todos") || !!datePicker
    if(!filtroAtivo){
        // Sem filtro: restaura o que mexemos e, se fomos NOS que abrimos, fecha de volta.
        if(window.__histTouched){ rows.forEach(r=>{ if(r.style.display!=="") r.style.display="" }); window.__histTouched=false }
        if(window.__histForcedOpen){ det.open=false; window.__histForcedOpen=false }
        const bdg=det.querySelector(".historico-count-badge")
        if(bdg && bdg.dataset.orig!==undefined){ bdg.textContent=bdg.dataset.orig; delete bdg.dataset.orig }
        return
    }
    window.__histTouched=true
    let matches=0
    rows.forEach(linha=>{
        const texto=linha.innerText.toLowerCase()
        const casaTexto=(linha.querySelector(".casa-cell")?.innerText||"").toLowerCase().trim()
        const esporteTexto=(linha.querySelector(".esporte-cell")?.innerText||"").toLowerCase().trim()
        let mostrar=true
        if(busca && !texto.includes(busca)) mostrar=false
        if(casasChecked && casasChecked.length>0 && !casasChecked.includes(casaTexto)) mostrar=false
        if(esporteFiltro && esporteFiltro!=="todos" && esporteTexto!==esporteFiltro) mostrar=false
        if(datePicker){ const iso=linha.dataset.horario||""; if(iso){ const d=new Date(iso); if(!isNaN(d.getTime())){ const p=n=>String(n).padStart(2,"0"); const ds=`${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}`; if(ds!==datePicker) mostrar=false } } }
        const novo=mostrar?"":"none"
        if(linha.style.display!==novo) linha.style.display=novo
        if(mostrar) matches++
    })
    if(matches>0 && !det.open){ det.open=true; window.__histForcedOpen=true }
    const bdg=det.querySelector(".historico-count-badge")
    if(bdg){ if(bdg.dataset.orig===undefined) bdg.dataset.orig=bdg.textContent; bdg.textContent=matches }
}
// Debounce único para digitação — evita rodar/reflow a cada tecla (tremida)
function filtrarApostasDebounced(){
    clearTimeout(window.__fa2)
    window.__fa2 = setTimeout(filtrarApostas, 220)
}
function clickPill(pill){
    document.querySelectorAll('#betStatusPills .bet-pill').forEach(p=>p.classList.remove('active'))
    pill.classList.add('active')
    const status = pill.dataset.status
    const sf = document.getElementById('statusFilter')
    if(sf){ sf.value = ['todos','ganha','perdida','pendente','anulada'].includes(status) ? status : 'todos' }
    filtrarApostas()
    if(status==='finalizadas') setTimeout(filtrarApostas, 220)
    if(typeof window.v160UpdateFinBadge==='function') setTimeout(window.v160UpdateFinBadge, 300)
}
// Selects/checkboxes do filtro: aplica via mesmo debounce (evita execução dupla)
// Multi-select casas
function toggleBetFiDrop(id){
    const drop=document.getElementById(id);if(!drop) return
    const isOpen=drop.classList.contains("open")
    document.querySelectorAll(".bet-fi-multi-drop.open").forEach(d=>d.classList.remove("open"))
    if(!isOpen) drop.classList.add("open")
}
function filtrarBetFiDrop(input,dropId){
    const q=input.value.toLowerCase()
    document.querySelectorAll(`#${dropId} .bet-fi-multi-item:not(:first-child)`).forEach(item=>{
        item.style.display=item.innerText.toLowerCase().includes(q)?"":"none"
    })
}
function toggleTodosBetFi(cb,dropId){
    const drop=document.getElementById(dropId);if(!drop) return
    drop.querySelectorAll("input[type=checkbox]:not([value=__todos])").forEach(c=>{ c.checked=false })
    cb.checked=true
    atualizarLabelCasas();filtrarApostas()
}
function onCasaCheck(){
    const todosChk=document.querySelector("#casasDrop input[value=__todos]");if(todosChk) todosChk.checked=false
    const checked=Array.from(document.querySelectorAll("#casasDrop input[type=checkbox]:not([value=__todos]):checked"))
    if(!checked.length&&todosChk) todosChk.checked=true
    atualizarLabelCasas();filtrarApostas()
}
function atualizarLabelCasas(){
    const label=document.getElementById("casasDropLabel");if(!label) return
    const checked=Array.from(document.querySelectorAll("#casasDrop input[type=checkbox]:not([value=__todos]):checked"))
    label.textContent=checked.length===0?"Todas as casas":checked.length===1?checked[0].value:checked.length+" casas"
}
// Fechar dropdown ao clicar fora
// Chart init — labels/valores defined by inline script in index.html
window.apostasPreview = window.apostasPreview || []

document.addEventListener("paste", function(e){
    let imagens = [], total = 0
    for(let item of e.clipboardData.items){
        if(item.type.includes("image")){
            total++
            let reader = new FileReader()
            reader.onload = ev => { imagens.push(ev.target.result); if(imagens.length === total) enviar(imagens) }
            const file = item.getAsFile()
            if(file) reader.readAsDataURL(file)
            else total--
        }
    }
})

function enviar(imgs){
    const loading = document.getElementById("loading")
    if(loading){ loading.style.display="block"; loading.textContent="Processando OCR..." }
    fetch("/colar", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({images:imgs}) })
    .then(async r=>{
        const txt = await r.text()
        try { return JSON.parse(txt) }
        catch(e){ console.error("Resposta não JSON do /colar:", txt); return {ok:false, erro:"Resposta inválida do servidor", resultados:[]} }
    })
    .then(d=>{
        console.log("RETORNO /colar:", d)
        if(!d.job_id){ // fallback: resposta direta (compatibilidade)
            window.apostasPreview = Array.isArray(d) ? d : (d.resultados || [])
            if(typeof window.renderPreview === "function") window.renderPreview()
            else console.error("renderPreview não existe")
            if(loading) loading.style.display="none"
            return
        }
        let dots = 0
        const poll = setInterval(async ()=>{
            dots = (dots + 1) % 4
            if(loading) loading.textContent = "Processando OCR" + ".".repeat(dots + 1)
            try {
                const r2 = await fetch(`/colar/status/${d.job_id}`, {cache:"no-store"})
                const job = await r2.json()
                if(job.status === "done" || job.status === "error"){
                    clearInterval(poll)
                    if(loading) loading.style.display="none"
                    window.apostasPreview = Array.isArray(job.resultados) ? job.resultados : []
                    if(typeof window.renderPreview === "function") window.renderPreview()
                    if(job.status === "error") console.warn("OCR erro:", job.erro)
                }
            } catch(e){ clearInterval(poll); if(loading) loading.style.display="none" }
        }, 200)
        if(d.ok === false && d.erro) console.warn("OCR retornou aviso:", d.erro)
    })
    .catch(err=>{ console.error("Erro fetch /colar:", err); if(loading) loading.style.display="none" })
}

function v106ToDatetimeLocal(value){
    if(!value) return ""
    try{
        const d = new Date(value); if(isNaN(d.getTime())) return ""
        const pad = n => String(n).padStart(2,"0")
        return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
    }catch(e){ return "" }
}

let editId = null
function abrirEditar(btn){
    const tr = btn.closest("tr")
    editId = btn.dataset.id || tr?.dataset.id
    document.getElementById("editAposta").value = tr.querySelector(".aposta-cell").innerText
    document.getElementById("editCasa").value = tr.querySelector(".casa-cell").innerText
    document.getElementById("editEsporte").value = tr.querySelector(".esporte-cell").innerText
    document.getElementById("editJogo").value = tr.querySelector(".jogo-cell").innerText
    if(document.getElementById("editMercado") && tr.querySelector(".mercado-cell")) document.getElementById("editMercado").value = tr.querySelector(".mercado-cell").innerText
    if(document.getElementById("editSelecao") && tr.querySelector(".selecao-cell")) document.getElementById("editSelecao").value = tr.querySelector(".selecao-cell").innerText
    if(document.getElementById("editLinha") && tr.querySelector(".linha-cell")) document.getElementById("editLinha").value = tr.querySelector(".linha-cell").innerText
    if(document.getElementById("editPeriodo") && tr.querySelector(".periodo-cell")) document.getElementById("editPeriodo").value = tr.querySelector(".periodo-cell").innerText
    document.getElementById("editOdd").value = tr.querySelector(".odd-cell").innerText
    document.getElementById("editValor").value = tr.querySelector(".valor-cell").innerText
    document.getElementById("editEstado").value = btn.dataset.estado
    const sj = document.getElementById("editStatusJogoManual"); if(sj) sj.value = btn.dataset.statusJogo || ""
    const horarioInput = document.getElementById("editHorarioJogo")
    if(horarioInput){
        const horarioExistente = v106ToDatetimeLocal(tr.dataset.horario || btn.dataset.horario || "")
        if(horarioExistente){
            horarioInput.value = horarioExistente
        } else {
            const now = new Date()
            const y = now.getFullYear()
            const m = String(now.getMonth()+1).padStart(2,"0")
            horarioInput.value = `${y}-${m}-01T00:00`
        }
    }
    document.getElementById("editModal").style.display="flex"
    if(typeof window.gameAutocompleteAttach==="function") window.gameAutocompleteAttach()
}
function fecharModal(){ document.getElementById("editModal").style.display="none" }
function _estaEditando(){ const m=document.getElementById("editModal");return !!(m&&m.style.display==="flex") }
function salvarEdicao(){
    const payload = {
        id: editId,
        aposta: document.getElementById("editAposta").value,
        casa: document.getElementById("editCasa").value,
        esporte: document.getElementById("editEsporte").value,
        jogo: document.getElementById("editJogo").value,
        mercado: document.getElementById("editMercado") ? document.getElementById("editMercado").value : "",
        selecao: document.getElementById("editSelecao") ? document.getElementById("editSelecao").value : "",
        linha: document.getElementById("editLinha") ? document.getElementById("editLinha").value : "",
        periodo: document.getElementById("editPeriodo") ? document.getElementById("editPeriodo").value : "",
        odd: document.getElementById("editOdd").value,
        valor: document.getElementById("editValor").value,
        estado: document.getElementById("editEstado").value,
        horario_jogo: document.getElementById("editHorarioJogo")?.value || "",
        status_jogo_manual: document.getElementById("editStatusJogoManual")?.value || ""
    }
    fetch("/editar_ajax", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload) })
    .then(()=>location.reload())
}

// v62
function toggleUserMenu(ev){
    if(ev) ev.stopPropagation()
    const menu = document.getElementById("sidebarUserMenu")
    if(menu) menu.classList.toggle("open")
}
// v63
window.v63FeedKnownIds = window.v63FeedKnownIds || new Set()
window.v63FeedPrimed = window.v63FeedPrimed || false
function v63ShowNewBetAlert(){
    const badge = document.getElementById("feedNotifyBadge"), toast = document.getElementById("feedToastNova"), panel = document.querySelector(".chart-panel")
    if(badge){ badge.style.display="inline-flex"; badge.classList.add("blink") }
    if(toast){ toast.style.display="inline-flex"; toast.classList.add("blink") }
    if(panel) panel.classList.add("feed-has-new")
}
function v63ClearNewBetAlert(){
    const badge = document.getElementById("feedNotifyBadge"), toast = document.getElementById("feedToastNova"), panel = document.querySelector(".chart-panel")
    if(badge){ badge.style.display="none"; badge.classList.remove("blink") }
    if(toast){ toast.style.display="none"; toast.classList.remove("blink") }
    if(panel) panel.classList.remove("feed-has-new")
}
window.carregarFeedApostas = function(force=false){
    const div = document.getElementById("feed-apostas"); if(!div) return
    if(force || div.dataset.loaded !== "1") div.innerHTML = `<div class="feed-empty">Carregando últimas apostas...</div>`
    fetch("/ultimas_apostas?_=" + Date.now(), {cache:"no-store"})
    .then(r=>r.json())
    .then(d=>{
        div.dataset.loaded = "1"
        if(!Array.isArray(d) || d.length === 0){ div.innerHTML = `<div class="feed-empty">Nenhuma aposta pública encontrada.</div>`; return }
        const incomingIds = d.map(a=>String(a.id || `${a.jogo}-${a.aposta}-${a.odd}-${a.valor}-${a.data}`))
        const newestId = incomingIds[0]
        const hasNew = window.v63FeedPrimed && newestId && !window.v63FeedKnownIds.has(newestId)
        window.v63FeedKnownIds = new Set(incomingIds); window.v63FeedPrimed = true
        if(hasNew) v63ShowNewBetAlert()
        div.innerHTML = ""
        d.forEach((a,idx)=>{
            const id = String(a.id || `${a.jogo}-${a.aposta}-${a.odd}-${a.valor}-${a.data}`)
            const payload = encodeURIComponent(JSON.stringify(a)), isNew = hasNew && idx === 0
            div.innerHTML += `<div class="feed-card ${isNew?"feed-new":""}" data-id="${id}"><div class="feed-card-main"><div class="feed-title-line"><strong>${a.jogo||"Jogo não informado"}</strong>${isNew?'<span class="novo-badge">NOVO</span>':''}</div><span>${a.aposta||""}</span><div class="feed-meta">${a.casa||"Casa"} • ${a.esporte||"Esporte"} • Odd ${a.odd||"-"} • R$ ${a.valor||"-"} ${a.horario_jogo?"• Jogo: "+a.horario_jogo:""} ${a.data?"• "+a.data:""}</div></div><button type="button" class="copy-bet-btn" data-payload="${payload}" onclick="copiarApostaComunidade(this)">Copiar</button></div>`
        })
    })
    .catch(()=>{ if(div.dataset.loaded !== "1") div.innerHTML = `<div class="feed-empty">Erro ao carregar últimas apostas.</div>` })
}
// v72
window.v72DirtyMetrics = null
function v72Money(v){ return "R$ " + Number(v||0).toFixed(2) }
function v72UpdateMetrics(m){
    if(!m) return
    const map = {
        "metric-banca": v72Money(m.banca_atual),
        "metric-valor-aberto": v72Money(m.valor_em_aberto !== undefined ? m.valor_em_aberto : 0),
        "metric-roi": Number(m.roi||0).toFixed(2)+"%",
        "metric-taxa": Number(m.taxa||0).toFixed(2)+"%",
        "metric-total": m.total,
        "metric-pendentes": m.pendentes
    }
    Object.entries(map).forEach(([id,val])=>{ const el=document.getElementById(id); if(el) el.innerText=val })
    const lucro = document.getElementById("metric-lucro")
    if(lucro){ lucro.innerText=v72Money(m.lucro_total); lucro.classList.remove("green-text","red-text"); lucro.classList.add(Number(m.lucro_total||0)>=0?"green-text":"red-text") }
}
function v72BadgeStatus(estado){
    if(estado==="ganha") return '<span class="badge green">Ganha</span>'
    if(estado==="perdida") return '<span class="badge red">Perdida</span>'
    if(estado==="anulada") return '<span class="badge gray">Anulada</span>'
    return '<span class="badge yellow">Pendente</span>'
}
function v72UpdateRow(tr, b){
    if(!tr||!b) return
    const statusCell=tr.querySelector(".status-cell"); if(statusCell) statusCell.innerHTML=v72BadgeStatus(b.estado||"")
    const lucroCell=tr.children[8]||tr.querySelector(".lucro-cell")
    if(lucroCell){ const lucro=Number(b.lucro||0); lucroCell.innerText=v72Money(lucro); lucroCell.classList.remove("green-text","red-text"); if(lucro>0) lucroCell.classList.add("green-text"); if(lucro<0) lucroCell.classList.add("red-text") }
}
function v72Toast(msg, type="ok"){
    let t=document.getElementById("v72Toast")
    if(!t){ t=document.createElement("div"); t.id="v72Toast"; document.body.appendChild(t) }
    t.className="v72-toast "+type; t.innerText=msg; t.classList.add("show")
    setTimeout(()=>t.classList.remove("show"), 1800)
}
function v72SaveScroll(){ sessionStorage.setItem("restoreScrollY", String(window.scrollY||0)) }
function v72RestoreScroll(){
    const y=sessionStorage.getItem("restoreScrollY")
    if(y!==null){ sessionStorage.removeItem("restoreScrollY"); setTimeout(()=>window.scrollTo(0,Number(y||0)),0) }
}
window.addEventListener("beforeunload", v72SaveScroll)
document.addEventListener("submit", function(e){
    const form=e.target; if(!form||!form.matches(".manual-form")) return
    e.preventDefault()
    const fd=new FormData(form), btn=form.querySelector('button[type="submit"]')
    if(btn){ btn.disabled=true; btn.dataset.oldText=btn.innerText; btn.innerText="Salvando..." }
    fetch("/adicionar_ajax"+window._mesQS("?"), { method:"POST", body:fd, cache:"no-store" })
    .then(r=>r.json()).then(d=>{
        if(!d.ok) throw new Error(d.erro||"erro")
        location.reload()
    })
    .catch(e=>{ if(btn){ btn.disabled=false; btn.innerText=btn.dataset.oldText||"Adicionar" }; v72Toast(e.message||"Erro ao adicionar aposta","err") })
}, true)
document.addEventListener("submit", function(){ v72SaveScroll() }, true)

// v72-copy-private
window.v72OriginalCopiarApostaComunidade = window.copiarApostaComunidade
window.copiarApostaComunidade = function(btn){
    if(typeof window.v72OriginalCopiarApostaComunidade === "function") window.v72OriginalCopiarApostaComunidade(btn)
    const hidden=document.getElementById("copiadaComunidade"); if(hidden) hidden.value="1"
    const src=document.getElementById("sourceOriginalId")
    try { const data=JSON.parse(decodeURIComponent(btn.dataset.payload||"{}")); if(src) src.value=data.source_original_id||data.id||""; const hj=document.getElementById("horarioJogo"); if(hj) hj.value=data.horario_jogo||"" } catch(e) {}
    v72Toast("Aposta copiada como privada")
}

// v75
window.apostasPreview = window.apostasPreview || []
window.escapeHtmlPreview = window.escapeHtmlPreview || function(value){
    return String(value??"").replaceAll("&","&amp;").replaceAll('"',"&quot;").replaceAll("<","&lt;").replaceAll(">","&gt;")
}
function _ocrLimparDisplay(txt){
    return String(txt||"")
        .replace(/[•·→←↑↓★☆♦♣♠♥©®™°]/g,"")
        .replace(/\b(odd|data|date|hora|vator|vtr|ref)\s*[:.]?\s*[\d/]*/gi,"")
        .replace(/\b\d{2}\/\d{2}(\/\d{2,4})?\b/g,"")
        .replace(/\b\d{2}:\d{2}(:\d{2})?\b/g,"")
        .replace(/\s{2,}/g," ")
        .replace(/^[\s\-./|:]+|[\s\-./|:]+$/g,"")
}
window.renderPreview = function(){
    const div=document.getElementById("preview-area"), salvar=document.getElementById("salvar-preview")
    if(!div) return
    div.innerHTML = ""
    if(!Array.isArray(window.apostasPreview)||window.apostasPreview.length===0){
        div.innerHTML=`<div class="preview-empty">Nenhuma aposta lida. Tente colar o print novamente.</div>`
        if(salvar) salvar.style.display="none"; return
    }
    window.apostasPreview.forEach((a,i)=>{
        const odd=String(a.odd||"").replace(",",".")
        let valor=String(a.valor||"").replace(",",".")
        if(odd&&valor&&parseFloat(odd)>1&&Math.abs(parseFloat(odd)-parseFloat(valor))<0.0001) valor=""
        const jogoDisp=_ocrLimparDisplay(window.semBarra(a.jogo||""))
        const apostaDisp=_ocrLimparDisplay(window.semBarra(a.aposta||""))
        div.innerHTML+=`<div class="preview-card preview-card-client"><input id="c${i}" value="${window.escapeHtmlPreview(a.casa||'')}" placeholder="Casa"><input id="e${i}" value="${window.escapeHtmlPreview(a.esporte||'')}" placeholder="Esporte"><input id="j${i}" value="${window.escapeHtmlPreview(jogoDisp)}" placeholder="Jogo"><input id="a${i}" value="${window.escapeHtmlPreview(apostaDisp)}" placeholder="Aposta"><input id="o${i}" value="${window.escapeHtmlPreview(odd||'')}" placeholder="Odd"><input id="v${i}" value="${window.escapeHtmlPreview(valor||'')}" placeholder="Valor"><input type="hidden" id="m${i}" value="${window.escapeHtmlPreview(a.mercado||'')}"><input type="hidden" id="s${i}" value="${window.escapeHtmlPreview(a.selecao||'')}"><input type="hidden" id="l${i}" value="${window.escapeHtmlPreview(a.linha||'')}"><input type="hidden" id="p${i}" value="${window.escapeHtmlPreview(a.periodo||'')}"></div>`
    })
    if(salvar){ salvar.style.display="block"; salvar.disabled=false; salvar.innerText="Salvar Apostas do Preview" }
    div.scrollIntoView({behavior:"smooth",block:"center"})
    if(typeof window.gameAutocompleteAttach === "function") window.gameAutocompleteAttach()
}

function _inserirBetOtimista(apostas){
    const tbody=document.querySelector("#betsMainTable tbody")
    if(!tbody) return []
    const agora=new Date()
    const pad=n=>String(n).padStart(2,"0")
    const dataStr=`${pad(agora.getDate())}/${pad(agora.getMonth()+1)}/${agora.getFullYear()} ${pad(agora.getHours())}:${pad(agora.getMinutes())}`
    const esc=v=>String(v||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
    const nCols=(document.querySelectorAll("#betsMainTable thead th")||[]).length||11
    const inseridos=[]
    for(const a of apostas){
        const tr=document.createElement("tr")
        tr.className="bet-row"
        tr.dataset.data=dataStr
        tr.dataset.aoVivo="0"
        tr.dataset.horario=""
        tr.innerHTML=`
            <td class="data-cell"><span class="game-date-main">${dataStr.split(" ")[0]}</span></td>
            <td class="casa-cell">${esc(a.casa)}</td>
            <td class="esporte-cell">${esc(a.esporte)}</td>
            <td class="jogo-cell">${esc(a.jogo)}</td>
            <td class="aposta-cell">${esc(a.aposta)}</td>
            <td class="odd-cell">${parseFloat(a.odd)||""}</td>
            <td class="valor-cell">${(parseFloat(a.valor)||0).toFixed(2)}</td>
            <td class="status-cell"><span class="badge yellow">Pendente</span></td>
            <td>R$ 0.00</td>
            <td class="api-cell"></td>
            <td class="actions"><span style="opacity:0.4;font-size:0.8em">salvando…</span></td>`
        tbody.insertBefore(tr,tbody.firstChild)
        inseridos.push(tr)
    }
    return inseridos
}

// handler do botao salvar-preview
document.addEventListener("DOMContentLoaded", function(){
    const btn = document.getElementById("salvar-preview")
    if(!btn) return
    btn.addEventListener("click", function(){
        if(btn.disabled) return
        const n = Array.isArray(window.apostasPreview) ? window.apostasPreview.length : 0
        if(!n){ if(typeof v72Toast==="function") v72Toast("Nenhuma aposta para salvar","err"); return }
        const apostas = []
        for(let i=0; i<n; i++){
            const orig = window.apostasPreview[i] || {}
            const jogoEl = document.getElementById("j"+i)
            const horarioIso = jogoEl?.dataset.horario || orig.horario_jogo_iso || ""
            const statusJogo = jogoEl?.dataset.statusJogo || orig.status_jogo || ""
            const aoVivo = jogoEl?.dataset.aoVivo === "1" || orig.ao_vivo || false
            apostas.push({
                casa: document.getElementById("c"+i)?.value ?? orig.casa ?? "",
                esporte: document.getElementById("e"+i)?.value ?? orig.esporte ?? "",
                jogo: jogoEl?.value ?? orig.jogo ?? "",
                aposta: document.getElementById("a"+i)?.value ?? orig.aposta ?? "",
                odd: document.getElementById("o"+i)?.value ?? String(orig.odd ?? ""),
                valor: document.getElementById("v"+i)?.value ?? String(orig.valor ?? ""),
                mercado: document.getElementById("m"+i)?.value ?? orig.mercado ?? "",
                selecao: document.getElementById("s"+i)?.value ?? orig.selecao ?? "",
                linha: document.getElementById("l"+i)?.value ?? orig.linha ?? "",
                periodo: document.getElementById("p"+i)?.value ?? orig.periodo ?? "",
                texto_bruto: orig.texto_bruto ?? "",
                texto_interpretado: orig.texto_interpretado ?? "",
                itens_multipla: orig.itens_multipla ?? {},
                itens_multipla_detalhados: orig.itens_multipla_detalhados ?? [],
                horario_jogo_iso: horarioIso,
                horario_jogo: statusJogo,
                status_jogo: statusJogo,
                ao_vivo: aoVivo
            })
        }
        btn.disabled = true; btn.innerText = "Salvando..."

        // Inserção otimista: bet aparece na tabela imediatamente
        const previewDiv=document.getElementById("preview-area")
        const salvarDiv=document.getElementById("salvar-preview")
        const previaSalva=window.apostasPreview.slice()
        const inseridos=_inserirBetOtimista(apostas)
        if(previewDiv) previewDiv.innerHTML=""
        if(salvarDiv) salvarDiv.style.display="none"

        fetch("/salvar_preview"+window._mesQS("?"), {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({apostas: apostas})
        })
        .then(r=>r.json())
        .then(d=>{
            if(!d.ok) throw new Error(d.erro || "Erro ao salvar")
            // Atualiza botões de ação com IDs reais
            const bets=d.bets||[]
            inseridos.forEach((tr,idx)=>{
                const b=bets[idx]
                if(b&&b.id){
                    tr.dataset.id=b.id
                    const ac=tr.querySelector(".actions")
                    if(ac) ac.innerHTML=`<a href="/resultado/${b.id}/ganha"><button class="green">✔</button></a><a href="/resultado/${b.id}/perdida"><button class="red">✖</button></a><a href="/resultado/${b.id}/anulada"><button class="gray">↺</button></a><button class="blue" onclick="abrirEditar(this)" data-estado="" data-status-jogo="" data-horario="">✎</button><a href="/remover/${b.id}"><button class="dark">🗑</button></a>`
                }
            })
            btn.disabled=false; btn.innerText="Salvar Apostas do Preview"
            if(typeof v72Toast==="function") v72Toast(`${inseridos.length} aposta${inseridos.length!==1?"s":""} salva${inseridos.length!==1?"s":""}!`,"ok")
        })
        .catch(e=>{
            inseridos.forEach(tr=>tr.remove())
            window.apostasPreview=previaSalva
            if(previewDiv) previewDiv.innerHTML=""
            if(typeof window.renderPreview==="function") window.renderPreview()
            btn.disabled=false; btn.innerText="Salvar Apostas do Preview"
            if(typeof v72Toast==="function") v72Toast(e.message||"Erro ao salvar","err")
        })
    })
})

// v76
function v76Escape(value){ return String(value??"").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;") }
function v76Money(value){ return "R$ "+Number(value||0).toFixed(2) }
function v76StatusBadge(estado){
    if(estado==="ganha") return '<span class="badge green">Ganha</span>'
    if(estado==="perdida") return '<span class="badge red">Perdida</span>'
    if(estado==="anulada") return '<span class="badge gray">Anulada</span>'
    return '<span class="badge yellow">Pendente</span>'
}
function v76AddBetToTable(b){
    const tbody=document.querySelector(".table-panel tbody"); if(!tbody||!b) return
    const id=b.id||""; if(id&&document.querySelector(`tr[data-id="${CSS.escape(id)}"]`)) return
    const lucro=Number(b.lucro||0), tr=document.createElement("tr")
    tr.dataset.id=id; tr.dataset.jogo=b.jogo||""; tr.dataset.horario=b.horario_jogo_iso||""
    tr.dataset.statusJogo=b.status_jogo||b.horario_jogo||""; tr.dataset.statusClass=b.ao_vivo?"live":""
    tr.classList.add("v76-new-row")
    tr.innerHTML=`<td>${v76Escape(b.data||"")}</td><td class="casa-cell">${v76Escape(b.casa||"")}</td><td class="esporte-cell">${v76Escape(b.esporte||"")}</td><td class="jogo-cell">${v76Escape(b.jogo||"")}</td><td class="aposta-cell">${v76Escape(b.aposta_display||b.aposta||"")}</td><td class="odd-cell">${v76Escape(b.odd||"")}</td><td class="valor-cell">${v76Escape(b.valor||"")}</td><td class="status-cell">${v76StatusBadge(b.estado||"")}</td><td class="${lucro>0?"green-text":lucro<0?"red-text":""}">${v76Money(lucro)}</td><td class="api-cell">${v76Escape(b.api_status||"")}</td><td class="actions"><a href="/resultado/${id}/ganha"><button class="green">✓</button></a><a href="/resultado/${id}/perdida"><button class="red">✕</button></a><a href="/resultado/${id}/anulada"><button class="gray">–</button></a><button class="blue" onclick="abrirEditar(this)" data-id="${id}" data-estado="${v76Escape(b.estado||'')}">✎</button><a href="/remover/${id}" onclick="return confirm('Apagar esta aposta?')" class="delete-bet-link"><button class="dark delete-bet-btn" title="Apagar aposta">🗑</button></a></td>`
    tbody.prepend(tr); setTimeout(()=>tr.classList.remove("v76-new-row"), 2200)
}
function v76AddSavedPreviewBets(data){ if(!data||!Array.isArray(data.bets)) return; data.bets.forEach(v76AddBetToTable) }

// v85
function atualizarHorariosEspn(){
    if(typeof v72Toast==="function") v72Toast("Atualizando horários...")
    fetch("/atualizar_horarios_espn", {method:"POST",cache:"no-store"})
    .then(r=>r.json()).then(d=>{ if(typeof v72Toast==="function") v72Toast(`${d.atualizadas||0} horário(s) atualizado(s)`); setTimeout(()=>location.reload(),600) })
    .catch(()=>{ if(typeof v72Toast==="function") v72Toast("Erro ao atualizar horários","err"); else alert("Erro ao atualizar horários") })
}

// v107
(function(){
    let timer=null
    let _jogosCache=null, _jogosCacheTs=0, _jogosPromise=null
    const _JOGOS_TTL=5*60*1000
    function esc(v){ return String(v??"").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;") }
    function norm(v){ return String(v||"").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g,"") }
    function queryNorm(q){ const aliases={"real":"real madrid","psg":"paris saint germain","paris":"paris saint germain","bayern":"bayern munich","bayern munique":"bayern munich","bayern de munique":"bayern munich","flumi":"fluminense","flu":"fluminense","cortinas":"corinthians","shaktar":"shakhtar donetsk"}; const s=norm(q).trim(); return aliases[s]||s }
    function tokensBusca(q){ return queryNorm(q).split(/[^a-z0-9]+/).filter(t=>t.length>=3&&!["jogo","time","times","casa","odd","valor","aposta","futebol","basquete","club"].includes(t)) }
    function scoreLocal(q,jogo){ const qn=queryNorm(q),jn=norm(jogo),toks=tokensBusca(q); if(!qn) return 1; let score=0; if(jn.includes(qn)) score+=1000; if(toks.length&&toks.every(t=>jn.includes(t))) score+=600; toks.forEach(t=>{if(jn.includes(t)) score+=70}); if(toks.length>=2&&!toks.every(t=>jn.includes(t))) score-=500; return score }
    function isGameInput(input){ if(!input||input.tagName!=="INPUT") return false; const id=input.id||"",name=(input.name||"").toLowerCase(),ph=(input.getAttribute("placeholder")||"").toLowerCase(); return name==="jogo"||name.includes("jogo")||ph.includes("jogo")||ph.includes("times")||/^j\d+$/.test(id) }
    function getSport(input){ try{ const id=input.id||"",n=id.match(/^j(\d+)$/)?.[1]; if(n!==undefined){const esp=document.getElementById(`e${n}`);if(esp) return esp.value||""} const form=input.closest("form");if(form){const esp=form.querySelector('input[name="esporte"]');if(esp) return esp.value||""} const card=input.closest(".preview-card");if(card){const esp=card.querySelector('input[id^="e"]');if(esp) return esp.value||""} }catch(e){} return "" }
    function wrapInput(input){ if(input.parentElement&&input.parentElement.classList.contains("game-autocomplete-wrap")) return input.parentElement; const wrap=document.createElement("div");wrap.className="game-autocomplete-wrap";input.parentNode.insertBefore(wrap,input);wrap.appendChild(input);return wrap }
    function box(input){ const wrap=wrapInput(input);let b=wrap.querySelector(".game-autocomplete-dropdown");if(!b){b=document.createElement("div");b.className="game-autocomplete-dropdown";wrap.appendChild(b)}return b }
    function closeAll(){ document.querySelectorAll(".game-autocomplete-dropdown.open").forEach(b=>b.classList.remove("open")) }
    function show(input,html){ const b=box(input);b.innerHTML=html;b.classList.add("open") }
    function fmt(horario,status){ const src=horario||status||"";let m=String(src).match(/(\d{2})\/(\d{2})\/(\d{4})\s+(\d{2}):(\d{2})/);if(m) return{data:`${m[1]}/${m[2]}`,hora:`${m[4]}:${m[5]}`};m=String(src).match(/(\d{2})\/(\d{2})\s+(\d{1,2}):(\d{2})/);if(m) return{data:`${m[1]}/${m[2]}`,hora:`${String(m[3]).padStart(2,"0")}:${m[4]}`};if(String(status||"").toLowerCase().includes("ao vivo")) return{data:"AO VIVO",hora:"LIVE"};return{data:"DATA",hora:status||""} }
    async function carregarJogos(){
        if(_jogosCache&&(Date.now()-_jogosCacheTs)<_JOGOS_TTL) return _jogosCache
        if(!_jogosPromise){
            _jogosPromise=fetch("/api/buscar_jogos",{cache:"no-store"})
                .then(r=>r.json())
                .then(data=>{ _jogosCache=data.jogos||[];_jogosCacheTs=Date.now();_jogosPromise=null;return _jogosCache })
                .catch(()=>{ _jogosCache=_jogosCache||[];_jogosPromise=null;return _jogosCache })
        }
        return _jogosPromise
    }
    function renderOpcoes(input,jogos){
        show(input,jogos.slice(0,12).map(j=>{const status=j.status_jogo||j.horario_jogo||"",p=fmt(j.horario_jogo,status),liga=j.liga_nome||j.league||"";return`<button type="button" class="game-autocomplete-option" data-jogo="${esc(j.jogo)}" data-horario="${esc(j.horario_jogo_iso||"")}" data-status="${esc(status)}" data-live="${j.ao_vivo?"1":"0"}"><span class="game-autocomplete-date"><small>${esc(p.data)}</small><strong>${esc(p.hora)}</strong></span><span class="game-autocomplete-main"><small>${esc(liga)}</small><strong>${esc(j.jogo)}</strong></span></button>`}).join(""))
        box(input).querySelectorAll(".game-autocomplete-option").forEach(btn=>{
            btn.addEventListener("mousedown",e=>e.preventDefault())
            btn.onclick=()=>{
                input.value=btn.dataset.jogo||input.value
                input.dataset.horario=btn.dataset.horario||""
                input.dataset.statusJogo=btn.dataset.status||""
                input.dataset.aoVivo=btn.dataset.live||"0"
                input.dataset.partidaSelecionada="1"
                const iso=input.dataset.horario||""
                if(input.id==="editJogo"){
                    // Modal de editar: atualiza o horário e o status do PRÓPRIO modal
                    const eh=document.getElementById("editHorarioJogo")
                    if(eh && typeof v106ToDatetimeLocal==="function"){ const dl=v106ToDatetimeLocal(iso); if(dl) eh.value=dl }
                    const esj=document.getElementById("editStatusJogoManual"); if(esj) esj.value=input.dataset.statusJogo||""
                } else if(input.name==="jogo"){
                    const hidden=document.getElementById("horarioJogo"); if(hidden) hidden.value=iso
                }
                closeAll(); if(typeof v72Toast==="function") v72Toast("Partida selecionada")
            }
        })
    }
    async function buscar(input){
        if(!isGameInput(input)) return
        const q=(input.value||"").trim()
        if(q.length<2){ show(input,`<div class="game-autocomplete-empty">Digite pelo menos 2 letras.</div>`);return }
        if(!_jogosCache) show(input,`<div class="game-autocomplete-loading">Buscando jogos...</div>`)
        try{
            let todos=await carregarJogos()
            const esporteRaw=getSport(input)
            let jogos=todos
            if(esporteRaw){ const en=norm(esporteRaw);if(en.includes("basquete")||en.includes("basket")) jogos=jogos.filter(j=>j.esporte==="Basquete");else if(en.includes("futebol")||en.includes("soccer")) jogos=jogos.filter(j=>j.esporte==="Futebol") }
            let resultado=jogos.map(j=>({...j,_localScore:scoreLocal(q,j.jogo||"")})).filter(j=>j._localScore>0).sort((a,b)=>(b._localScore-a._localScore)||String(a.horario_jogo_iso||"").localeCompare(String(b.horario_jogo_iso||"")))
            if(resultado.length){ renderOpcoes(input,resultado);return }
            // fallback: busca no servidor com o query
            const r=await fetch(`/api/buscar_jogos?q=${encodeURIComponent(q)}&esporte=${encodeURIComponent(esporteRaw)}`,{cache:"no-store"})
            const data=await r.json();resultado=data.jogos||[]
            if(resultado.length){
                if(_jogosCache){ const ids=new Set(_jogosCache.map(j=>j.id));resultado.forEach(j=>{if(j.id&&!ids.has(j.id)) _jogosCache.push(j)}) }
                renderOpcoes(input,resultado)
            } else { show(input,`<div class="game-autocomplete-empty">Nenhum jogo encontrado.</div>`) }
        }catch(e){ console.error("Autocomplete jogos erro:",e);show(input,`<div class="game-autocomplete-empty">Erro ao buscar jogos.</div>`) }
    }
    function attach(){ document.querySelectorAll("input").forEach(input=>{ if(!isGameInput(input)||input.dataset.gameAutocompleteReady==="1") return; input.dataset.gameAutocompleteReady="1";wrapInput(input); input.addEventListener("focus",()=>buscar(input)); input.addEventListener("input",()=>{clearTimeout(timer);timer=setTimeout(()=>buscar(input),150)}) }) }
    document.addEventListener("click",e=>{if(e.target.closest(".game-autocomplete-wrap")) return;closeAll()})
    document.addEventListener("keydown",e=>{if(e.key==="Escape") closeAll()})
    document.addEventListener("submit",function(e){ const form=e.target;if(!form||form.id!=="manualForm") return; const aposta=form.querySelector('input[name="aposta"]'),jogo=form.querySelector('input[name="jogo"]');if(aposta&&jogo&&!aposta.value.trim()) aposta.value=jogo.value.trim()||"Aposta manual" },true)
    document.addEventListener("DOMContentLoaded",()=>{ attach();carregarJogos().catch(()=>{}) })
    window.gameAutocompleteAttach=attach
    window.recarregarJogosCache=()=>{ _jogosCacheTs=0;return carregarJogos() }
})();

// v131
function abrirModalBancaInicial(){ const modal=document.getElementById("bancaInicialModal");if(modal) modal.style.display="flex" }
function fecharModalBancaInicial(){ const modal=document.getElementById("bancaInicialModal");if(modal) modal.style.display="none" }

// v132 — modais da banca inicial (cards/valores agora vêm prontos do servidor via metricas())
(function(){
    window.abrirModalBancaInicial=function(){ const modal=document.getElementById("bancaInicialModal");if(modal) modal.style.display="flex" }
    window.fecharModalBancaInicial=function(){ const modal=document.getElementById("bancaInicialModal");if(modal) modal.style.display="none" }
})();

// v135
(function(){
    function money(v){ return "R$ "+Number(v||0).toFixed(2) }
    document.addEventListener("DOMContentLoaded",()=>{
        const modal=document.getElementById("bancaInicialModal")
        const form=modal?modal.querySelector('form[action="/configurar_banca_inicial"]'):null
        if(!form||form.dataset.v135Ready==="1") return
        form.dataset.v135Ready="1"
        form.addEventListener("submit",async function(e){
            e.preventDefault()
            const input=document.getElementById("bancaInicialInput"),valor=input?input.value:0
            try{
                const r=await fetch("/configurar_banca_inicial",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({banca_inicial:valor})})
                const data=await r.json()
                if(data&&data.ok){ const el=document.getElementById("metric-banca-inicial");if(el) el.textContent=money(data.banca_inicial||0); if(typeof fecharModalBancaInicial==="function") fecharModalBancaInicial(); if(typeof v72Toast==="function") v72Toast("Banca inicial salva") }
                else alert("Erro ao salvar banca inicial: "+(data.erro||"erro desconhecido"))
            }catch(err){ console.error(err);alert("Erro ao salvar banca inicial: "+(err.message||"erro desconhecido")) }
        })
    })
})();

// v136
(function(){
    let sortAsc=true,groupMode=false,collapsedGroups=new Set(),initializedCollapse=false
    function parseISO(v){ if(!v) return null;const d=new Date(v);return isNaN(d.getTime())?null:d }
    function parseBR(v){ const m=String(v||"").match(/(\d{2})\/(\d{2})\/(\d{4})\s+(\d{2}):(\d{2})/);if(!m) return null;return new Date(Number(m[3]),Number(m[2])-1,Number(m[1]),Number(m[4]),Number(m[5])) }
    function parseMoney(txt){ txt=String(txt||"").replace(/[^\d,.-]/g,"").trim();if(txt.includes(",")&&txt.includes(".")) txt=txt.replace(/\./g,"").replace(",",".");else if(txt.includes(",")) txt=txt.replace(",",".");const n=parseFloat(txt);return isNaN(n)?0:n }
    function money(v){ return "R$ "+Number(v||0).toFixed(2) }
    function cleanText(v){ return String(v||"").replace(/⏰|🏁|●/g,"").replace(/\bAo vivo\b/gi,"").replace(/\bFinalizado\b/gi,"").replace(/\bHoje\s+\d{1,2}:\d{2}\b/gi,"").replace(/\b\d{2}\/\d{2}\s+\d{1,2}:\d{2}\b/g,"").replace(/\b\d+\s+jogos\s*•?.*$/gi,"").replace(/\s{2,}/g," ").trim() }
    function col(label){ const ths=Array.from(document.querySelectorAll("table thead th")),target=String(label).toLowerCase();for(let i=0;i<ths.length;i++){const t=ths[i].innerText.trim().toLowerCase().replace(/\s+↑$/,"").replace(/\s+↓$/,"");if(t===target) return i}return -1 }
    function cell(row,i){ return row.children&&row.children[i]?row.children[i]:null }
    function iso(row){ return row.dataset.horarioJogoIso||row.dataset.horario||"" }
    function raw(row){ return row.dataset.statusJogo||row.dataset.horarioJogo||"" }
    function statusText(row){ const i=col("status");return(i>=0?row.children?.[i]?.innerText:row.querySelector(".status-badge")?.innerText||"").trim().toLowerCase() }
    function valor(row){ const i=col("valor");return parseMoney(i>=0?row.children?.[i]?.innerText:"") }
    function lucro(row){ const i=col("lucro");return parseMoney(i>=0?row.children?.[i]?.innerText:"") }
    function closed(row){ const s=statusText(row);return s.includes("ganha")||s.includes("green")||s.includes("perdida")||s.includes("red")||s.includes("anulada")||s.includes("void") }
    function game(row){ const c=row.querySelector(".jogo-cell")||cell(row,3);if(!c) return "";let name=row.dataset.jogo||"";if(!name){for(const n of Array.from(c.childNodes)){if(n.nodeType===Node.TEXT_NODE&&n.textContent.trim()){name=n.textContent.trim();break}}}if(!name) name=c.textContent||"";name=cleanText(name);row.dataset.jogo=name;c.replaceChildren(document.createTextNode(name));return name }
    function singleMatch(row){ const g=game(row).toLowerCase();if(!g||g==="múltipla"||g==="multipla") return false;return /\s(x|vs\.?|v\.?)\s/.test(g)&&(g.match(/\s\/\s/g)||[]).length===0 }
    function trueMulti(row){ const g=game(row).toLowerCase(),r=raw(row).toLowerCase();if(singleMatch(row)) return false;if(g==="múltipla"||g==="multipla") return true;if(r.includes("jogos")||r.includes("próximo")||r.includes("proximo")) return true;const bet=(cell(row,4)?.innerText||"").toLowerCase();return !singleMatch(row)&&bet.split("/").length>=4 }
    function dateObj(row){ return parseISO(iso(row))||parseBR(row.dataset.data||cell(row,0)?.innerText||"")||null }
    function dateLabel(row){ const d=parseISO(iso(row));if(d){const p=n=>String(n).padStart(2,"0");return`${p(d.getDate())}/${p(d.getMonth()+1)} ${p(d.getHours())}:${p(d.getMinutes())}`}const r=raw(row);if(r&&/\d{2}\/\d{2}/.test(r)) return r;return(row.dataset.data||cell(row,0)?.innerText||"-").split("\n")[0]||"-" }
    function dayKey(row){ const d=dateObj(row);if(!d) return "sem-data";const p=n=>String(n).padStart(2,"0");return`${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}` }
    function dayLabel(k){ if(k==="sem-data") return "Sem data";const[y,m,d]=k.split("-").map(Number);const dt=new Date(y,m-1,d);const today=new Date();today.setHours(0,0,0,0);const cmp=new Date(dt);cmp.setHours(0,0,0,0);const diff=Math.round((cmp-today)/86400000);const dd=String(dt.getDate()).padStart(2,"0"),mm=String(dt.getMonth()+1).padStart(2,"0");if(diff===0) return`Hoje — ${dd}/${mm}`;if(diff===1) return`Amanhã — ${dd}/${mm}`;if(diff===-1) return`Ontem — ${dd}/${mm}`;const dias=["Domingo","Segunda-feira","Terça-feira","Quarta-feira","Quinta-feira","Sexta-feira","Sábado"];return`${dias[dt.getDay()]} — ${dd}/${mm}/${dt.getFullYear()}` }
    function gStatus(row){ const r=String(raw(row)||"").toLowerCase();const d=parseISO(iso(row));if(trueMulti(row)) return["Múltipla","multi",30];if(d&&((Date.now()-d.getTime())/60000)>=130) return["Finalizado","finished",50];if(row.dataset.aoVivo==="1"||r.includes("ao vivo")||r.includes("live")) return["Ao vivo","live",0];if(r.includes("final")||r.includes("encerr")) return["Finalizado","finished",50];if(r.includes("em andamento")) return["Ao vivo","live",1];if(r.includes("sem horário")||r.includes("sem horario")) return["Sem horário","empty",40];if(r.includes("agendado")) return["Agendado","scheduled",4];if(d){const diff=(d.getTime()-Date.now())/60000;if(diff<-120) return["Finalizado","finished",50];if(diff<0) return["Ao vivo","live",1];if(diff<=60) return[`Falta ${Math.max(1,Math.floor(diff))}min`,"soon",2];if(d.toDateString()===new Date().toDateString()) return["Hoje","today",3];return["Futuro","scheduled",4]}return["Sem horário","empty",40] }
    function baseTime(row){ const d=dateObj(row);return d?d.getTime():9999999999999 }
    function cmp(a,b){ const ta=baseTime(a),tb=baseTime(b);return sortAsc?ta-tb:tb-ta }
    function renderLeft(row){ const c=cell(row,0);if(!c) return;const st=gStatus(row);const html=`<span class="game-date-main">${dateLabel(row)}</span><span class="game-date-status ${st[1]}">${st[0]}</span>`;if(c.dataset.v136!==html){c.classList.add("game-date-cell");c.innerHTML=html;c.dataset.v136=html} }
    function groupKey(row){ if(trueMulti(row)) return`__multi__:${row.dataset.id||Math.random()}`;return game(row).toLowerCase()||`__row__:${row.dataset.id||Math.random()}` }
    function rep(rows){ return rows.slice().sort(cmp)[0] }
    function clusterRows(rows){ const groups=new Map();for(const r of rows){const k=groupKey(r);if(!groups.has(k)) groups.set(k,[]);groups.get(k).push(r)}const gl=Array.from(groups.values()).map(rs=>{const r0=rep(rs);return{rs,t:baseTime(r0),day:dayKey(r0)}});gl.sort((a,b)=>sortAsc?(a.t-b.t):(b.t-a.t));gl.forEach(g=>g.rs.sort(cmp));return gl }
    function _subtotalVisivel(r){ return r.style.display!=="none" && !r.classList.contains("v149-historico-hidden") }
    function renderSubtotal(tr){ const rs=(tr._betRows||[]).filter(_subtotalVisivel);if(rs.length<2){tr.style.display="none";return}tr.style.display="";const s=summary(rs);const cor=s.luc>0?"#37d67a":s.luc<0?"#ff6b6b":"#8a93a6";const cols=document.querySelectorAll("table thead th").length||10;const td=tr.firstElementChild||tr.appendChild(document.createElement("td"));td.colSpan=cols;td.setAttribute("style","padding:3px 14px;background:rgba(255,255,255,.015);border:none;font-size:12px;color:#8a93a6;text-align:right");td.innerHTML=`<span style="opacity:.7">↳ Lucro do jogo:</span> <strong style="color:${cor}">${money(s.luc)}</strong><span style="opacity:.5;margin-left:8px">${rs.length} apostas</span>` }
    function gameSubtotalRow(rs){ const tr=document.createElement("tr");tr.className="game-subtotal-row-v155";tr._betRows=rs;tr.appendChild(document.createElement("td"));renderSubtotal(tr);return tr }
    window.v155SyncSubtotals=function(){ document.querySelectorAll("tr.game-subtotal-row-v155").forEach(renderSubtotal) }
    function clear(tbody){ tbody.querySelectorAll("tr.game-group-row-v129,tr.game-group-row-v130,tr.game-group-row-v136,tr.day-separator-row-v136,tr.game-subtotal-row-v155").forEach(r=>r.remove());tbody.querySelectorAll("tr.bet-row").forEach(r=>r.classList.remove("group-child-v129","group-collapsed-v129","group-highlight-v129","group-child-v130","group-collapsed-v130","group-highlight-v130","group-child-v136","group-collapsed-v136","group-highlight-v136")) }
    function summary(rows){ let aberto=0,luc=0,green=0,red=0,pend=0;for(const r of rows){if(!closed(r)) aberto+=valor(r);luc+=lucro(r);const s=statusText(r);if(s.includes("ganha")||s.includes("green")) green++;else if(s.includes("perdida")||s.includes("red")) red++;else pend++}return{aberto,luc,green,red,pend} }
    function dayRow(k,count){ const tr=document.createElement("tr");tr.className="day-separator-row-v136";tr.dataset.dayKey=k;const cols=document.querySelectorAll("table thead th").length||10;tr.innerHTML=`<td colspan="${cols}"><span>${dayLabel(k)}</span><strong>${count} aposta${count!==1?"s":""}</strong></td>`;return tr }
    function groupHeader(k,rows){ const r=rep(rows),st=gStatus(r),s=summary(rows),cols=document.querySelectorAll("table thead th").length||10;const collapsed=collapsedGroups.has(k),lc=s.luc>0?"pos":s.luc<0?"neg":"";const tr=document.createElement("tr");tr.className="game-group-row-v136";tr.dataset.groupKey=k;tr.innerHTML=`<td colspan="${cols}"><button type="button" class="game-group-toggle-v129"><span class="group-arrow-v129">${collapsed?"▶":"▼"}</span><strong>${game(r)}</strong><span class="group-count-v129">${rows.length} aposta${rows.length>1?"s":""}</span><span class="game-date-status ${st[1]}">${st[0]}</span><span class="group-time-v129">${dateLabel(r)}</span><span class="group-summary-line-v138"><span>Aberto ${money(s.aberto)}</span><span class="${lc}">Lucro ${money(s.luc)}</span></span></button></td>`;tr.querySelector("button").onclick=()=>{collapsedGroups.has(k)?collapsedGroups.delete(k):collapsedGroups.add(k);apply(true)};return tr }
    function setupToolbar(){ const panel=document.querySelector(".table-panel")||document.querySelector("table")?.parentElement;if(!panel||panel.querySelector(".smart-table-toolbar-v129")) return;const bar=document.createElement("div");bar.className="smart-table-toolbar-v129";bar.innerHTML=`<button type="button" id="toggleGroupV129" class="smart-table-btn-v129">📌 Agrupar jogos</button><button type="button" id="expandGroupsV129" class="smart-table-btn-v129 secondary">Expandir tudo</button>`;const target=panel.querySelector(".table-scroll-wrap")||panel.querySelector("table");if(target&&target.parentElement===panel) panel.insertBefore(bar,target);else panel.prepend(bar);bar.querySelector("#toggleGroupV129").onclick=()=>{groupMode=!groupMode;bar.querySelector("#toggleGroupV129").textContent=groupMode?"☰ Lista simples":"📌 Agrupar jogos";apply(true)};bar.querySelector("#expandGroupsV129").onclick=()=>{collapsedGroups.clear();apply(true)} }
    function setupSort(){ const th=document.getElementById("gameDateSortHeader"),arrow=document.getElementById("gameDateSortArrow");if(!th||th.dataset.v136Ready==="1") return;th.dataset.v136Ready="1";th.onclick=()=>{sortAsc=!sortAsc;if(arrow) arrow.textContent=sortAsc?"↑":"↓";apply(true)} }
    function autoCollapse(groups){ initializedCollapse=true; }
    function apply(force=false){
        const tbody=document.querySelector("table tbody");if(!tbody) return
        setupToolbar();setupSort()
        let rows=Array.from(tbody.querySelectorAll("tr.bet-row"));if(!rows.length) return
        rows.forEach(r=>{game(r);renderLeft(r)});rows.sort(cmp);clear(tbody)
        const groups=new Map()
        if(groupMode){
            for(const r of rows){const k=groupKey(r);if(!groups.has(k)) groups.set(k,[]);groups.get(k).push(r)}
            autoCollapse(groups)
            const entries=Array.from(groups.entries()).sort((a,b)=>cmp(rep(a[1]),rep(b[1])))
            let currentDay=null
            for(const[k,rs]of entries){ const dk=dayKey(rep(rs));if(dk!==currentDay){currentDay=dk;let count=0;for(const[,xs]of entries) if(dayKey(rep(xs))===dk) count+=xs.length;tbody.appendChild(dayRow(dk,count))};if(rs.length>1&&!k.startsWith("__multi__")){tbody.appendChild(groupHeader(k,rs));const collapsed=collapsedGroups.has(k);rs.forEach(r=>{r.classList.add("group-child-v136");if(collapsed) r.classList.add("group-collapsed-v136");if(rs.length>=3) r.classList.add("group-highlight-v136");tbody.appendChild(r)})}else rs.forEach(r=>tbody.appendChild(r)) }
        }else{ const groups=clusterRows(rows);const counts={};groups.forEach(g=>counts[g.day]=(counts[g.day]||0)+g.rs.length);const daySeen=new Set();for(const g of groups){if(!daySeen.has(g.day)){daySeen.add(g.day);tbody.appendChild(dayRow(g.day,counts[g.day]))};g.rs.forEach(r=>tbody.appendChild(r));if(g.rs.length>1) tbody.appendChild(gameSubtotalRow(g.rs)) } }
        if(window.v155SyncSubtotals) window.v155SyncSubtotals()
    }
    function preserve(fn){ const y=window.scrollY;fn();requestAnimationFrame(()=>window.scrollTo({top:y,behavior:"auto"})) }
    document.addEventListener("click",e=>{ const t=String(e.target?.innerText||"").toLowerCase();if(t.includes("salvar apostas")||t.includes("excluir")||t.includes("editar")){setTimeout(()=>{ if(typeof _estaEditando==="function"&&_estaEditando()) return; preserve(()=>apply(true)) },700);setTimeout(()=>{ if(typeof _estaEditando==="function"&&_estaEditando()) return; preserve(()=>apply(true)) },1600)} })
    document.addEventListener("DOMContentLoaded",()=>{ apply(true);setInterval(()=>preserve(()=>apply(false)),300000) })
    document.addEventListener("DOMContentLoaded",()=>{ setTimeout(()=>{ if(typeof filtrarApostas==="function") filtrarApostas() },50) })
    window.v136SmartTableApply=apply
})();

// v141
(function(){
    function parseMoney(txt){ const raw=String(txt||"");let s=raw.replace(/[^\d,.-]/g,"").trim();const negative=raw.includes("-");if(s.includes(",")&&s.includes(".")) s=s.replace(/\./g,"").replace(",",".");else if(s.includes(",")) s=s.replace(",",".");const n=parseFloat(s);return isNaN(n)?0:(negative?-Math.abs(n):n) }
    function money(v){ const n=Number(v||0);return(n<0?"-R$ ":"R$ ")+Math.abs(n).toFixed(2) }
    function pct(v){ return Number(v||0).toFixed(2)+"%" }
    function card(title){ title=title.toLowerCase();return Array.from(document.querySelectorAll(".metric-card")).find(c=>(c.querySelector("span")?.innerText||"").trim().toLowerCase()===title) }
    function color(el,val){ if(!el) return;el.classList.remove("metric-positive-v137","metric-negative-v137","metric-zero-v137");if(val>0) el.classList.add("metric-positive-v137");else if(val<0) el.classList.add("metric-negative-v137");else el.classList.add("metric-zero-v137") }
    function atualizar(){
        const bancaAtualEl=card("banca atual")?.querySelector("strong"),bancaInicialEl=card("banca inicial")?.querySelector("strong"),valorAbertoEl=card("valor em aberto")?.querySelector("strong"),lucroEl=card("lucro total")?.querySelector("strong"),roiEl=card("roi")?.querySelector("strong")
        const bancaAtual=parseMoney(bancaAtualEl?.innerText||"0"),bancaInicial=parseMoney(bancaInicialEl?.innerText||"0"),valorAberto=parseMoney(valorAbertoEl?.innerText||"0")
        if(!bancaInicial) return
        const lucro=bancaAtual+valorAberto-bancaInicial,roi=(lucro/bancaInicial)*100
        if(lucroEl){ lucroEl.textContent=money(lucro);color(lucroEl,lucro) }
        if(roiEl){ roiEl.textContent=pct(roi);color(roiEl,lucro) }
    }
    window.v141AtualizarLucroPorBanca=atualizar
})();

// v142
(function(){
    window.v142Debounce=function(key,fn,wait){ window.__v142Timers=window.__v142Timers||{};clearTimeout(window.__v142Timers[key]);window.__v142Timers[key]=setTimeout(fn,wait||250) }
})();

// v147
(function(){
    function norm(v){ return String(v||"").normalize("NFD").replace(/[̀-ͯ]/g,"").toLowerCase().trim() }
    function col(label){ const target=norm(label);const ths=Array.from(document.querySelectorAll("table thead th"));for(let i=0;i<ths.length;i++){const txt=norm(ths[i].innerText).replace(/\s+[↑↓]$/,"");if(txt===target) return i}return -1 }
    function opts(s){ return Array.from(s.options||[]).map(o=>norm(o.innerText||o.value)).join(" ") }
    function money(txt){ txt=String(txt||"").replace(/[^\d,.-]/g,"").trim();if(txt.includes(",")&&txt.includes(".")) txt=txt.replace(/\./g,"").replace(",",".");else if(txt.includes(",")) txt=txt.replace(",",".");const n=parseFloat(txt);return isNaN(n)?0:n }
    function filters(){
        const inputs=Array.from(document.querySelectorAll("input")),selects=Array.from(document.querySelectorAll("select"))
        const search=inputs.find(i=>norm(i.placeholder).includes("pesquisar")),min=inputs.find(i=>norm(i.placeholder).includes("valor min")),max=inputs.find(i=>norm(i.placeholder).includes("valor max"))
        const status=selects.find(s=>{const o=opts(s);return o.includes("pendente")||o.includes("ganha")||o.includes("perdida")||o.includes("anulada")})
        const data=selects.find(s=>{const o=opts(s);return o.includes("todas as datas")||o.includes("hoje")||o.includes("amanha")||o.includes("amanhã")})
        const casa=selects.find(s=>s!==status&&s!==data&&(opts(s).includes("todos")||opts(s).includes("todas")))
        return{q:norm(search?.value||""),status:norm(status?.value||status?.selectedOptions?.[0]?.innerText||""),data:norm(data?.value||data?.selectedOptions?.[0]?.innerText||""),casa:norm(casa?.value||casa?.selectedOptions?.[0]?.innerText||""),min:min&&min.value!==""?money(min.value):null,max:max&&max.value!==""?money(max.value):null}
    }
    function rowDate(row){ const txt=row.children?.[0]?.innerText||"";const m=txt.match(/(\d{2})\/(\d{2})(?:\/(\d{4}))?/);if(!m) return "";return`${m[3]||new Date().getFullYear()}-${m[2]}-${m[1]}` }
    function dateOk(row,f){ if(!f||f==="todas"||f==="todas as datas") return true;const d=rowDate(row);if(!d) return true;const p=n=>String(n).padStart(2,"0");const now=new Date();const today=`${now.getFullYear()}-${p(now.getMonth()+1)}-${p(now.getDate())}`;const tom=new Date(now.getFullYear(),now.getMonth(),now.getDate()+1);const tomorrow=`${tom.getFullYear()}-${p(tom.getMonth()+1)}-${p(tom.getDate())}`;if(f.includes("hoje")) return d===today;if(f.includes("amanha")||f.includes("amanhã")) return d===tomorrow;if(/\d{4}-\d{2}-\d{2}/.test(f)) return d===f;return true }
    function statusOk(row,f){ if(!f||f==="todos"||f==="todas") return true;const i=col("status"),txt=norm(i>=0?row.children?.[i]?.innerText:"");if(f.includes("pendente")) return txt.includes("pendente");if(f.includes("ganha")||f.includes("green")) return txt.includes("ganha")||txt.includes("green");if(f.includes("perdida")||f.includes("red")) return txt.includes("perdida")||txt.includes("red");if(f.includes("anulada")||f.includes("void")) return txt.includes("anulada")||txt.includes("void");return txt.includes(f) }
    function rowOk(row,f){ if(f.q&&!norm(row.innerText).includes(f.q)) return false;if(!statusOk(row,f.status)) return false;if(!dateOk(row,f.data)) return false;if(f.casa&&!["todos","todas"].includes(f.casa)){const i=col("Casa"),txt=norm(i>=0?row.children?.[i]?.innerText:"");if(txt&&txt!==f.casa&&!txt.includes(f.casa)) return false}const vi=col("Valor"),val=money(vi>=0?row.children?.[vi]?.innerText:"");if(f.min!==null&&val<f.min) return false;if(f.max!==null&&val>f.max) return false;return true }
    function apply(){
        const tbody=document.querySelector("table tbody");if(!tbody) return
        const f=filters(),rows=Array.from(tbody.querySelectorAll("tr.bet-row"))
        rows.forEach(r=>{const ok=rowOk(r,f);r.dataset.v147Filtered=ok?"1":"0";r.style.display=ok?"":"none"})
        const all=Array.from(tbody.children)
        all.forEach((el,i)=>{
            if(el.classList.contains("game-group-row-v136")||el.classList.contains("game-group-row-v130")||el.classList.contains("game-group-row-v129")){let v=false;for(let j=i+1;j<all.length;j++){const n=all[j];if(n.classList.contains("game-group-row-v136")||n.classList.contains("game-group-row-v130")||n.classList.contains("game-group-row-v129")||n.classList.contains("day-separator-row-v136")) break;if(n.classList.contains("bet-row")&&n.dataset.v147Filtered==="1"){v=true;break}};el.style.display=v?"":"none"}
        })
        all.forEach((el,i)=>{ if(el.classList.contains("day-separator-row-v136")){let v=false;for(let j=i+1;j<all.length;j++){const n=all[j];if(n.classList.contains("day-separator-row-v136")) break;if((n.classList.contains("bet-row")&&n.dataset.v147Filtered==="1")||((n.className||"").includes("game-group-row")&&n.style.display!=="none")){v=true;break}};el.style.display=v?"":"none"} })
    }
    function bind(){ document.querySelectorAll("input,select").forEach(el=>{if(el.dataset.v147Ready==="1") return;el.dataset.v147Ready="1";el.addEventListener("input",()=>{clearTimeout(window.__v147t);window.__v147t=setTimeout(apply,120)});el.addEventListener("change",()=>{clearTimeout(window.__v147t);window.__v147t=setTimeout(apply,120)})}) }
    document.addEventListener("click",e=>{const t=norm(e.target?.innerText||"");if(t.includes("agrupar")||t.includes("expandir")||t.includes("salvar")||t.includes("editar")||t.includes("excluir")||t.includes("buscar")){setTimeout(()=>{bind();apply()},350);setTimeout(apply,1300)}})
    document.addEventListener("DOMContentLoaded",()=>{bind();setTimeout(apply,0)})
    window.v147ApplyFilters=apply
})();
// Wrap v147ApplyFilters: whenever something calls it (e.g. v150 at 900ms/2000ms),
// filtrarApostas re-runs right after to re-apply the date filter
;(function(){
    const _orig=window.v147ApplyFilters
    window.v147ApplyFilters=function(){ if(_orig) _orig(); if(typeof filtrarApostas==="function") filtrarApostas() }
})();

// v149
(function(){
    let ultimaVersaoApostas=null,feedVisivel=false,mostrarHistoricoAntigo=false
    function norm(v){ return String(v||"").normalize("NFD").replace(/[̀-ͯ]/g,"").toLowerCase().trim() }
    function statusIdx(){ const ths=Array.from(document.querySelectorAll("table thead th"));for(let i=0;i<ths.length;i++){if(norm(ths[i].innerText).replace(/\s+[↑↓]$/,"")==="status") return i}return -1 }
    function rowDate(row){ const txt=row.children?.[0]?.innerText||"";const m=txt.match(/(\d{2})\/(\d{2})(?:\/(\d{4}))?/);if(!m) return null;return new Date(Number(m[3]||new Date().getFullYear()),Number(m[2])-1,Number(m[1])) }
    function isOldFinished(row){ const si=statusIdx();const st=norm(si>=0?row.children?.[si]?.innerText:"");const finished=st.includes("ganha")||st.includes("green")||st.includes("perdida")||st.includes("red")||st.includes("anulada")||st.includes("void");if(!finished) return false;const d=rowDate(row);if(!d) return false;const today=new Date();today.setHours(0,0,0,0);d.setHours(0,0,0,0);return d.getTime()<today.getTime() }
    function ensureHistoricoButton(){ const panel=document.querySelector(".table-panel")||document.querySelector("table")?.parentElement;if(!panel||document.getElementById("toggleHistoricoV149")||document.getElementById("betStatusPills")) return;const bar=panel.querySelector(".smart-table-toolbar-v129")||panel;const btn=document.createElement("button");btn.type="button";btn.id="toggleHistoricoV149";btn.className="smart-table-btn-v129 secondary historico-btn-v149";btn.textContent="📦 Mostrar finalizadas antigas";btn.onclick=()=>{mostrarHistoricoAntigo=!mostrarHistoricoAntigo;btn.textContent=mostrarHistoricoAntigo?"📦 Ocultar finalizadas antigas":"📦 Mostrar finalizadas antigas";aplicarHistorico()};if(bar.classList&&bar.classList.contains("smart-table-toolbar-v129")){bar.appendChild(btn)}else{const target=panel.querySelector(".table-scroll-wrap")||panel.querySelector("table");if(target&&target.parentElement===panel) panel.insertBefore(btn,target);else panel.prepend(btn)} }
    function aplicarHistorico(){ const rows=Array.from(document.querySelectorAll("tr.bet-row"));let hidden=0;rows.forEach(row=>{if(isOldFinished(row)&&!mostrarHistoricoAntigo){row.classList.add("v149-historico-hidden");hidden++}else{row.classList.remove("v149-historico-hidden")}});let badge=document.getElementById("historicoHiddenBadgeV149");const btn=document.getElementById("toggleHistoricoV149");if(btn){if(!badge){badge=document.createElement("span");badge.id="historicoHiddenBadgeV149";badge.className="historico-badge-v149";btn.appendChild(badge)};badge.textContent=hidden?" "+hidden:""} }
    async function checarVersaoApostas(){ try{const r=await fetch("/api/apostas_versao",{cache:"no-store"});const data=await r.json();if(!data||!data.ok) return;if(ultimaVersaoApostas===null){ultimaVersaoApostas=data.versao;return};if(data.versao!==ultimaVersaoApostas){ultimaVersaoApostas=data.versao;if(feedVisivel){try{if(typeof carregarFeedApostas==="function") carregarFeedApostas(false)}catch(e){}};setTimeout(()=>{try{if(typeof v147ApplyFilters==="function") v147ApplyFilters()}catch(e){}; aplicarHistorico()},500)}}catch(e){} }
    function patchStatusButtons(){ document.querySelectorAll("tr.bet-row button,tr.bet-row a").forEach(btn=>{if(btn.dataset.v149StatusReady==="1") return;const t=norm(btn.innerText||btn.title||btn.getAttribute("aria-label")||"");const icon=(btn.innerText||"").trim();const looksStatus=t.includes("green")||t.includes("ganha")||t.includes("red")||t.includes("perdida")||t.includes("anular")||t.includes("anulada")||["✓","✔","x","✕","-"].includes(icon);if(!looksStatus) return;btn.dataset.v149StatusReady="1";btn.addEventListener("click",()=>{const row=btn.closest("tr.bet-row");if(row){row.classList.add("v149-status-changing");setTimeout(()=>row.classList.remove("v149-status-changing"),2200)};setTimeout(()=>{try{if(typeof v147ApplyFilters==="function") v147ApplyFilters()}catch(e){}; try{if(typeof v141AtualizarLucroPorBanca==="function") v141AtualizarLucroPorBanca()}catch(e){}; aplicarHistorico()},900)},{capture:true})}) }
    function boot(){ patchStatusButtons();aplicarHistorico();checarVersaoApostas() }
    document.addEventListener("click",e=>{ const t=norm(e.target?.innerText||"");if(t.includes("ultimas apostas")||t.includes("últimas apostas")) feedVisivel=true;if(t.includes("evolucao")||t.includes("evolução")) feedVisivel=false;const isFormSubmit=e.target?.type==="submit"&&e.target?.closest("form#manualForm");if(!isFormSubmit&&(t.includes("salvar")||t.includes("editar")||t.includes("excluir")||t.includes("agrupar")||t.includes("expandir"))){setTimeout(()=>{ensureHistoricoButton();patchStatusButtons();aplicarHistorico()},800)} })
    document.addEventListener("DOMContentLoaded",()=>{ setTimeout(boot,0);setTimeout(boot,200);setInterval(()=>{ if(typeof _estaEditando==="function"&&_estaEditando()) return; checarVersaoApostas() },30000) })
    window.v149AplicarHistorico=aplicarHistorico
    window.v149SetMostrarHistorico=function(v){ mostrarHistoricoAntigo=Boolean(v); aplicarHistorico() }
})();

// v155: subtotais de lucro-por-jogo respeitam os filtros (v147) e o esconder-antigas (v149)
;(function(){
    function wrap(name){ const o=window[name];if(typeof o==="function"&&!o.__v155Wrapped){ const w=function(){ const r=o.apply(this,arguments);if(window.v155SyncSubtotals) window.v155SyncSubtotals();return r };w.__v155Wrapped=true;window[name]=w } }
    function armar(){ wrap("v147ApplyFilters");wrap("v149AplicarHistorico");wrap("v149SetMostrarHistorico");if(window.v155SyncSubtotals) window.v155SyncSubtotals() }
    document.addEventListener("DOMContentLoaded",()=>{ armar();setTimeout(armar,300);setTimeout(armar,1200) })
})();

// v150
(function(){
    const LIMITE_MINUTOS=130
    function parseGameDateFromDataset(row){ const iso=row.dataset.horarioJogoIso||row.dataset.horario||"";if(!iso) return null;const d=new Date(iso);return isNaN(d.getTime())?null:d }
    function parseGameDateFromCell(row){ const txt=row.children?.[0]?.innerText||"";const m=txt.match(/(\d{2})\/(\d{2})(?:\/(\d{4}))?\s+(\d{1,2}):(\d{2})/);if(!m) return null;return new Date(Number(m[3]||new Date().getFullYear()),Number(m[2])-1,Number(m[1]),Number(m[4]),Number(m[5])) }
    function gameDate(row){ return parseGameDateFromDataset(row)||parseGameDateFromCell(row) }
    function shouldFinalize(row){ const d=gameDate(row);if(!d) return false;return(Date.now()-d.getTime())/60000>=LIMITE_MINUTOS }
    function forceFinalizeOldLiveGames(){ document.querySelectorAll("tr.bet-row").forEach(row=>{if(!shouldFinalize(row)) return;if(row.dataset.v150Finalized==="1") return;row.dataset.v150Finalized="1";row.dataset.aoVivo="0";row.dataset.statusJogo="Finalizado";row.dataset.horarioJogo="Finalizado";const first=row.children?.[0];if(first){const main=first.querySelector(".game-date-main")?.innerText||first.innerText.split("\n")[0]||"";first.classList.add("game-date-cell");first.innerHTML=`<span class="game-date-main">${main}</span><span class="game-date-status finished">Finalizado</span>`}}) }
    function refresh(){ forceFinalizeOldLiveGames();try{if(typeof v147ApplyFilters==="function") v147ApplyFilters()}catch(e){};try{if(typeof v149AplicarHistorico==="function") v149AplicarHistorico()}catch(e){} }
        // Antes rodava a CADA clique (causava a tabela inteira piscar ao abrir o editar).
    document.addEventListener("DOMContentLoaded",()=>{ setTimeout(refresh,900);setTimeout(refresh,2000) })
    // Agora roda periodicamente — finaliza jogos antigos sem re-renderizar a cada clique.
    setInterval(()=>{ if(typeof _estaEditando==="function"&&_estaEditando()) return; refresh() }, 60000)
    window.v150ForceFinalizeOldLiveGames=refresh
})();

// v160 — pills de status
(function(){
    function init(){
        const pills=document.querySelectorAll('#betStatusPills .bet-pill')
        if(!pills.length) return
        pills.forEach(pill=>{
            pill.addEventListener('click',function(){
                pills.forEach(p=>p.classList.remove('active'))
                this.classList.add('active')
                const status=this.dataset.status
                const sf=document.getElementById('statusFilter')
                if(sf){ const valid=['todos','ganha','perdida','pendente','anulada'];sf.value=valid.includes(status)?status:'todos' }
                if(typeof v149SetMostrarHistorico==='function') v149SetMostrarHistorico(['finalizadas','ganha','perdida','anulada'].includes(status))
                filtrarApostas()
                if(status==='finalizadas') setTimeout(filtrarApostas,220)
                setTimeout(updateFinBadge,300)
                try{ if(typeof v147ApplyFilters==='function'&&status!=='finalizadas') v147ApplyFilters() }catch(e){}
            })
        })
        updateFinBadge()
    }
    function updateFinBadge(){
        const badge=document.getElementById('finBadge');if(!badge) return
        let count=0
        document.querySelectorAll('tr.bet-row').forEach(r=>{
            const st=(r.querySelector('.status-cell')?.innerText||'').toLowerCase()
            if(st.includes('ganha')||st.includes('perdida')||st.includes('anulada')) count++
        })
        badge.textContent=count>0?count:''
    }
    document.addEventListener('DOMContentLoaded',()=>{ setTimeout(init,80); setTimeout(updateFinBadge,900) })
    window.v160UpdateFinBadge=updateFinBadge
})();

// v154
(function(){
    function norm(v){ return String(v||"").normalize("NFD").replace(/[̀-ͯ]/g,"").toLowerCase().trim() }
    function parseMoney(txt){ const raw=String(txt||"");let s=raw.replace(/[^\d,.-]/g,"").trim();const negative=raw.includes("-");if(s.includes(",")&&s.includes(".")) s=s.replace(/\./g,"").replace(",",".");else if(s.includes(",")) s=s.replace(",",".");const n=parseFloat(s);return isNaN(n)?0:(negative?-Math.abs(n):n) }
    function money(v){ const n=Number(v||0);return(n<0?"-R$ ":"R$ ")+Math.abs(n).toFixed(2) }
    function col(label){ const target=norm(label);const ths=Array.from(document.querySelectorAll("table thead th"));for(let i=0;i<ths.length;i++){const txt=norm(ths[i].innerText).replace(/\s+[↑↓]$/,"");if(txt===target) return i}return -1 }
    function estadoFromHref(href){ const m=String(href||"").match(/\/resultado\/[^\/]+\/([^\/\?]+)/);return m?decodeURIComponent(m[1]):"" }
    function badge(estado){ estado=norm(estado);if(estado==="ganha"||estado==="green") return`<span class="status-badge ganha">Ganha</span>`;if(estado==="perdida"||estado==="red") return`<span class="status-badge perdida">Perdida</span>`;if(estado==="anulada"||estado==="void") return`<span class="status-badge anulada">Anulada</span>`;return`<span class="status-badge pendente">Pendente</span>` }
    function lucroLocal(row,estado){ const oddIdx=col("Odd"),valorIdx=col("Valor");const odd=parseMoney(oddIdx>=0?row.children?.[oddIdx]?.innerText:"");const valor=parseMoney(valorIdx>=0?row.children?.[valorIdx]?.innerText:"");estado=norm(estado);if(estado==="ganha"||estado==="green") return(odd*valor)-valor;if(estado==="perdida"||estado==="red") return -valor;return 0 }
    function aplicarLinha(row,estado,lucro){ const statusIdx=col("Status"),lucroIdx=col("Lucro");if(statusIdx>=0&&row.children?.[statusIdx]) row.children[statusIdx].innerHTML=badge(estado);if(lucro===undefined||lucro===null||Number.isNaN(Number(lucro))) lucro=lucroLocal(row,estado);if(lucroIdx>=0&&row.children?.[lucroIdx]){row.children[lucroIdx].textContent=money(Number(lucro||0));row.children[lucroIdx].classList.remove("lucro-pos","lucro-neg","lucro-zero");row.children[lucroIdx].classList.add(lucro>0?"lucro-pos":lucro<0?"lucro-neg":"lucro-zero")};row.classList.add("v154-status-ok");setTimeout(()=>row.classList.remove("v154-status-ok"),900) }
    function atualizarMetricas(metricas){ if(!metricas) return;function setByTitle(title,value,formatter){const card=Array.from(document.querySelectorAll(".metric-card")).find(c=>norm(c.querySelector("span")?.innerText||"")===norm(title));const strong=card?.querySelector("strong");if(strong) strong.textContent=formatter?formatter(value):value};if(metricas.banca_atual!==undefined) setByTitle("Banca Atual",metricas.banca_atual,money);const _elTot=document.getElementById("metric-total");if(_elTot&&metricas.total!==undefined) _elTot.textContent=String(metricas.total);if(metricas.pendentes!==undefined) setByTitle("Pendentes",metricas.pendentes,v=>String(v));const elLucro=document.getElementById("metric-lucro");if(elLucro&&metricas.lucro_total!==undefined){const l=Number(metricas.lucro_total);elLucro.textContent=money(l);elLucro.classList.toggle("mc-pos",l>=0);elLucro.classList.toggle("mc-neg",l<0)};const elRoi=document.getElementById("metric-roi");if(elRoi&&metricas.roi!==undefined) elRoi.textContent=Number(metricas.roi).toFixed(2)+"%";const elTaxa=document.getElementById("metric-taxa");if(elTaxa&&metricas.taxa!==undefined) elTaxa.textContent=Number(metricas.taxa).toFixed(2)+"%" }
    function recalcularLeve(){ try{if(typeof v141AtualizarLucroPorBanca==="function") v141AtualizarLucroPorBanca()}catch(e){};try{if(typeof v147ApplyFilters==="function") v147ApplyFilters()}catch(e){};try{if(typeof v149AplicarHistorico==="function") v149AplicarHistorico()}catch(e){};try{if(typeof v150ForceFinalizeOldLiveGames==="function") v150ForceFinalizeOldLiveGames()}catch(e){} }
    async function ajaxResultado(anchor,row){
        const href=anchor.getAttribute("href"),estado=estadoFromHref(href);if(!href||!estado) return
        const y=window.scrollY;row.classList.add("v154-status-loading")
        const url=(href.includes("?")?href+"&ajax=1":href+"?ajax=1")+window._mesQS("&")
        const r=await fetch(url,{method:"GET",headers:{"X-Requested-With":"XMLHttpRequest"},cache:"no-store"})
        let data={};try{data=await r.json()}catch(e){}
        if(!r.ok||!data.ok) throw new Error(data.erro||"erro_status")
        const bet=data.bet||{},lucro=bet.lucro!==undefined?Number(bet.lucro):lucroLocal(row,estado)
        aplicarLinha(row,bet.estado||bet.status||estado,lucro);atualizarMetricas(data.metricas);recalcularLeve()
        requestAnimationFrame(()=>window.scrollTo({top:y,behavior:"auto"}))
    }
    function attachResultadoClicks(){
        document.querySelectorAll('a[href*="/resultado/"]').forEach(a=>{
            if(a.dataset.v154) return
            a.dataset.v154="1"
            a.addEventListener("click",async function(e){
                e.preventDefault()
                const row=a.closest("tr"); if(!row) return location.href=a.href
                try{ await ajaxResultado(a,row) }catch(err){ location.href=a.href }
            })
        })
    }
    document.addEventListener("DOMContentLoaded",()=>{ attachResultadoClicks(); const obs=new MutationObserver(()=>attachResultadoClicks()); obs.observe(document.body,{childList:true,subtree:true}) })
    window.v154StatusAjaxOriginal=true
})();



// Planilha sidebar switcher
function toggleSbPlanilha(ev) {
    if (ev) ev.stopPropagation();
    const wrap = document.querySelector('.sb-pl-wrap');
    const menu = document.getElementById('sbPlMenu');
    if (!menu) return;
    const open = menu.style.display !== 'none';
    menu.style.display = open ? 'none' : 'block';
    if (wrap) wrap.classList.toggle('open', !open);
}
function sbPlRenomear(pid, nomeAtual) {
    const novo = prompt('Novo nome para a planilha:', nomeAtual);
    if (!novo || novo.trim() === nomeAtual) return;
    document.getElementById('sbPlRenamePid').value = pid;
    document.getElementById('sbPlRenomeNome').value = novo.trim();
    document.getElementById('sbPlRenameForm').submit();
}
// Topbar bankroll dropdown
function toggleTopbarBankroll(ev) {
    if (ev) ev.stopPropagation();
    const wrap = document.querySelector('.topbar-bankroll-wrap');
    const menu = document.getElementById('topbarBankrollMenu');
    if (!menu) return;
    const open = menu.style.display !== 'none';
    menu.style.display = open ? 'none' : 'block';
    if (wrap) wrap.classList.toggle('open', !open);
}
function topbarBrRenomear(pid, nomeAtual) {
    const novo = prompt('Novo nome para a planilha:', nomeAtual);
    if (!novo || novo.trim() === nomeAtual) return;
    document.getElementById('topbarBrRenamePid').value = pid;
    document.getElementById('topbarBrRenomeNome').value = novo.trim();
    document.getElementById('topbarBrRenameForm').submit();
}


// ======= DOMContentLoaded CONSOLIDADO =======
document.addEventListener("DOMContentLoaded", function(){
    // 1. Limpar apostas duplicadas visualmente
    limparApostaDuplicadaVisual()

    // 2. Form manual — handler já em document.addEventListener("submit",...,true) na linha do v72

    // 3. Restaurar estado da sidebar
    ;(function(){
        const collapsed = localStorage.getItem("sidebarCollapsed") === "1"
        if(collapsed){
            document.body.classList.add("sidebar-collapsed")
            const btn = document.querySelector(".sidebar-toggle")
            if(btn) btn.innerText = "›"
        }
    })()

    // 4. Bind filtros
    document.querySelectorAll("#apostas select,#casasDrop input").forEach(el=>{
        el.addEventListener("change", filtrarApostasDebounced)
    })

    // 5. Grafico Chart.js
    ;(function(){
        const canvas = document.getElementById("grafico")
        if(!canvas || typeof Chart === "undefined") return
        const corBarra = v => v >= 0 ? "rgba(34,197,94,0.70)" : "rgba(248,113,113,0.70)"
        const corBorda = v => v >= 0 ? "#22c55e" : "#f87171"
        new Chart(canvas, {
            type: "bar",
            data: { labels: labels, datasets: [{
                label: "Lucro do dia",
                data: valores,
                backgroundColor: valores.map(corBarra),
                borderColor: valores.map(corBorda),
                borderWidth: 1.5,
                borderRadius: 4,
                maxBarThickness: 48,
            }]},
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor:"rgba(15,23,42,0.96)", titleColor:"#f1f5f9", bodyColor:"#f1f5f9",
                        titleFont:{size:13, weight:"bold"}, bodyFont:{size:15, weight:"bold"},
                        padding:11, displayColors:false, borderColor:"rgba(148,163,184,0.3)", borderWidth:1,
                        callbacks: {
                            title: items => "Dia " + (items[0]?.label || ""),
                            label: ctx => (ctx.parsed.y >= 0 ? "Lucro: R$ " : "Prejuízo: R$ ") + Math.abs(ctx.parsed.y).toFixed(2)
                        }
                    }
                },
                layout: { padding: { top:6, right:8, bottom:0, left:0 } },
                scales: {
                    x: { ticks: { color:"#e2e8f0", maxRotation:45, minRotation:45, autoSkip:true, maxTicksLimit:20, font:{size:12, weight:"600"} }, grid: { color:"rgba(30,41,59,0.35)" } },
                    y: {
                        ticks: { color:"#e2e8f0", font:{size:12, weight:"600"}, callback: v => "R$ "+v.toFixed(0) },
                        grid: { color:"rgba(30,41,59,0.55)" },
                        afterBuildTicks(axis){ if(!axis.ticks.some(t=>t.value===0)) axis.ticks.push({value:0}) },
                    }
                }
            }
        })
    })()

    // 6. Feed de apostas
    carregarFeedApostas(true)
    setInterval(()=>carregarFeedApostas(false), 60000)
    ;(function(){
        const feedTab = document.getElementById("tabFeedBtn"); if(feedTab) feedTab.addEventListener("click", v63ClearNewBetAlert)
        const feedPanel = document.getElementById("aba-feed"); if(feedPanel) feedPanel.addEventListener("mouseenter", v63ClearNewBetAlert)
    })()

    // 7. Restaurar scroll
    v72RestoreScroll()

    // 8. vFix: anti-tremida, pills, MutationObserver
    ;(function(){
        if(document.getElementById('betStatusPills')){
            window.v149AplicarHistorico = function(){}
            window.v149SetMostrarHistorico = function(){}
        }
        function _cancelaV147(e){
            const t = e.target
            if(t && t.matches && t.matches('input, select') && !t.closest('#apostas')){
                clearTimeout(window.__v147t)
            }
        }
        document.addEventListener('input', _cancelaV147)
        document.addEventListener('change', _cancelaV147)
        document.querySelectorAll('#apostas input, #apostas select').forEach(function(el){
            el.addEventListener('input',  function(){ clearTimeout(window.__v147t) })
            el.addEventListener('change', function(){ clearTimeout(window.__v147t) })
        })
        setTimeout(function(){ if(typeof filtrarApostas==='function') filtrarApostas() }, 250)
        setTimeout(function(){ if(typeof filtrarApostas==='function') filtrarApostas() }, 1100)
        setTimeout(function(){ if(typeof filtrarApostas==='function') filtrarApostas() }, 2500)
        setTimeout(function(){
            const _origV136 = window.v136SmartTableApply
            if(_origV136){
                window.v136SmartTableApply = function(force){
                    _origV136(force)
                    setTimeout(function(){ if(typeof filtrarApostas==='function') filtrarApostas() }, 80)
                }
            }
        }, 500)
        const _tbody = document.querySelector('#betsMainTable tbody')
        if(_tbody && typeof MutationObserver !== 'undefined'){
            let _t = null
            const _obs = new MutationObserver(function(){
                clearTimeout(_t)
                _t = setTimeout(function(){
                    if(typeof filtrarApostas === 'function') filtrarApostas()
                }, 60)
            })
            _obs.observe(_tbody, { childList: true })
        }
    })()
})

// ======= click GLOBAL CONSOLIDADO =======
// Handlers não-capture (bubble): fechamento de menus/dropdowns
document.addEventListener("click", function(e){
    // Fechar custom-dropdown ao clicar fora
    document.querySelectorAll(".custom-filter").forEach(box=>{
        if(!box.contains(e.target)){ const dropdown = box.querySelector(".custom-dropdown"); if(dropdown) dropdown.classList.remove("open") }
    })

    // Fechar bet-fi-multi-drop ao clicar fora
    if(!e.target.closest(".bet-fi-multi")) document.querySelectorAll(".bet-fi-multi-drop.open").forEach(d=>d.classList.remove("open"))

    // Fechar sidebar user menu ao clicar fora
    const sidebarMenu = document.getElementById("sidebarUserMenu")
    const sidebarCard = document.querySelector(".sidebar-user-card")
    if(sidebarMenu && sidebarCard && !sidebarMenu.contains(e.target) && !sidebarCard.contains(e.target)) sidebarMenu.classList.remove("open")

    // Fechar planilha switcher ao clicar fora
    const sbPlWrap = document.querySelector('.sb-pl-wrap')
    const sbPlMenu = document.getElementById('sbPlMenu')
    if(sbPlMenu && sbPlMenu.style.display !== 'none' && sbPlWrap && !sbPlWrap.contains(e.target)){
        sbPlMenu.style.display = 'none'
        sbPlWrap.classList.remove('open')
    }

    // Fechar topbar bankroll dropdown ao clicar fora
    const topbarBrWrap = document.querySelector('.topbar-bankroll-wrap')
    const topbarBrMenu = document.getElementById('topbarBankrollMenu')
    if(topbarBrMenu && topbarBrMenu.style.display !== 'none' && topbarBrWrap && !topbarBrWrap.contains(e.target)){
        topbarBrMenu.style.display = 'none'
        topbarBrWrap.classList.remove('open')
    }
})

// Handlers capture (interceptam antes dos elementos):
document.addEventListener("click", function(e){
    // Salvar scroll antes de navegar
    const action = e.target.closest('a[href^="/resultado/"], a[href^="/remover/"], a[href^="/admin/"], a[href^="/saldos/remover/"]')
    if(action) sessionStorage.setItem("restoreScrollY", String(window.scrollY || 0))
}, true)

document.addEventListener("click", function(e){
    // AJAX: marcar resultado
    const link=e.target.closest('a[href^="/resultado/"]'); if(!link) return
    e.preventDefault(); e.stopPropagation()
    const tr=link.closest("tr"); link.style.pointerEvents="none"; link.style.opacity=".6"
    fetch(link.getAttribute("href")+"?ajax=1"+window._mesQS("&"), {cache:"no-store"})
    .then(r=>r.json()).then(d=>{ if(!d.ok) throw new Error("erro"); v72UpdateRow(tr,d.bet); v72UpdateMetrics(d.metricas); v72Toast("Resultado atualizado") })
    .catch(()=>v72Toast("Erro ao atualizar","err"))
    .finally(()=>{ link.style.pointerEvents=""; link.style.opacity="" })
}, true)

document.addEventListener("click", function(e){
    // AJAX: remover aposta
    const link=e.target.closest('a[href^="/remover/"]'); if(!link) return
    e.preventDefault(); e.stopPropagation()
    if(!confirm("Apagar esta aposta?")) return
    const tr=link.closest("tr")
    fetch(link.getAttribute("href")+"?ajax=1"+window._mesQS("&"), {cache:"no-store"})
    .then(r=>r.json()).then(d=>{
        if(!d.ok) throw new Error("erro")
        if(tr){ tr.style.transition=".18s ease"; tr.style.opacity="0"; tr.style.transform="translateX(10px)"; setTimeout(()=>tr.remove(),180) }
        v72UpdateMetrics(d.metricas); v72Toast("Aposta apagada")
    })
    .catch(()=>v72Toast("Erro ao apagar","err"))
}, true)

document.addEventListener("click", function(e){ if(e.target.closest("a,button")) v72SaveScroll() }, true)
