const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const STATES = [["AC","Acre"],["AL","Alagoas"],["AP","Amapá"],["AM","Amazonas"],["BA","Bahia"],["CE","Ceará"],["DF","Distrito Federal"],["ES","Espírito Santo"],["GO","Goiás"],["MA","Maranhão"],["MT","Mato Grosso"],["MS","Mato Grosso do Sul"],["MG","Minas Gerais"],["PA","Pará"],["PB","Paraíba"],["PR","Paraná"],["PE","Pernambuco"],["PI","Piauí"],["RJ","Rio de Janeiro"],["RN","Rio Grande do Norte"],["RS","Rio Grande do Sul"],["RO","Rondônia"],["RR","Roraima"],["SC","Santa Catarina"],["SP","São Paulo"],["SE","Sergipe"],["TO","Tocantins"]];
const REGIONS = {Norte:["AC","AP","AM","PA","RO","RR","TO"],Nordeste:["AL","BA","CE","MA","PB","PE","PI","RN","SE"],"Centro-Oeste":["DF","GO","MT","MS"],Sudeste:["ES","MG","RJ","SP"],Sul:["PR","RS","SC"]};
const FILTER_KEY = "licitara:filters";
const SAVED_KEY = "licitara:saved";
const REFRESH_MS = 60000;
const state = {catalog:{},products:[],states:[],city:"",period:"open",search:"",sort:"date",page:1,pages:1,total:0,view:"opportunities",saved:[],opportunities:[],filterTab:"region",filterSnapshot:null,loading:false,pendingLoad:false};

function esc(value=""){return String(value).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function money(value){return typeof value==="number"&&Number.isFinite(value)?value.toLocaleString("pt-BR",{style:"currency",currency:"BRL"}):"Não informado";}
function dateTimeFmt(value){if(!value)return"Não informado";const d=new Date(value);return Number.isNaN(d.getTime())?String(value):`${d.toLocaleDateString("pt-BR",{day:"2-digit",month:"short",year:"numeric"}).replace(".","")} · ${d.toLocaleTimeString("pt-BR",{hour:"2-digit",minute:"2-digit"})}`;}
function isFuture(value){if(!value)return false;const d=new Date(value);return !Number.isNaN(d.getTime())&&d.getTime()>Date.now();}
async function api(url,options={}){const response=await fetch(url,{credentials:"same-origin",...options,headers:{"Content-Type":"application/json",...(options.headers||{})}});let data={};try{data=await response.json()}catch{}if(!response.ok)throw new Error(data.error||"Não foi possível concluir a solicitação.");return data;}
function post(url,data){return api(url,{method:"POST",body:JSON.stringify(data)});}
function toast(message,type="success"){const node=document.createElement("div");node.className=`toast ${type==="error"?"error":""}`;node.innerHTML=`<span class="toast-indicator"></span><span>${esc(message)}</span>`;$("#toast-region").append(node);setTimeout(()=>node.remove(),4300);}

function readSaved(){try{const value=JSON.parse(localStorage.getItem(SAVED_KEY)||"[]");return Array.isArray(value)?value:[]}catch{return[]}}
function readFilters(){
  try{const saved=JSON.parse(localStorage.getItem(FILTER_KEY)||"{}")||{};
    return {products:Array.isArray(saved.products)?saved.products.slice(0,100):[],
      states:Array.isArray(saved.states)?saved.states.filter(code=>STATES.some(([s])=>s===code)):[],
      city:typeof saved.city==="string"?saved.city:"",period:saved.period==="future"?"future":"open"};}
  catch{return {products:[],states:[],city:"",period:"open"}}
}
function saveFiltersLocally(){localStorage.setItem(FILTER_KEY,JSON.stringify({products:state.products,states:state.states,city:state.city,period:state.period}))}

async function init(){
  const restored=readFilters();
  state.products=restored.products;state.states=restored.states;state.city=restored.city;state.period=restored.period;
  state.saved=readSaved();
  bindGlobal();
  try{const catalog=await api("/api/catalog");state.catalog=catalog.categories||{}}catch{toast("Não foi possível carregar o catálogo de produtos.","error")}
  updateProfileTags();
  await loadOpportunities();
  startAutoRefresh();
}

function bindGlobal(){
  $("#filter-button").addEventListener("click",()=>openFilters());
  $("#refresh-button").addEventListener("click",()=>loadOpportunities(true));
  $("#search-input").addEventListener("input",debounce(e=>{state.search=e.target.value.trim();state.page=1;loadOpportunities()},320));
  $("#sort-select").addEventListener("change",e=>{state.sort=e.target.value;state.page=1;loadOpportunities()});
  $("#contact-button").addEventListener("click",()=>openWhatsApp("Olá! Gostaria de saber mais sobre as licitações disponíveis"));
  $("#loan-button").addEventListener("click",openLoanModal);
  $("#help-link").addEventListener("click",openHelpModal);
  $("#footer-help").addEventListener("click",openHelpModal);
  $("#chat-form").addEventListener("submit",sendChat);
  $("#chat-expand").addEventListener("click",toggleChatSize);
  initSidebarResizer();
  document.addEventListener("click",handleDocumentClick);
  document.addEventListener("keydown",e=>{if(e.key==="Escape"){closeModal();if($(".assistant-card.expanded"))toggleChatSize()}if(e.key==="/"&&!["INPUT","TEXTAREA"].includes(document.activeElement.tagName)){e.preventDefault();$("#search-input").focus()}});
  $("#search-input").value=state.search;
  $("#sort-select").value=state.sort;
}

function showView(view){
  state.view=view;
  $$(".nav-link").forEach(x=>x.classList.toggle("active",x.dataset.view===view));
  $("#opportunities-view").classList.toggle("hidden",!["opportunities","saved"].includes(view));
  $("#saved-view").classList.add("hidden");
  $("#breadcrumb-current").textContent=({opportunities:"Oportunidades",saved:"Salvas"})[view]||"Oportunidades";
  if(view==="saved"){state.saved=readSaved();renderOpportunities(state.opportunities.filter(x=>state.saved.includes(x.id)))}
  if(view==="opportunities"){renderOpportunities(state.opportunities);renderPagination()}
}
function handleDocumentClick(e){
  const nav=e.target.closest("[data-view]");if(nav){showView(nav.dataset.view);toggleMobileSidebar(true);return}
  if(e.target.closest("[data-demo-doc]")){toast("Este é um exemplo demonstrativo. O documento original não está disponível.","error");return}
  const download=e.target.closest("[data-download-id]");if(download){downloadEdital(download);return}
  const filter=e.target.closest("[data-open-filters]");if(filter){openFilters(filter.dataset.openFilters);return}
  const save=e.target.closest("[data-save-id]");if(save){toggleSaved(save.dataset.saveId);return}
  const cardChat=e.target.closest("[data-card-chat]");if(cardChat){openOpportunityChat(cardChat.dataset.cardChat);return}
  const chatOpportunity=e.target.closest("[data-chat-opportunity]");if(chatOpportunity){showView("opportunities");setTimeout(()=>{const card=document.getElementById(`op-${encodeURIComponent(chatOpportunity.dataset.chatOpportunity)}`);card?.scrollIntoView({behavior:"smooth",block:"center"});card?.classList.add("chat-highlight");setTimeout(()=>card?.classList.remove("chat-highlight"),1600)},80);return}
  const items=e.target.closest("[data-items-id]");if(items){openItems(items.dataset.itemsId,items.dataset.title,items.dataset.org,items.dataset.number);return}
  const close=e.target.closest("[data-close-modal]");
  if(close&&!close.classList.contains("modal-backdrop"))closeModal();
}
async function downloadEdital(button){
  const id=button.dataset.downloadId;
  if(!id||button.dataset.busy)return;
  const original=button.innerHTML;
  button.dataset.busy="1";button.disabled=true;button.textContent="Baixando…";
  try{
    const response=await fetch(`/api/opportunities/${encodeURIComponent(id)}/download`);
    if(!response.ok){let message="Não foi possível baixar o edital agora.";try{const data=await response.json();message=data.error||message}catch{}throw new Error(message)}
    const blob=await response.blob();
    const name=responseFilename(response.headers.get("Content-Disposition"))||`edital-${id.replace(/[^a-z0-9]+/gi,"-")}.pdf`;
    const link=document.createElement("a");link.href=URL.createObjectURL(blob);link.download=name;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(link.href),4000);
    toast("Download do edital iniciado.");
  }catch(error){toast(error.message,"error")}
  finally{delete button.dataset.busy;button.disabled=false;button.innerHTML=original}
}
function responseFilename(header){
  if(!header)return"";
  const encoded=/filename\*=UTF-8''([^;]+)/i.exec(header);
  if(encoded){try{return decodeURIComponent(encoded[1].trim())}catch{}}
  const plain=/filename="?([^";]+)"?/i.exec(header);
  return plain?plain[1].trim():"";
}
function toggleMobileSidebar(forceClose=false){const sidebar=$("#sidebar");const open=sidebar.classList.contains("open");sidebar.classList.toggle("open",!open&&!forceClose);$("#sidebar-scrim").classList.toggle("open",!open&&!forceClose)}
function toggleSaved(id){const s=new Set(readSaved());s.has(id)?s.delete(id):s.add(id);state.saved=[...s];localStorage.setItem(SAVED_KEY,JSON.stringify(state.saved));if(state.view==="saved")renderOpportunities(state.opportunities.filter(x=>state.saved.includes(x.id)));else renderOpportunities(state.opportunities);toast(s.has(id)?"Oportunidade salva.":"Oportunidade removida das salvas.")}

async function loadOpportunities(force=false,quiet=false){
  if(state.loading){if(force)state.pendingLoad=true;return}
  state.loading=true;
  const list=$("#opportunity-list");
  if(!quiet&&list)list.innerHTML=`<div class="loading-state"><div><div class="spinner"></div><p>Consultando oportunidades no PNCP…</p></div></div>`;
  const query=new URLSearchParams();
  if(state.search)query.set("q",state.search);
  if(state.city)query.set("city",state.city);
  if(state.sort)query.set("sort",state.sort);
  query.set("page",String(state.page));
  query.set("period",state.period);
  state.states.forEach(code=>query.append("state",code));
  state.products.forEach(product=>query.append("product",product));
  if(force)query.set("refresh","1");
  try{
    const result=await api(`/api/opportunities?${query}`);
    state.opportunities=result.opportunities||[];
    state.pages=result.pages||1;
    state.total=typeof result.total==="number"?result.total:state.opportunities.length;
    const banner=$("#source-label").closest(".source-banner");
    $("#source-label").textContent=result.demo?"Exemplos de demonstração · PNCP indisponível":result.stale?"PNCP sem resposta agora · exibindo a última consulta":state.period==="future"?"Licitações futuras · abertura de propostas adiante":"Dados oficiais consultados no PNCP";
    banner.classList.toggle("demo-banner",!!(result.demo||result.stale));
    $("#source-updated").textContent=result.updated_at?`Dados de ${new Date(result.updated_at).toLocaleTimeString("pt-BR",{hour:"2-digit",minute:"2-digit",second:"2-digit"})}`:"";
    banner.title=result.warning||"A lista se atualiza sozinha a cada minuto. O PNCP é reconsultado em segundo plano a cada 3 minutos; use Atualizar para forçar agora.";
    if(result.warning)toast(result.warning,"error");
    updateMetrics(state.opportunities,result.total);
    renderOpportunities(state.view==="saved"?state.opportunities.filter(x=>state.saved.includes(x.id)):state.opportunities);
    $("#results-label").textContent=state.opportunities.length?`${state.opportunities.length} nesta página`:"";
    $("#nav-match-count").textContent=String(state.opportunities.filter(x=>x.match).length||"");
    renderFilterChips();
  }catch(error){
    if(!quiet&&list){list.innerHTML=`<div class="error-state"><div class="empty-state"><div><div class="empty-icon">!</div><h3>Não foi possível carregar os editais</h3><p>${esc(error.message)}</p><button id="retry-opportunities" class="button button-secondary button-small">Tentar novamente</button></div></div></div>`;$("#retry-opportunities").addEventListener("click",()=>loadOpportunities(true))}
    else toast(error.message,"error");
  }finally{
    state.loading=false;
    if(state.pendingLoad){state.pendingLoad=false;loadOpportunities(true,true)}
  }
}
function startAutoRefresh(){
  setInterval(()=>{
    if(document.visibilityState!=="visible"||state.loading||chatTyping)return;
    if(!["opportunities","saved"].includes(state.view))return;
    loadOpportunities(false,true);
  },REFRESH_MS);
}
function updateMetrics(records,total){$("#metric-total").textContent=String(total??records.length);$("#metric-matches").textContent=String(records.filter(x=>x.match).length);const sum=records.reduce((s,x)=>s+(typeof x.valor==="number"&&x.valor>0?x.valor:0),0);$("#metric-value").textContent=sum?new Intl.NumberFormat("pt-BR",{style:"currency",currency:"BRL",notation:sum>10000000?"compact":"standard",maximumFractionDigits:sum>10000000?1:0}).format(sum):"—"}
function updateProfileTags(){
  $("#profile-tags").innerHTML=state.products.length?state.products.slice(0,3).map(p=>`<span class="catalog-tag">${esc(p)}</span>`).join("")+(state.products.length>3?`<span class="catalog-tag">+${state.products.length-3}</span>`:""):'<span class="catalog-tag">Adicione produtos</span>';
  renderFilterChips();
}

function renderOpportunities(records){
  const list=$("#opportunity-list");if(!list)return;
  if(!records.length){
    const emptyPeriod=state.period==="future"&&state.view!=="saved";
    const title=state.view==="saved"?"Nenhuma oportunidade salva":emptyPeriod?"Nenhuma licitação futura encontrada agora":"Nenhuma oportunidade encontrada";
    const copy=state.view==="saved"?"Salve editais para encontrá-los rapidamente por aqui.":emptyPeriod?"Nenhuma contratação publicada nos últimos dias tem abertura de propostas futura com esses filtros. Tente ampliar a região ou volte mais tarde.":state.products.length?"Nenhum edital publicado agora foi encontrado para os itens do seu perfil. A busca usa o índice do PNCP (objeto e itens), mas visita só os resultados mais recentes. Tente outro item, amplie a região ou atualize a lista.":state.search?"A API do PNCP não pesquisa texto em todo o acervo: a busca percorre os editais carregados agora. Escolha um estado ou um produto para restringir e encontrar mais.":"Experimente outros termos ou amplie os filtros para encontrar mais oportunidades.";
    list.innerHTML=`<div class="empty-state"><div><span class="empty-icon"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg></span><h3>${esc(title)}</h3><p>${esc(copy)}</p>${state.view==="saved"?'<button class="button button-secondary button-small" data-view="opportunities">Ver oportunidades</button>':'<button class="button button-secondary button-small" data-open-filters="region">Revisar filtros</button>'}</div></div>`;
    $("#pagination").innerHTML="";renderFilterChips();return;
  }
  list.innerHTML=records.map(renderOpportunity).join("");
  renderPagination();
  renderFilterChips();
}
function renderPagination(){
  const container=$("#pagination");if(!container||state.view==="saved"||state.pages<=1){if(container)container.innerHTML="";return}
  const windowStart=Math.max(1,Math.min(state.page-2,state.pages-4)),windowEnd=Math.min(state.pages,windowStart+4);
  let html=`<button type="button" data-page="${Math.max(1,state.page-1)}" ${state.page===1?"disabled":""}>‹</button>`;
  for(let p=windowStart;p<=windowEnd;p++)html+=`<button type="button" data-page="${p}" class="${p===state.page?"current":""}">${p}</button>`;
  if(windowEnd<state.pages)html+=`<span>… ${state.pages}</span>`;
  html+=`<button type="button" data-page="${Math.min(state.pages,state.page+1)}" ${state.page===state.pages?"disabled":""}>›</button>`;
  container.innerHTML=html;
  $$("[data-page]",container).forEach(b=>b.addEventListener("click",()=>{state.page=Number(b.dataset.page);loadOpportunities();$("#opportunities-view").scrollIntoView({behavior:"smooth",block:"start"})}));
}
function renderOpportunity(item){
  const isSaved=state.saved.includes(item.id),demo=!!item.demo,location=[item.cidade,item.uf].filter(Boolean).join(" / ")||"Localidade não informada";
  const url=item.url&&!demo?item.url:"";
  const future=state.period==="future";
  return `<article class="opportunity-card ${demo?"demo-card":""}" id="op-${encodeURIComponent(item.id)}">
    <div class="card-top"><span class="modality-tag">${esc(item.modalidade||"Modalidade não informada")}</span><span class="status-tag">${esc(item.status||"Status não informado")}</span><span class="origin-tag">${esc(item.origem||"PNCP")}</span>${future?'<span class="future-tag">Abertura futura</span>':""}${item.match?`<span class="match-tag" title="Este edital cita o item do seu perfil"><svg viewBox="0 0 24 24"><path d="m5 12 4 4L19 6"/></svg>${esc(item.matched_product?"Atende: "+item.matched_product:"Compatível com seu perfil")}</span>`:""}<div class="card-corner"><button class="save-button ${isSaved?"saved":""}" type="button" aria-label="${isSaved?"Remover dos salvos":"Salvar oportunidade"}" data-save-id="${esc(item.id)}"><svg viewBox="0 0 24 24"><path d="m12 17.3 6.2 3.7-1.6-7.1L22 9l-7.2-.6L12 2 9.2 8.4 2 9l5.4 4.9L5.8 21z"/></svg></button><button class="card-chat-button" type="button" data-card-chat="${esc(item.id)}" title="Perguntar à IA sobre esta oportunidade" aria-label="Perguntar à IA sobre esta oportunidade"><svg viewBox="0 0 24 24"><path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8A8.5 8.5 0 0 1 8.7 3.9a8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8v.5Z"/></svg><span>IA</span></button></div></div>
    <h3>${esc(item.titulo||"Objeto não informado")}</h3><p class="agency-name">${esc(item.orgao||"Órgão não informado")}</p>
    <div class="card-details"><div class="detail-item"><span>Cidade / UF</span><strong>${esc(location)}</strong></div><div class="detail-item"><span>Nº do edital</span><strong>${esc(item.numero||"Não informado")}</strong></div><div class="detail-item"><span>${future?"Abertura das propostas":"Encerramento das propostas"}</span><strong class="highlight">${esc(item.indexed&&!item.sessao?"Consultar no PNCP":dateTimeFmt(future&&item.abertura?item.abertura:item.sessao))}</strong></div><div class="detail-item"><span>Valor estimado</span><strong class="value">${esc(money(item.valor))}</strong></div><div class="detail-item"><span>ID PNCP</span><strong>${esc(item.pncp||"Não informado")}</strong></div></div>
    <div class="card-footer"><div class="card-buttons"><button class="button button-primary button-small card-button" type="button" ${demo?"data-demo-doc":`data-download-id="${esc(item.id)}" title="Baixar o arquivo do edital publicado pelo órgão"`}><svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5M12 15V3"/></svg>Baixar edital</button><button class="button button-secondary button-small card-button" type="button" data-items-id="${esc(item.id)}" data-title="${esc(item.titulo||"Objeto não informado")}" data-org="${esc(item.orgao||"Órgão não informado")}" data-number="${esc(item.numero||"Não informado")}">Ver itens</button>${url?`<a class="button button-secondary button-small card-button" href="${esc(url)}" target="_blank" rel="noopener noreferrer">Site oficial ↗</a>`:`<button class="button button-secondary button-small card-button" type="button" disabled title="Link oficial não disponibilizado">Site oficial ↗</button>`}</div><span class="card-source-meta">${demo?"EXEMPLO IDENTIFICADO COMO DEMONSTRAÇÃO":item.documentos==null?"Documentos: consulte a página oficial":"+"+item.documentos+" documento(s)"}</span></div>
  </article>`;
}
function renderFilterChips(){
  const chips=[];
  if(state.period==="future")chips.push({key:"period",label:"Licitações futuras"});
  state.states.forEach(code=>chips.push({key:`state:${code}`,label:code}));
  if(state.city)chips.push({key:"city",label:`Município: ${state.city}`});
  $("#filter-chips").innerHTML=chips.map(chip=>`<span class="filter-chip">${esc(chip.label)}<button type="button" data-remove-filter="${esc(chip.key)}" aria-label="Remover filtro">×</button></span>`).join("");
  $("#active-filter-dot").classList.toggle("hidden",!chips.length&&!state.products.length);
  $$("[data-remove-filter]").forEach(btn=>btn.addEventListener("click",()=>{
    const key=btn.dataset.removeFilter;
    if(key==="period")state.period="open";
    else if(key==="city")state.city="";
    else if(key.startsWith("state:"))state.states=state.states.filter(code=>code!==key.slice(6));
    state.page=1;saveFiltersLocally();loadOpportunities();
  }));
}

function openModal(content,wide=false){$("#modal-root").innerHTML=`<div class="modal-backdrop" data-close-modal><section class="modal ${wide?"modal-wide":""}" role="dialog" aria-modal="true">${content}</section></div>`;$(".modal-backdrop").addEventListener("click",e=>{if(e.target.classList.contains("modal-backdrop"))closeModal()});document.body.style.overflow="hidden";setTimeout(()=>$(".modal-close")?.focus(),0)}
function closeModal(){if(state.filterSnapshot){state.products=state.filterSnapshot.products;state.states=state.filterSnapshot.states;state.city=state.filterSnapshot.city;state.period=state.filterSnapshot.period;state.filterSnapshot=null;updateProfileTags()}oppChat={record:null,history:[],typing:false};$("#modal-root").innerHTML="";document.body.style.overflow=""}

function openFilters(tab="region"){
  state.filterSnapshot={products:[...state.products],states:[...state.states],city:state.city,period:state.period};
  state.filterTab=["products","period"].includes(tab)?tab:"region";
  const modal=`<div class="modal-header"><div><span class="eyebrow">PERSONALIZE SUA PESQUISA</span><h2>Filtros</h2><p>Escolha onde procurar, o que sua empresa oferece e o momento das licitações.</p></div><button class="modal-close" data-close-modal aria-label="Fechar">×</button></div>
  <div class="modal-body"><div class="filter-tabs"><button class="filter-tab ${state.filterTab==="region"?"active":""}" data-filter-tab="region">Região e localização</button><button class="filter-tab ${state.filterTab==="products"?"active":""}" data-filter-tab="products">Produtos e serviços</button><button class="filter-tab ${state.filterTab==="period"?"active":""}" data-filter-tab="period">Momento da licitação</button></div>
  <div id="region-filter-panel" class="${state.filterTab==="region"?"":"hidden"}"><div class="region-section"><label class="check-option"><input id="filter-all-brazil" type="checkbox" ${state.states.length?"":"checked"}>Brasil inteiro</label></div><div class="region-section"><h3>Selecione por região</h3><div class="region-grid">${Object.entries(REGIONS).map(([region])=>`<label class="check-option"><input type="checkbox" data-region-check="${esc(region)}" ${REGIONS[region].every(s=>state.states.includes(s))?"checked":""}>${esc(region)}</label>`).join("")}</div></div><div class="region-section"><h3>Ou escolha um ou mais estados</h3><div class="region-grid">${STATES.map(([code,name])=>`<label class="check-option"><input type="checkbox" data-state-check="${code}" ${state.states.includes(code)?"checked":""}>${code} <span>${name}</span></label>`).join("")}</div></div><div class="region-section"><h3>Município</h3><input id="filter-city" class="modal-search" placeholder="Digite o nome do município" value="${esc(state.city)}"></div></div>
  <div id="products-filter-panel" class="${state.filterTab==="products"?"":"hidden"}"><input id="filter-product-search" class="modal-search filter-search" type="search" placeholder="Buscar produto ou serviço"><div id="filter-product-list" class="filter-product-list">${renderFilterProducts("")}</div><div id="filter-selected-products" class="selected-chips">${renderFilterProductChips()}</div></div>
  <div id="period-filter-panel" class="${state.filterTab==="period"?"":"hidden"}"><div class="region-section"><h3>Momento da licitação</h3><div class="period-options"><label class="check-option"><input type="radio" name="filter-period" value="open" ${state.period==="open"?"checked":""}><span><strong>Propostas abertas</strong><small>Contratações recebendo propostas agora.</small></span></label><label class="check-option"><input type="radio" name="filter-period" value="future" ${state.period==="future"?"checked":""}><span><strong>Licitações futuras</strong><small>Publicadas recentemente, com abertura de propostas em uma data futura.</small></span></label></div></div><p class="filter-hint">As licitações futuras são buscadas entre as contratações publicadas no PNCP nos últimos dias. Se não houver nenhuma com abertura adiante, a lista aparece vazia — nunca inventamos editais.</p></div></div>
  <div class="modal-footer"><button class="button button-secondary" data-close-modal>Cancelar</button><button id="save-filters" class="button button-primary">Salvar alterações</button></div>`;
  openModal(modal,true);
  $$("[data-filter-tab]").forEach(b=>b.addEventListener("click",()=>{state.filterTab=b.dataset.filterTab;$$("[data-filter-tab]").forEach(x=>x.classList.toggle("active",x===b));$("#region-filter-panel").classList.toggle("hidden",state.filterTab!=="region");$("#products-filter-panel").classList.toggle("hidden",state.filterTab!=="products");$("#period-filter-panel").classList.toggle("hidden",state.filterTab!=="period")}));
  $("#filter-all-brazil").addEventListener("change",e=>{if(e.target.checked){state.states=[];$$("[data-state-check]").forEach(x=>x.checked=false);$$("[data-region-check]").forEach(x=>x.checked=false)}});
  $$("[data-state-check]").forEach(c=>c.addEventListener("change",()=>{state.states=$$("[data-state-check]:checked").map(x=>x.dataset.stateCheck);$("#filter-all-brazil").checked=!state.states.length}));
  $$("[data-region-check]").forEach(c=>c.addEventListener("change",()=>{const codes=REGIONS[c.dataset.regionCheck];state.states=c.checked?[...new Set([...state.states,...codes])]:state.states.filter(x=>!codes.includes(x));$$("[data-state-check]").forEach(x=>x.checked=state.states.includes(x));$("#filter-all-brazil").checked=!state.states.length}));
  $("#filter-city").addEventListener("input",e=>{state.city=e.target.value});
  $$("input[name=filter-period]").forEach(radio=>radio.addEventListener("change",()=>{state.period=radio.value}));
  $("#filter-product-search").addEventListener("input",e=>{$("#filter-product-list").innerHTML=renderFilterProducts(e.target.value);bindFilterProductButtons()});
  bindFilterProductButtons();
  $("#save-filters").addEventListener("click",saveFilters);
}
function renderFilterProducts(query){const q=query.toLocaleLowerCase("pt-BR");return Object.entries(state.catalog).map(([cat,items])=>{const matches=items.filter(x=>x.toLocaleLowerCase("pt-BR").includes(q));if(!matches.length)return"";return`<div class="filter-product-category">${esc(cat)}</div><div class="filter-product-grid">${matches.map(x=>`<button type="button" class="catalog-option ${state.products.includes(x)?"selected":""}" data-filter-product="${esc(x)}">${esc(x)}</button>`).join("")}</div>`}).join("")+(q&&!Object.values(state.catalog).flat().some(x=>x.toLocaleLowerCase("pt-BR").includes(q))?`<div class="filter-product-category">Adicionar item personalizado</div><div class="filter-product-grid"><button type="button" class="catalog-option" data-filter-product="${esc(query)}">+ ${esc(query)}</button></div>`:"")}
function renderFilterProductChips(){return state.products.map(p=>`<span class="selected-chip">${esc(p)}<button type="button" aria-label="Remover ${esc(p)}" data-remove-filter-product="${esc(p)}">×</button></span>`).join("")}
function bindFilterProductButtons(){$$("[data-filter-product]").forEach(b=>b.addEventListener("click",()=>{const p=b.dataset.filterProduct;if(state.products.includes(p))state.products=state.products.filter(x=>x!==p);else state.products.push(p);$("#filter-product-list").innerHTML=renderFilterProducts($("#filter-product-search").value);$("#filter-selected-products").innerHTML=renderFilterProductChips();bindFilterProductButtons()}));bindRemoveProductButtons()}
function bindRemoveProductButtons(){$$("[data-remove-filter-product]").forEach(b=>b.addEventListener("click",()=>{state.products=state.products.filter(x=>x!==b.dataset.removeFilterProduct);$("#filter-product-list").innerHTML=renderFilterProducts($("#filter-product-search").value);$("#filter-selected-products").innerHTML=renderFilterProductChips();bindFilterProductButtons()}))}
async function saveFilters(){
  state.page=1;state.filterSnapshot=null;saveFiltersLocally();
  closeModal();updateProfileTags();
  await loadOpportunities(true);
  toast(state.period==="future"?"Filtros aplicados · buscando licitações futuras.":"Filtros aplicados.");
}

async function openItems(id,title,org,number){
  openModal(`<div class="modal-header"><div><span class="eyebrow">DETALHES DA OPORTUNIDADE</span><h2>Itens da licitação</h2><p>${esc(org)} · Edital ${esc(number)}</p></div><button class="modal-close" data-close-modal aria-label="Fechar">×</button></div><div class="modal-body"><div class="items-intro"><strong>${esc(title)}</strong><span>Os itens abaixo são apresentados conforme os dados disponíveis na fonte oficial.</span></div><div id="items-content" class="loading-state"><div class="spinner"></div></div><p class="items-explainer">Dica: quantidades e valores estimados são referências publicadas no processo. Leia o edital completo e seus anexos para conferir especificações, prazos e condições de participação.</p><section id="documents-section" class="documents-section hidden"><h3>Documentos do processo</h3><div id="documents-content"></div></section></div>`,true);
  try{
    const result=await api(`/api/opportunities/${encodeURIComponent(id)}/items`);
    const box=$("#items-content");if(!box)return;
    if(result.unavailable){box.className="empty-state";box.innerHTML=`<div><h3>Itens não disponibilizados</h3><p>${esc(result.message||"A fonte oficial não disponibilizou os itens desta contratação.")}</p></div>`}
    else if(!result.items?.length){box.className="empty-state";box.innerHTML=`<div><h3>Nenhum item informado</h3><p>A fonte oficial não apresentou itens nesta consulta.</p></div>`}
    else{box.className="items-table-wrap";box.innerHTML=`<table class="items-table"><thead><tr><th>Descrição do item</th><th>Quantidade</th><th>Unidade</th><th>Valor unitário</th><th>Valor total</th></tr></thead><tbody>${result.items.map(i=>`<tr><td class="item-description">${esc(i.descricao||"Não informado")}<span class="item-plain">${i.natureza==="Serviço"?"O órgão solicita a prestação deste serviço; confira o escopo detalhado no edital.":i.natureza==="Material"?"O órgão solicita o fornecimento deste produto; confira as especificações no edital.":"Confira no edital se o item se refere a um produto ou serviço."}</span></td><td>${esc(i.quantidade??"Não informado")}</td><td>${esc(i.unidade||"Não informado")}</td><td>${esc(money(i.unitario))}</td><td>${esc(money(i.total))}</td></tr>`).join("")}</tbody></table>`}
    const documents=result.documents||[];
    if(documents.length){$("#documents-section").classList.remove("hidden");$("#documents-content").innerHTML=documents.map(d=>d.url?`<a class="document-link" href="${esc(d.url)}" target="_blank" rel="noopener noreferrer">${esc(d.title)} ↗</a>`:`<div class="document-link unavailable">${esc(d.title)} · link indisponível</div>`).join("");const card=document.getElementById(`op-${encodeURIComponent(id)}`);const meta=card?.querySelector(".card-source-meta");if(meta)meta.textContent=`+${documents.length} documento(s) na fonte oficial`}
  }catch(e){const box=$("#items-content");if(box){box.className="error-state";box.textContent=e.message}}
}

let oppChat={record:null,history:[],typing:false};
function findOpportunity(id){return state.opportunities.find(item=>item.id===id)||null}
function appendOppMessage(text,who){
  const box=$("#opp-chat-messages");if(!box)return null;
  const node=document.createElement("div");node.className=`chat-message ${who==="user"?"user-message":"bot-message"}`;
  if(who==="user")node.textContent=text;
  box.append(node);chatScroll(box);return node;
}
function opportunityFacts(record){
  const location=[record.cidade,record.uf].filter(Boolean).join(" / ")||"Não informado";
  return `<div class="opp-chat-facts"><span><small>Órgão</small><strong>${esc(record.orgao||"Não informado")}</strong></span><span><small>Local</small><strong>${esc(location)}</strong></span><span><small>Encerramento</small><strong>${esc(dateTimeFmt(record.sessao))}</strong></span><span><small>Valor estimado</small><strong>${esc(money(record.valor))}</strong></span></div>`;
}
function openOpportunityChat(id){
  const record=findOpportunity(id);
  if(!record){toast("Não foi possível abrir o chat deste edital. Atualize a lista e tente de novo.","error");return}
  oppChat={record,history:[],typing:false};
  const suggestions=["Resuma este edital","Quais são os prazos?","Quais itens foram publicados?","Como participar?",...(state.products.length?["Por que apareceu no meu filtro?"]:[])];
  openModal(`<div class="modal-header"><div><span class="eyebrow">CONVERSA SOBRE ESTE EDITAL</span><h2 class="opp-chat-title">${esc(record.titulo||"Objeto não informado")}</h2><p>${esc(record.modalidade||"Modalidade não informada")} · Edital ${esc(record.numero||"não informado")}${record.demo?" · exemplo demonstrativo":""}</p></div><button class="modal-close" data-close-modal aria-label="Fechar">×</button></div>
  <div class="modal-body opp-chat-body">${opportunityFacts(record)}
    <div id="opp-chat-messages" class="chat-messages opp-chat-messages"><div class="chat-message bot-message">Pode perguntar à vontade: prazos, itens publicados, valor estimado, como participar — ou por que este edital apareceu no seu filtro. Respondo só com os dados deste processo; o edital oficial continua sendo a referência.</div></div>
    <div class="opp-chat-suggestions">${suggestions.map(question=>`<button type="button" data-opp-question="${esc(question)}">${esc(question)}</button>`).join("")}</div>
    <form id="opp-chat-form" class="chat-form"><input id="opp-chat-input" aria-label="Pergunte sobre este edital" placeholder="Pergunte sobre este edital…" maxlength="1200"><button type="submit" aria-label="Enviar pergunta"><svg viewBox="0 0 24 24"><path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/></svg></button></form>
    <small class="chat-disclaimer">Respostas geradas a partir dos dados públicos deste edital. Confirme requisitos e condições no documento oficial.</small>
  </div>`,true);
  $(".modal").classList.add("opp-chat-modal");
  $("#opp-chat-form").addEventListener("submit",sendOpportunityChat);
  $$("[data-opp-question]").forEach(button=>button.addEventListener("click",()=>{const input=$("#opp-chat-input");input.value=button.dataset.oppQuestion;sendOpportunityChat()}));
  setTimeout(()=>$("#opp-chat-input")?.focus(),40);
  chatScroll($("#opp-chat-messages"));
}
async function sendOpportunityChat(e){
  e?.preventDefault();
  const input=$("#opp-chat-input"),message=input?.value.trim();
  if(!message||!oppChat.record)return;
  input.value="";
  appendOppMessage(message,"user");
  const box=$("#opp-chat-messages");
  const loading=document.createElement("div");loading.className="chat-message bot-message loading-message";
  loading.innerHTML='<span class="typing-dots"><i></i><i></i><i></i></span>';box.append(loading);chatScroll(box);
  const history=oppChat.history.slice(-8);
  try{
    const result=await post("/api/chat",{message,products:state.products,opportunity:oppChat.record,history});
    loading.remove();
    oppChat.history.push({role:"user",content:message},{role:"assistant",content:result.answer||""});
    typeMessage(appendOppMessage("","bot"),result.answer||"",null);
  }catch(error){
    loading.remove();
    typeMessage(appendOppMessage("","bot"),error.message,null);
  }
}

function openWhatsApp(message){window.open(`https://wa.me/5548991579450?text=${encodeURIComponent(message)}`,"_blank","noopener,noreferrer")}
function openLoanModal(){openModal(`<div class="modal-header"><div><span class="eyebrow">PARCERIA PARA SUA EMPRESA</span><h2>Conte com a gente</h2></div><button class="modal-close" data-close-modal aria-label="Fechar">×</button></div><div class="modal-body"><div class="help-copy"><p>Está necessitando de empréstimo barato para alavancar sua empresa? Está precisando de ajuda de analistas para vender licitações mais facilmente? Fale com a gente!</p><p>Nossa equipe pode conversar com você sobre crédito e apoio especializado para participar de licitações.</p></div><button id="loan-whatsapp" class="whatsapp-cta"><svg viewBox="0 0 24 24"><path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8A8.5 8.5 0 0 1 8.7 3.9a8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8v.5Z"/></svg>FALAR COM UM ESPECIALISTA NO WHATSAPP</button></div>`,false);$("#loan-whatsapp").addEventListener("click",()=>openWhatsApp("Olá! Venho da sua agência e estou interessado na sua ajuda"))}
function openHelpModal(){openModal(`<div class="modal-header"><div><span class="eyebrow">ESTAMOS AQUI PARA AJUDAR</span><h2>Fale com a Licitara</h2><p>Atendimento e dúvidas sobre licitações.</p></div><button class="modal-close" data-close-modal aria-label="Fechar">×</button></div><div class="modal-body"><div class="help-copy"><p>Nossa equipe pode ajudar você a entender a plataforma e os próximos passos para acompanhar uma oportunidade.</p><p>Atendimento pelo WhatsApp: segunda a sexta, em horário comercial.</p></div><button id="help-whatsapp" class="whatsapp-cta">CONVERSAR PELO WHATSAPP</button></div>`,false);$("#help-whatsapp").addEventListener("click",()=>openWhatsApp("Olá! Gostaria de auxílio para aprender sobre licitações"))}

let chatTyping=null;
function chatScroll(box=$("#chat-messages")){if(box)box.scrollTop=box.scrollHeight}
let chatPlaceholder=null;
const SIDEBAR_KEY="licitara:sidebar-width";
function sidebarWidthBounds(){const min=240;const max=Math.max(min,Math.min(560,Math.round(window.innerWidth*0.45)));return{min,max}}
function setSidebarWidth(value,{persist=false}={}){
  const {min,max}=sidebarWidthBounds();
  const width=Math.round(Math.min(max,Math.max(min,Number(value)||320)));
  document.documentElement.style.setProperty("--sidebar-w",`${width}px`);
  document.documentElement.classList.add("chat-resized");
  if(persist)try{localStorage.setItem(SIDEBAR_KEY,String(width))}catch{}
  return width;
}
function restoreSidebarWidth(){
  let saved=0;
  try{saved=parseInt(localStorage.getItem(SIDEBAR_KEY)||"",10)}catch{}
  if(Number.isFinite(saved)&&saved>0)setSidebarWidth(saved);
}
function resetSidebarWidth(){
  document.documentElement.style.removeProperty("--sidebar-w");
  document.documentElement.classList.remove("chat-resized");
  try{localStorage.removeItem(SIDEBAR_KEY)}catch{}
}
function initSidebarResizer(){
  const handle=$("#sidebar-resizer");const sidebar=$("#sidebar");if(!handle||!sidebar)return;
  restoreSidebarWidth();
  let startX=0,startWidth=0,currentWidth=sidebarWidthBounds().min,dragging=false;
  const apply=value=>{currentWidth=setSidebarWidth(value);return currentWidth};
  const stop=e=>{
    if(!dragging)return;
    dragging=false;
    document.body.classList.remove("sidebar-resizing");
    handle.classList.remove("dragging");
    try{handle.releasePointerCapture(e.pointerId)}catch{}
    setSidebarWidth(currentWidth,{persist:true});
  };
  handle.addEventListener("pointerdown",e=>{
    if(e.button!==0)return;
    dragging=true;startX=e.clientX;startWidth=sidebar.getBoundingClientRect().width;
    currentWidth=startWidth;
    document.body.classList.add("sidebar-resizing");
    handle.classList.add("dragging");
    try{handle.setPointerCapture(e.pointerId)}catch{}
    e.preventDefault();
  });
  handle.addEventListener("pointermove",e=>{if(dragging)apply(startWidth+(e.clientX-startX))});
  handle.addEventListener("pointerup",stop);
  handle.addEventListener("pointercancel",stop);
  handle.addEventListener("dblclick",resetSidebarWidth);
  handle.addEventListener("keydown",e=>{
    const step=e.shiftKey?40:16;
    const width=sidebar.getBoundingClientRect().width;
    if(e.key==="ArrowLeft"){apply(width-step);setSidebarWidth(currentWidth,{persist:true});e.preventDefault()}
    else if(e.key==="ArrowRight"){apply(width+step);setSidebarWidth(currentWidth,{persist:true});e.preventDefault()}
    else if(e.key==="Home"){resetSidebarWidth();e.preventDefault()}
  });
  window.addEventListener("resize",()=>{
    if(!document.documentElement.classList.contains("chat-resized"))return;
    const width=parseFloat(document.documentElement.style.getPropertyValue("--sidebar-w"))||320;
    apply(width);
  });
}
function toggleChatSize(){
  const card=$(".assistant-card");if(!card)return;
  const expanded=!card.classList.contains("expanded");
  if(expanded){
    chatPlaceholder=document.createElement("div");
    chatPlaceholder.className="chat-placeholder";
    card.parentNode.insertBefore(chatPlaceholder,card);
    document.body.append(card);
    card.classList.add("expanded");
  }else{
    card.classList.remove("expanded");
    if(chatPlaceholder){chatPlaceholder.replaceWith(card);chatPlaceholder=null}
  }
  $("#chat-expand").setAttribute("aria-label",expanded?"Recolher assistente":"Ampliar assistente");
  $("#chat-expand").textContent=expanded?"⤡":"⤢";
  if(expanded)$("#chat-input").focus();
  chatScroll();
}
function finishTyping(){if(!chatTyping)return;clearTimeout(chatTyping.timer);chatTyping.node.textContent=chatTyping.text;chatTyping.done?.();chatTyping=null;chatScroll()}
function typeMessage(node,text,done){
  if(!node)return;
  finishTyping();
  node.textContent="";
  const box=node.closest(".chat-messages");
  const caret=document.createElement("span");caret.className="typing-caret";caret.setAttribute("aria-hidden","true");node.append(caret);
  const job={node,text,done:null,index:0,caret,timer:null};
  const step=()=>{
    if(job.index>=text.length){caret.remove();chatTyping=null;done?.();chatScroll(box);return}
    caret.insertAdjacentText("beforebegin",text[job.index]);
    job.index+=1;
    chatScroll(box);
    job.timer=setTimeout(step,12);
  };
  job.start=()=>{job.timer=setTimeout(step,90)};
  chatTyping=job;
  job.start();
}
function appendChat(message,who,opportunities=[]){
  const node=document.createElement("div");
  node.className=`chat-message ${who==="user"?"user-message":"bot-message"}`;
  if(who==="user")node.textContent=message;
  $("#chat-messages").append(node);
  if(who!=="user"&&opportunities.length){
    const links=document.createElement("div");
    links.className="chat-result-links";
    opportunities.slice(0,5).forEach(item=>{const button=document.createElement("button");button.type="button";button.dataset.chatOpportunity=item.id;button.textContent=`Ver oportunidade: ${item.titulo||"Abrir edital"}`;links.append(button)});
    node.append(links);
  }
  chatScroll();
  return node;
}
async function sendChat(e){
  e.preventDefault();
  const input=$("#chat-input"),message=input.value.trim();
  if(!message)return;
  finishTyping();
  input.value="";
  appendChat(message,"user");
  const loading=document.createElement("div");
  loading.className="chat-message bot-message loading-message";
  loading.innerHTML='<span class="typing-dots"><i></i><i></i><i></i></span>';
  $("#chat-messages").append(loading);
  chatScroll();
  try{
    const result=await post("/api/chat",{message,products:state.products});
    loading.remove();
    const node=appendChat("","bot",result.opportunities||[]);
    typeMessage(node,result.answer||"",null);
  }catch(error){
    loading.remove();
    const node=appendChat("","bot");
    typeMessage(node,error.message,null);
  }
}

function debounce(fn,delay){let timer;return(...args)=>{clearTimeout(timer);timer=setTimeout(()=>fn(...args),delay)}}

init();
