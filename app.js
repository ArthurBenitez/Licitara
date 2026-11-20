const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const STATES = [["AC","Acre"],["AL","Alagoas"],["AP","Amapá"],["AM","Amazonas"],["BA","Bahia"],["CE","Ceará"],["DF","Distrito Federal"],["ES","Espírito Santo"],["GO","Goiás"],["MA","Maranhão"],["MT","Mato Grosso"],["MS","Mato Grosso do Sul"],["MG","Minas Gerais"],["PA","Pará"],["PB","Paraíba"],["PR","Paraná"],["PE","Pernambuco"],["PI","Piauí"],["RJ","Rio de Janeiro"],["RN","Rio Grande do Norte"],["RS","Rio Grande do Sul"],["RO","Rondônia"],["RR","Roraima"],["SC","Santa Catarina"],["SP","São Paulo"],["SE","Sergipe"],["TO","Tocantins"]];
const REGIONS = {Norte:["AC","AP","AM","PA","RO","RR","TO"],Nordeste:["AL","BA","CE","MA","PB","PE","PI","RN","SE"],"Centro-Oeste":["DF","GO","MT","MS"],Sudeste:["ES","MG","RJ","SP"],Sul:["PR","RS","SC"]};
const state = {user:null,demoMode:false,catalog:{},signupProducts:[],products:[],states:[],city:"",search:"",sort:"date",page:1,pages:1,total:0,view:"opportunities",adminCompanies:[],adminHistory:[],adminTab:"companies",adminSearch:"",saved:[],opportunities:[],filterTab:"region",filterSnapshot:null,loading:false,allBrazil:false};

function esc(value=""){return String(value).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function initials(name=""){return name.trim().split(/\s+/).slice(0,2).map(x=>x[0]||"").join("").toUpperCase()||"LC";}
function money(value){return typeof value==="number"&&Number.isFinite(value)?value.toLocaleString("pt-BR",{style:"currency",currency:"BRL"}):"Não informado";}
function dateFmt(value){if(!value)return"Não informado";const d=new Date(value);return Number.isNaN(d.getTime())?String(value):d.toLocaleDateString("pt-BR",{day:"2-digit",month:"short",year:"numeric"}).replace(".","");}
function dateTimeFmt(value){if(!value)return"Não informado";const d=new Date(value);return Number.isNaN(d.getTime())?String(value):`${d.toLocaleDateString("pt-BR",{day:"2-digit",month:"short",year:"numeric"}).replace(".","")} · ${d.toLocaleTimeString("pt-BR",{hour:"2-digit",minute:"2-digit"})}`;}
async function api(url,options={}){const response=await fetch(url,{credentials:"same-origin",...options,headers:{"Content-Type":"application/json",...(options.headers||{})}});let data={};try{data=await response.json()}catch{}if(!response.ok)throw new Error(data.error||"Não foi possível concluir a solicitação.");return data;}
function post(url,data){return api(url,{method:"POST",body:JSON.stringify(data)});}
function toast(message,type="success"){const node=document.createElement("div");node.className=`toast ${type==="error"?"error":""}`;node.innerHTML=`<span class="toast-indicator"></span><span>${esc(message)}</span>`;$("#toast-region").append(node);setTimeout(()=>node.remove(),4300);}

async function init(){
  try{const [session,catalog]=await Promise.all([api("/api/me"),api("/api/catalog")]);state.demoMode=session.demo_mode;state.catalog=catalog.categories||{};if(session.user){await acceptUser(session.user)}else showAuth()}catch(e){showAuth();toast("O servidor da plataforma não está disponível. Inicie server.py para continuar.","error")}
  bindGlobal();fillSignupStateSelect();
}

function bindGlobal(){
  $("#login-form").addEventListener("submit",login);
  $("#signup-form").addEventListener("submit",signup);
  $("#show-signup").addEventListener("click",()=>showSignup(true));
  $("#back-login").addEventListener("click",()=>showSignup(false));
  $("#demo-client").addEventListener("click",()=>demoLogin("empresa@licitara.demo","EmpresaDemo#2026"));
  $("#demo-admin").addEventListener("click",()=>demoLogin("admin@licitara.demo","AdminDemo#2026"));
  $("#logout-button").addEventListener("click",logout);
  $("#mobile-menu").addEventListener("click",toggleMobileSidebar);
  $("#sidebar-scrim").addEventListener("click",toggleMobileSidebar);
  $("#filter-button").addEventListener("click",openFilters);
  $("#refresh-button").addEventListener("click",()=>loadOpportunities(true));
  $("#search-input").addEventListener("input",debounce(e=>{state.search=e.target.value.trim();state.page=1;loadOpportunities()},320));
  $("#sort-select").addEventListener("change",e=>{state.sort=e.target.value;state.page=1;loadOpportunities()});
  $("#contact-button").addEventListener("click",()=>openWhatsApp("Olá! Minha empresa gostaria de auxílio para aprender sobre licitações"));
  $("#loan-button").addEventListener("click",openLoanModal);
  $("#help-link").addEventListener("click",openHelpModal);
  $("#footer-help").addEventListener("click",openHelpModal);
  $("#profile-button").addEventListener("click",()=>openWhatsApp("Olá! Preciso de ajuda com minha conta na Licitara."));
  $("#chat-form").addEventListener("submit",sendChat);
  $("#signup-product-search").addEventListener("input",renderSignupCatalog);
  $("#signup-form").elements.cnpj.addEventListener("input",e=>{e.target.value=maskCnpj(e.target.value)});
  $("#signup-form").elements.phone.addEventListener("input",e=>{e.target.value=maskPhone(e.target.value)});
  document.addEventListener("click",handleDocumentClick);
  document.addEventListener("keydown",e=>{if(e.key==="Escape")closeModal();if(e.key==="/"&&!["INPUT","TEXTAREA"].includes(document.activeElement.tagName)&&!$("#app-view").classList.contains("hidden")){e.preventDefault();$("#search-input").focus()}});
}

function showAuth(){ $("#app-view").classList.add("hidden");$("#auth-view").classList.remove("hidden");$("#login-form-wrap").classList.remove("hidden");$("#signup-form-wrap").classList.add("hidden");}
function showSignup(show){$("#login-form-wrap").classList.toggle("hidden",show);$("#signup-form-wrap").classList.toggle("hidden",!show);if(show){state.signupProducts=[];renderSignupCatalog();renderSignupSelected();setTimeout(()=>$(".auth-main").scrollTo(0,0),0)}}
async function login(e){e.preventDefault();const form=new FormData(e.currentTarget);const button=$("button[type=submit]",e.currentTarget);button.disabled=true;button.textContent="Entrando…";try{const data=await post("/api/login",{email:form.get("email"),password:form.get("password")});state.demoMode=data.demo_mode;await acceptUser(data.user)}catch(error){toast(error.message,"error")}finally{button.disabled=false;button.innerHTML='Entrar na plataforma <span aria-hidden="true">→</span>'}}
async function demoLogin(email,password){try{const data=await post("/api/login",{email,password});state.demoMode=data.demo_mode;await acceptUser(data.user)}catch(e){toast(e.message,"error")}}
async function acceptUser(user){
  state.user=user;
  if(user.status==="pending"||user.status==="rejected"||user.status==="suspended"){showAccountStatus(user);return}
  $("#auth-view").classList.add("hidden");$("#app-view").classList.remove("hidden");
  $("#profile-name").textContent=user.name;$("#profile-email").textContent=user.email;$("#profile-avatar").textContent=initials(user.name);
  $("#sidebar-company").textContent=user.company?.trade_name||"Licitara";
  $("#admin-nav").classList.toggle("hidden",user.role!=="admin");
  state.products=user.company?.products||[];state.states=user.company?.regions||[];state.allBrazil=state.states.length===0;
  state.saved=readSaved();
  showView(user.role==="admin"?"admin":"opportunities");
  if(user.role==="admin")await loadAdmin();else{updateProfileTags();await loadOpportunities()}
}
function showAccountStatus(user){
  $("#auth-view").classList.remove("hidden");$("#app-view").classList.add("hidden");
  const status=user.status,heading=status==="pending"?"Estamos analisando seu cadastro":status==="rejected"?"Cadastro não aprovado":"Acesso temporariamente suspenso";
  const copy=status==="pending"?"Recebemos as informações da sua empresa. Nossa equipe está fazendo a análise e você receberá uma confirmação por e-mail assim que houver uma atualização.":status==="rejected"?"Seu cadastro não foi aprovado neste momento. Fale com nossa equipe para saber mais.":"O acesso desta empresa está suspenso. Nossa equipe pode ajudar a entender o que aconteceu.";
  $("#login-form-wrap").innerHTML=`<div class="approval-state"><span class="approval-icon">${status==="pending"?"◷":"!"}</span><span class="eyebrow">CADASTRO DA EMPRESA</span><h2>${esc(heading)}</h2><p class="auth-subtitle">${esc(copy)}</p><div class="approval-company"><strong>${esc(user.company?.trade_name||user.email)}</strong><span>${esc(user.company?.cnpj||"")}</span></div><button id="status-help" class="button button-secondary button-wide" type="button">Falar com a equipe</button><button id="status-logout" class="inline-action status-logout" type="button">Sair da conta</button></div>`;
  $("#signup-form-wrap").classList.add("hidden");
  $("#status-help").addEventListener("click",()=>openWhatsApp(`Olá! Preciso de ajuda com o cadastro da empresa ${user.company?.trade_name||""}.`));
  $("#status-logout").addEventListener("click",logout);
}
async function signup(e){
  e.preventDefault();const fd=new FormData(e.currentTarget);
  const data=Object.fromEntries(fd.entries());data.products=state.signupProducts;
  const submit=$("button[type=submit]",e.currentTarget);submit.disabled=true;submit.textContent="Enviando cadastro…";
  try{const result=await post("/api/signup",data);$("#signup-form-wrap").innerHTML=`<div class="approval-state"><span class="approval-icon">✓</span><span class="eyebrow">SOLICITAÇÃO ENVIADA</span><h2>Recebemos seu cadastro</h2><p class="auth-subtitle">Sua empresa agora está <strong>pendente de aprovação</strong>. Enviaremos uma confirmação para ${esc(data.email)} quando a análise for concluída.</p><button id="signup-done" class="button button-primary button-wide" type="button">Entendi</button></div>`;$("#signup-done").addEventListener("click",()=>showSignup(false));toast(result.message)}catch(error){toast(error.message,"error");submit.disabled=false;submit.textContent="Solicitar acesso →"}
}
async function logout(){try{await post("/api/logout",{})}catch{}state.user=null;state.view="opportunities";showAuth();$("#login-form").reset();toast("Você saiu da sua conta.")}

function fillSignupStateSelect(){const select=$("#signup-form").elements.state;STATES.forEach(([code,name])=>{const option=document.createElement("option");option.value=code;option.textContent=`${name} (${code})`;select.append(option)})}
function renderSignupCatalog(){
  const query=$("#signup-product-search").value.trim().toLocaleLowerCase("pt-BR");const container=$("#signup-catalog");let html="";
  for(const [category,items] of Object.entries(state.catalog)){const matches=items.filter(x=>x.toLocaleLowerCase("pt-BR").includes(query));if(!matches.length)continue;html+=`<div class="catalog-category">${esc(category)}</div><div class="catalog-options">${matches.map(x=>`<button type="button" class="catalog-option ${state.signupProducts.includes(x)?"selected":""}" data-signup-product="${esc(x)}">${esc(x)}</button>`).join("")}</div>`}
  if(query&&!html)html=`<div class="catalog-category">Sugestão personalizada</div><div class="catalog-options"><button type="button" class="catalog-option" data-signup-product="${esc($("#signup-product-search").value.trim())}">+ Adicionar “${esc($("#signup-product-search").value.trim())}”</button></div>`;
  container.innerHTML=html;
  $$("[data-signup-product]",container).forEach(button=>button.addEventListener("click",()=>{const item=button.dataset.signupProduct;if(!state.signupProducts.includes(item))state.signupProducts.push(item);renderSignupCatalog();renderSignupSelected()}));
}
function renderSignupSelected(){$("#signup-product-count").textContent=`${state.signupProducts.length} selecionado${state.signupProducts.length===1?"":"s"}`;$("#signup-selected").innerHTML=state.signupProducts.map(p=>`<span class="selected-chip">${esc(p)}<button type="button" aria-label="Remover ${esc(p)}" data-remove-signup="${esc(p)}">×</button></span>`).join("");$$("[data-remove-signup]").forEach(b=>b.addEventListener("click",()=>{state.signupProducts=state.signupProducts.filter(x=>x!==b.dataset.removeSignup);renderSignupCatalog();renderSignupSelected()}))}
function maskCnpj(value){return value.replace(/\D/g,"").slice(0,14).replace(/^(\d{2})(\d)/,"$1.$2").replace(/^(\d{2})\.(\d{3})(\d)/,"$1.$2.$3").replace(/\.(\d{3})(\d)/,".$1/$2").replace(/(\d{4})(\d{1,2})$/,"$1-$2")}
function maskPhone(value){return value.replace(/\D/g,"").slice(0,11).replace(/^(\d{2})(\d)/,"($1) $2").replace(/(\d{5})(\d{1,4})$/,"$1-$2")}

function showView(view){
  state.view=view;
  $$(".nav-link").forEach(x=>x.classList.toggle("active",x.dataset.view===view));
  $("#opportunities-view").classList.toggle("hidden",!["opportunities","saved"].includes(view));
  $("#admin-view").classList.toggle("hidden",view!=="admin");
  $("#company-view").classList.toggle("hidden",view!=="company");
  $("#saved-view").classList.add("hidden");
  $("#breadcrumb-current").textContent=({opportunities:"Oportunidades",saved:"Salvas",company:"Minha empresa",admin:"Administração"})[view]||"Oportunidades";
  if(view==="saved"){state.saved=readSaved();renderOpportunities(state.opportunities.filter(x=>state.saved.includes(x.id)))}
  if(view==="opportunities"){renderOpportunities(state.opportunities)}
  if(view==="company")renderCompany();
  if(view==="admin")loadAdmin();
}
function handleDocumentClick(e){
  const nav=e.target.closest("[data-view]");if(nav){showView(nav.dataset.view);toggleMobileSidebar(true);return}
  if(e.target.closest("[data-demo-doc]")){toast("Este é um exemplo demonstrativo. O documento original não está disponível.","error");return}
  const filter=e.target.closest("[data-open-filters]");if(filter){openFilters(filter.dataset.openFilters);return}
  const save=e.target.closest("[data-save-id]");if(save){toggleSaved(save.dataset.saveId);return}
  const chatOpportunity=e.target.closest("[data-chat-opportunity]");if(chatOpportunity){showView("opportunities");setTimeout(()=>{const card=document.getElementById(`op-${encodeURIComponent(chatOpportunity.dataset.chatOpportunity)}`);card?.scrollIntoView({behavior:"smooth",block:"center"});card?.classList.add("chat-highlight");setTimeout(()=>card?.classList.remove("chat-highlight"),1600)},80);return}
  const items=e.target.closest("[data-items-id]");if(items){openItems(items.dataset.itemsId,items.dataset.title,items.dataset.org,items.dataset.number);return}
  const adminAct=e.target.closest("[data-admin-action]");if(adminAct){adminAction(adminAct.dataset.adminAction,Number(adminAct.dataset.userId));return}
  const detail=e.target.closest("[data-company-detail]");if(detail){const company=state.adminCompanies.find(x=>x.id===Number(detail.dataset.companyDetail));if(company)openCompanyDetail(company);return}
  const close=e.target.closest("[data-close-modal]");
  if(close&&!close.classList.contains("modal-backdrop"))closeModal();
}
function toggleMobileSidebar(forceClose=false){const sidebar=$("#sidebar");const open=sidebar.classList.contains("open");sidebar.classList.toggle("open",!open&&!forceClose);$("#sidebar-scrim").classList.toggle("open",!open&&!forceClose)}
function readSaved(){try{return JSON.parse(localStorage.getItem(`licitara:saved:${state.user?.id}`)||"[]")}catch{return[]}}
function toggleSaved(id){const s=new Set(readSaved());s.has(id)?s.delete(id):s.add(id);state.saved=[...s];localStorage.setItem(`licitara:saved:${state.user?.id}`,JSON.stringify(state.saved));if(state.view==="saved")renderOpportunities(state.opportunities.filter(x=>state.saved.includes(x.id)));else renderOpportunities(state.opportunities);toast(s.has(id)?"Oportunidade salva.":"Oportunidade removida das salvas.")}

async function loadOpportunities(force=false){
  if(!state.user||state.user.role==="admin")return;
  const list=$("#opportunity-list");if(list)list.innerHTML=`<div class="loading-state"><div><div class="spinner"></div><p>Consultando oportunidades no PNCP…</p></div></div>`;
  const query=new URLSearchParams();if(state.search)query.set("q",state.search);if(state.sort)query.set("sort",state.sort);query.set("page",String(state.page));
  state.states.forEach(s=>query.append("state",s));if(state.city)query.set("city",state.city);if(state.allBrazil)query.set("all","1");
  if(force){query.set("refresh","1")}
  try{
    const result=await api(`/api/opportunities?${query}`);
    state.opportunities=result.opportunities||[];
    state.pages=result.pages||1;state.total=result.total||state.opportunities.length;
    $("#source-label").textContent=result.demo?"Exemplos de demonstração · PNCP indisponível":`Dados oficiais consultados no ${result.source||"PNCP"}`;
    $("#source-label").closest(".source-banner").classList.toggle("demo-banner",!!result.demo);
    $("#source-updated").textContent=result.updated_at?`Atualizado ${new Date(result.updated_at).toLocaleTimeString("pt-BR",{hour:"2-digit",minute:"2-digit"})}`:"";
    $("#source-label").closest(".source-banner").title=result.warning||"Dados publicados pelo Portal Nacional de Contratações Públicas.";
    if(result.warning)toast(result.warning,"error");
    updateMetrics(state.opportunities,result.total);
    renderOpportunities(state.view==="saved"?state.opportunities.filter(x=>state.saved.includes(x.id)):state.opportunities);
    $("#results-label").textContent=result.total?`${result.total} encontrados`:"";
    $("#nav-match-count").textContent=String(state.opportunities.filter(x=>x.match).length||"");
  }catch(error){list.innerHTML=`<div class="error-state"><div class="empty-state"><div><div class="empty-icon">!</div><h3>Não foi possível carregar os editais</h3><p>${esc(error.message)}</p><button id="retry-opportunities" class="button button-secondary button-small">Tentar novamente</button></div></div></div>`;$("#retry-opportunities").addEventListener("click",()=>loadOpportunities(true))}
}
function updateMetrics(records,total){$("#metric-total").textContent=String(total??records.length);$("#metric-matches").textContent=String(records.filter(x=>x.match).length);const sum=records.reduce((s,x)=>s+(typeof x.valor==="number"&&x.valor>0?x.valor:0),0);$("#metric-value").textContent=sum?new Intl.NumberFormat("pt-BR",{style:"currency",currency:"BRL",notation:sum>10000000?"compact":"standard",maximumFractionDigits:sum>10000000?1:0}).format(sum):"—"}
function updateProfileTags(){$("#profile-tags").innerHTML=state.products.length?state.products.slice(0,3).map(p=>`<span class="catalog-tag">${esc(p)}</span>`).join("")+(state.products.length>3?`<span class="catalog-tag">+${state.products.length-3}</span>`:""):'<span class="catalog-tag">Adicione produtos</span>';renderFilterChips()}
function renderOpportunities(records){
  const list=$("#opportunity-list");if(!list)return;
  if(!records.length){list.innerHTML=`<div class="empty-state"><div><span class="empty-icon"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg></span><h3>${state.view==="saved"?"Nenhuma oportunidade salva":"Nenhuma oportunidade encontrada"}</h3><p>${state.view==="saved"?"Salve editais para encontrá-los rapidamente por aqui.":"Experimente outros termos ou amplie os filtros para encontrar mais oportunidades."}</p>${state.view==="saved"?'<button class="button button-secondary button-small" data-view="opportunities">Ver oportunidades</button>':'<button class="button button-secondary button-small" data-open-filters="region">Revisar filtros</button>'}</div></div>`;$("#pagination").innerHTML="";return}
  list.innerHTML=records.map(renderOpportunity).join("");
  renderPagination();
  renderFilterChips();
}
function renderPagination(){const container=$("#pagination");if(!container||state.view==="saved"||state.pages<=1){if(container)container.innerHTML="";return}const windowStart=Math.max(1,Math.min(state.page-2,state.pages-4));const windowEnd=Math.min(state.pages,windowStart+4);let html=`<button type="button" data-page="${Math.max(1,state.page-1)}" ${state.page===1?"disabled":""}>‹</button>`;for(let p=windowStart;p<=windowEnd;p++)html+=`<button type="button" data-page="${p}" class="${p===state.page?"current":""}">${p}</button>`;if(windowEnd<state.pages)html+=`<span>… ${state.pages}</span>`;html+=`<button type="button" data-page="${Math.min(state.pages,state.page+1)}" ${state.page===state.pages?"disabled":""}>›</button>`;container.innerHTML=html;$$("[data-page]",container).forEach(b=>b.addEventListener("click",()=>{state.page=Number(b.dataset.page);loadOpportunities();$("#opportunities-view").scrollIntoView({behavior:"smooth",block:"start"})}))}
function renderOpportunity(item){
  const isSaved=state.saved.includes(item.id), demo=!!item.demo, location=[item.cidade,item.uf].filter(Boolean).join(" / ")||"Localidade não informada";
  const url=item.url&&!demo?item.url:"";
  const match=item.match;
  return `<article class="opportunity-card ${demo?"demo-card":""}" id="op-${encodeURIComponent(item.id)}">
    <div class="card-top"><span class="modality-tag">${esc(item.modalidade||"Modalidade não informada")}</span><span class="status-tag">${esc(item.status||"Status não informado")}</span><span class="origin-tag">${esc(item.origem||"PNCP")}</span>${match?'<span class="match-tag"><svg viewBox="0 0 24 24"><path d="m5 12 4 4L19 6"/></svg>Compatível com seu perfil</span>':""}<button class="save-button ${isSaved?"saved":""}" type="button" aria-label="${isSaved?"Remover dos salvos":"Salvar oportunidade"}" data-save-id="${esc(item.id)}"><svg viewBox="0 0 24 24"><path d="m12 17.3 6.2 3.7-1.6-7.1L22 9l-7.2-.6L12 2 9.2 8.4 2 9l5.4 4.9L5.8 21z"/></svg></button></div>
    <h3>${esc(item.titulo||"Objeto não informado")}</h3><p class="agency-name">${esc(item.orgao||"Órgão não informado")}</p>
    <div class="card-details"><div class="detail-item"><span>Cidade / UF</span><strong>${esc(location)}</strong></div><div class="detail-item"><span>Nº do edital</span><strong>${esc(item.numero||"Não informado")}</strong></div><div class="detail-item"><span>Encerramento das propostas</span><strong class="highlight">${esc(dateTimeFmt(item.sessao))}</strong></div><div class="detail-item"><span>Valor estimado</span><strong class="value">${esc(money(item.valor))}</strong></div><div class="detail-item"><span>ID PNCP</span><strong>${esc(item.pncp||"Não informado")}</strong></div></div>
    <div class="card-footer"><div class="card-buttons">${url?`<a class="button button-primary button-small card-button" href="${esc(url)}" target="_blank" rel="noopener noreferrer"><svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5M12 15V3"/></svg>Baixar edital</a>`:`<button class="button button-primary button-small card-button" type="button" ${demo?"data-demo-doc":"disabled"}><svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5M12 15V3"/></svg>Baixar edital</button>`}<button class="button button-secondary button-small card-button" type="button" data-items-id="${esc(item.id)}" data-title="${esc(item.titulo||"Objeto não informado")}" data-org="${esc(item.orgao||"Órgão não informado")}" data-number="${esc(item.numero||"Não informado")}">Ver itens</button>${url?`<a class="button button-secondary button-small card-button" href="${esc(url)}" target="_blank" rel="noopener noreferrer">Site oficial ↗</a>`:`<button class="button button-secondary button-small card-button" type="button" disabled title="Link oficial não disponibilizado">Site oficial ↗</button>`}</div><span class="card-source-meta">${demo?"EXEMPLO IDENTIFICADO COMO DEMONSTRAÇÃO":item.documentos==null?"Documentos: consulte a página oficial":"+"+item.documentos+" documento(s)"}</span></div>
  </article>`;
}
function renderFilterChips(){const chips=[];if(state.states.length)chips.push(...state.states.map(s=>`${state.allBrazil?"":"UF: "}${s}`));if(state.city)chips.push(`Município: ${state.city}`);$("#filter-chips").innerHTML=chips.map(x=>`<span class="filter-chip">${esc(x)}<button type="button" data-remove-filter="${esc(x)}" aria-label="Remover filtro">×</button></span>`).join("");$("#active-filter-dot").classList.toggle("hidden",!chips.length&&!state.products.length);$$("[data-remove-filter]").forEach(btn=>btn.addEventListener("click",()=>{const value=btn.dataset.removeFilter;if(value.startsWith("UF: ")||STATES.some(([code])=>value===code)){const code=value.replace("UF: ","");state.states=state.states.filter(s=>s!==code)}else state.city="";state.page=1;loadOpportunities()}))}

function openModal(content,wide=false){$("#modal-root").innerHTML=`<div class="modal-backdrop" data-close-modal><section class="modal ${wide?"modal-wide":""}" role="dialog" aria-modal="true">${content}</section></div>`;$(".modal-backdrop").addEventListener("click",e=>{if(e.target.classList.contains("modal-backdrop"))closeModal()});document.body.style.overflow="hidden";setTimeout(()=>$(".modal-close")?.focus(),0)}
function closeModal(){if(state.filterSnapshot){state.products=state.filterSnapshot.products;state.states=state.filterSnapshot.states;state.city=state.filterSnapshot.city;state.allBrazil=state.filterSnapshot.allBrazil;state.filterSnapshot=null;updateProfileTags()}$("#modal-root").innerHTML="";document.body.style.overflow=""}
function openFilters(tab="region"){
  state.filterSnapshot={products:[...state.products],states:[...state.states],city:state.city,allBrazil:state.allBrazil};
  state.filterTab=tab==="products"?"products":"region";
  const modal=`<div class="modal-header"><div><span class="eyebrow">PERSONALIZE SUA PESQUISA</span><h2>Filtros</h2><p>Escolha onde procurar e o que sua empresa oferece.</p></div><button class="modal-close" data-close-modal aria-label="Fechar">×</button></div>
  <div class="modal-body"><div class="filter-tabs"><button class="filter-tab ${state.filterTab==="region"?"active":""}" data-filter-tab="region">Região e localização</button><button class="filter-tab ${state.filterTab==="products"?"active":""}" data-filter-tab="products">Produtos e serviços</button></div>
  <div id="region-filter-panel" class="${state.filterTab==="region"?"":"hidden"}"><div class="region-section"><label class="check-option"><input id="filter-all-brazil" type="checkbox" ${state.allBrazil?"checked":""}>Brasil inteiro</label></div><div class="region-section"><h3>Selecione por região</h3><div class="region-grid">${Object.entries(REGIONS).map(([region])=>`<label class="check-option"><input type="checkbox" data-region-check="${esc(region)}" ${REGIONS[region].every(s=>state.states.includes(s))?"checked":""}>${esc(region)}</label>`).join("")}</div></div><div class="region-section"><h3>Ou escolha um ou mais estados</h3><div class="region-grid">${STATES.map(([code,name])=>`<label class="check-option"><input type="checkbox" data-state-check="${code}" ${state.states.includes(code)?"checked":""}>${code} <span>${name}</span></label>`).join("")}</div></div><div class="region-section"><h3>Município</h3><input id="filter-city" class="modal-search" placeholder="Digite o nome do município" value="${esc(state.city)}"></div></div>
  <div id="products-filter-panel" class="${state.filterTab==="products"?"":"hidden"}"><input id="filter-product-search" class="modal-search filter-search" type="search" placeholder="Buscar produto ou serviço"><div id="filter-product-list" class="filter-product-list">${renderFilterProducts("")}</div><div id="filter-selected-products" class="selected-chips">${renderFilterProductChips()}</div></div></div>
  <div class="modal-footer"><button class="button button-secondary" data-close-modal>Cancelar</button><button id="save-filters" class="button button-primary">Salvar alterações</button></div>`;
  openModal(modal,true);$$("[data-filter-tab]").forEach(b=>b.addEventListener("click",()=>{state.filterTab=b.dataset.filterTab;$$("[data-filter-tab]").forEach(x=>x.classList.toggle("active",x===b));$("#region-filter-panel").classList.toggle("hidden",state.filterTab!=="region");$("#products-filter-panel").classList.toggle("hidden",state.filterTab!=="products")}));
  $("#filter-all-brazil").addEventListener("change",e=>{state.allBrazil=e.target.checked;if(e.target.checked){state.states=[];$$("[data-state-check]").forEach(x=>x.checked=false);$$("[data-region-check]").forEach(x=>x.checked=false)}});
  $$("[data-state-check]").forEach(c=>c.addEventListener("change",()=>{state.allBrazil=false;state.states=$$("[data-state-check]:checked").map(x=>x.dataset.stateCheck);$("#filter-all-brazil").checked=false}));
  $$("[data-region-check]").forEach(c=>c.addEventListener("change",()=>{state.allBrazil=false;const codes=REGIONS[c.dataset.regionCheck];state.states=c.checked?[...new Set([...state.states,...codes])]:state.states.filter(x=>!codes.includes(x));$$("[data-state-check]").forEach(x=>x.checked=state.states.includes(x));$("#filter-all-brazil").checked=false}));
  $("#filter-city").addEventListener("input",e=>{state.city=e.target.value});
  $("#filter-product-search").addEventListener("input",e=>{const p=$("#filter-product-list");p.innerHTML=renderFilterProducts(e.target.value);bindFilterProductButtons()});
  bindFilterProductButtons();
  $("#save-filters").addEventListener("click",saveFilters);
}
function renderFilterProducts(query){const q=query.toLocaleLowerCase("pt-BR");return Object.entries(state.catalog).map(([cat,items])=>{const matches=items.filter(x=>x.toLocaleLowerCase("pt-BR").includes(q));if(!matches.length)return"";return`<div class="filter-product-category">${esc(cat)}</div><div class="filter-product-grid">${matches.map(x=>`<button type="button" class="catalog-option ${state.products.includes(x)?"selected":""}" data-filter-product="${esc(x)}">${esc(x)}</button>`).join("")}</div>`}).join("")+(q&&!Object.values(state.catalog).flat().some(x=>x.toLocaleLowerCase("pt-BR").includes(q))?`<div class="filter-product-category">Adicionar item personalizado</div><div class="filter-product-grid"><button type="button" class="catalog-option" data-filter-product="${esc(query)}">+ ${esc(query)}</button></div>`:"")}
function renderFilterProductChips(){return state.products.map(p=>`<span class="selected-chip">${esc(p)}<button type="button" aria-label="Remover ${esc(p)}" data-remove-filter-product="${esc(p)}">×</button></span>`).join("")}
function bindFilterProductButtons(){$$("[data-filter-product]").forEach(b=>b.addEventListener("click",()=>{const p=b.dataset.filterProduct;if(state.products.includes(p))state.products=state.products.filter(x=>x!==p);else state.products.push(p);$("#filter-product-list").innerHTML=renderFilterProducts($("#filter-product-search").value);$("#filter-selected-products").innerHTML=renderFilterProductChips();bindFilterProductButtons();bindRemoveProductButtons()}));bindRemoveProductButtons()}
function bindRemoveProductButtons(){$$("[data-remove-filter-product]").forEach(b=>b.addEventListener("click",()=>{state.products=state.products.filter(x=>x!==b.dataset.removeFilterProduct);$("#filter-product-list").innerHTML=renderFilterProducts($("#filter-product-search").value);$("#filter-selected-products").innerHTML=renderFilterProductChips();bindFilterProductButtons()}))}
async function saveFilters(){try{await post("/api/preferences",{products:state.products,states:state.states});state.user.company.products=state.products;state.user.company.regions=state.states;state.page=1;state.filterSnapshot=null;closeModal();updateProfileTags();await loadOpportunities();toast("Filtros e perfil da empresa atualizados.")}catch(e){toast(e.message,"error")}}

async function openItems(id,title,org,number){
  openModal(`<div class="modal-header"><div><span class="eyebrow">DETALHES DA OPORTUNIDADE</span><h2>Itens da licitação</h2><p>${esc(org)} · Edital ${esc(number)}</p></div><button class="modal-close" data-close-modal aria-label="Fechar">×</button></div><div class="modal-body"><div class="items-intro"><strong>${esc(title)}</strong><span>Os itens abaixo são apresentados conforme os dados disponíveis na fonte oficial.</span></div><div id="items-content" class="loading-state"><div class="spinner"></div></div><p class="items-explainer">Dica: quantidades e valores estimados são referências publicadas no processo. Leia o edital completo e seus anexos para conferir especificações, prazos e condições de participação.</p><section id="documents-section" class="documents-section hidden"><h3>Documentos do processo</h3><div id="documents-content"></div></section></div>`,true);
  try{
    const result=await api(`/api/opportunities/${encodeURIComponent(id)}/items`);
    const box=$("#items-content");if(!box)return;
    if(result.unavailable){box.className="empty-state";box.innerHTML=`<div><h3>Itens não disponibilizados</h3><p>${esc(result.message||"A fonte oficial não disponibilizou os itens desta contratação.")}</p></div>`}
    else if(!result.items?.length){box.className="empty-state";box.innerHTML=`<div><h3>Nenhum item informado</h3><p>A fonte oficial não apresentou itens nesta consulta.</p></div>`}
    else{box.className="items-table-wrap";box.innerHTML=`<table class="items-table"><thead><tr><th>Descrição do item</th><th>Quantidade</th><th>Unidade</th><th>Valor unitário</th><th>Valor total</th></tr></thead><tbody>${result.items.map(i=>`<tr><td class="item-description">${esc(i.descricao||"Não informado")}<span class="item-plain">${i.natureza==="Serviço"?"O órgão solicita a prestação deste serviço; confira o escopo detalhado no edital.":i.natureza==="Material"?"O órgão solicita o fornecimento deste produto; confira as especificações no edital.":"Confira no edital se o item se refere a um produto ou serviço."}</span></td><td>${esc(i.quantidade??"Não informado")}</td><td>${esc(i.unidade||"Não informado")}</td><td>${esc(money(i.unitario))}</td><td>${esc(money(i.total))}</td></tr>`).join("")}</tbody></table>`}
    const documents=result.documents||[];
    if(documents.length){$("#documents-section").classList.remove("hidden");$("#documents-content").innerHTML=documents.map(d=>d.url?`<a class="document-link" href="${esc(d.url)}" target="_blank" rel="noopener noreferrer">${esc(d.title)} ↗</a>`:`<div class="document-link unavailable">${esc(d.title)} · link indisponível</div>`).join("");const card=document.getElementById(`op-${encodeURIComponent(id)}`);if(card)card.querySelector(".card-source-meta").textContent=`+${documents.length} documento(s) na fonte oficial`}
  }catch(e){const box=$("#items-content");if(box){box.className="error-state";box.textContent=e.message}}
}

function openWhatsApp(message){window.open(`https://wa.me/5548991579450?text=${encodeURIComponent(message)}`,"_blank","noopener,noreferrer")}
function openLoanModal(){openModal(`<div class="modal-header"><div><span class="eyebrow">PARCERIA PARA SUA EMPRESA</span><h2>Conte com a gente</h2></div><button class="modal-close" data-close-modal aria-label="Fechar">×</button></div><div class="modal-body"><div class="help-copy"><p>Está necessitando de empréstimo barato para alavancar sua empresa? Está precisando de ajuda de analistas para vender licitações mais facilmente? Fale com a gente!</p><p>Nossa equipe pode conversar com você sobre crédito e apoio especializado para participar de licitações.</p></div><button id="loan-whatsapp" class="whatsapp-cta"><svg viewBox="0 0 24 24"><path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8A8.5 8.5 0 0 1 8.7 3.9a8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8v.5Z"/></svg>FALAR COM UM ESPECIALISTA NO WHATSAPP</button></div>`,false);$("#loan-whatsapp").addEventListener("click",()=>openWhatsApp("Olá! Venho da sua agência e estou interessado na sua ajuda"))}
function openHelpModal(){openModal(`<div class="modal-header"><div><span class="eyebrow">ESTAMOS AQUI PARA AJUDAR</span><h2>Fale com a Licitara</h2><p>Atendimento para empresas e dúvidas sobre licitações.</p></div><button class="modal-close" data-close-modal aria-label="Fechar">×</button></div><div class="modal-body"><div class="help-copy"><p>Nossa equipe pode ajudar você a entender a plataforma, seu cadastro e os próximos passos para acompanhar uma oportunidade.</p><p>Atendimento pelo WhatsApp: segunda a sexta, em horário comercial.</p></div><button id="help-whatsapp" class="whatsapp-cta">CONVERSAR PELO WHATSAPP</button></div>`,false);$("#help-whatsapp").addEventListener("click",()=>openWhatsApp("Olá! Minha empresa gostaria de auxílio para aprender sobre licitações"))}

async function sendChat(e){e.preventDefault();const input=$("#chat-input"),message=input.value.trim();if(!message)return;input.value="";appendChat(message,"user");const loading=document.createElement("div");loading.className="chat-message bot-message";loading.textContent="Consultando oportunidades…";$("#chat-messages").append(loading);try{const result=await post("/api/chat",{message});loading.remove();appendChat(result.answer,"bot",result.opportunities||[])}catch(error){loading.remove();appendChat(error.message,"bot")}$("#chat-messages").scrollTop=$("#chat-messages").scrollHeight}
function appendChat(message,who,opportunities=[]){const node=document.createElement("div");node.className=`chat-message ${who==="user"?"user-message":"bot-message"}`;node.textContent=message;if(who!=="user"&&opportunities.length){const links=document.createElement("div");links.className="chat-result-links";opportunities.slice(0,5).forEach(item=>{const button=document.createElement("button");button.type="button";button.dataset.chatOpportunity=item.id;button.textContent=`Ver oportunidade: ${item.titulo||"Abrir edital"}`;links.append(button)});node.append(links)}$("#chat-messages").append(node);$("#chat-messages").scrollTop=$("#chat-messages").scrollHeight}

function renderCompany(){const c=state.user.company||{};$("#company-view").innerHTML=`<section class="page-heading"><div><span class="eyebrow">DADOS DO SEU NEGÓCIO</span><h1>Minha empresa</h1><p>Confira as informações usadas para encontrar oportunidades relevantes.</p></div><button class="button button-secondary" data-open-filters="products">Editar produtos e regiões</button></section><div class="company-view-card"><h2>${esc(c.trade_name||"Empresa")}</h2><div class="company-facts"><div><span>Razão social</span><strong>${esc(c.legal_name||"Não informado")}</strong></div><div><span>CNPJ</span><strong>${esc(c.cnpj||"Não informado")}</strong></div><div><span>Localização</span><strong>${esc([c.city,c.state].filter(Boolean).join(" / ")||"Não informada")}</strong></div><div><span>Situação do cadastro</span><strong>Cadastro aprovado</strong></div><div style="grid-column:1/-1"><span>Atividade empresarial</span><strong>${esc(c.activity||"Não informada")}</strong></div></div><h2 style="margin-top:22px">Produtos e serviços</h2><div class="company-profile-products">${state.products.length?state.products.map(x=>`<span>${esc(x)}</span>`).join(""):"<span>Nenhum produto cadastrado</span>"}</div></div>`}

async function loadAdmin(){
  if(state.user?.role!=="admin")return;
  $("#admin-view").innerHTML=`<div class="loading-state"><div><div class="spinner"></div><p>Carregando solicitações…</p></div></div>`;
  try{const query=new URLSearchParams();if(state.adminSearch)query.set("q",state.adminSearch);const [data,hist]=await Promise.all([api(`/api/admin/companies?${query}`),api("/api/admin/history")]);state.adminCompanies=data.companies;state.adminHistory=hist.history;$("#pending-badge").textContent=data.counts.pending||"";$("#pending-badge").classList.toggle("hidden",!data.counts.pending);renderAdmin(data.counts)}catch(e){$("#admin-view").innerHTML=`<div class="error-state">${esc(e.message)}</div>`}
}
function renderAdmin(counts={pending:0,approved:0,rejected:0}){
  const companies=state.adminCompanies;const tableRows=companies.map(c=>`<tr><td><span class="admin-company-name">${esc(c.company.trade_name)}</span><span class="admin-company-sub">${esc(c.name)} · ${esc(c.email)}</span></td><td>${esc(c.company.cnpj)}</td><td>${esc(c.company.city)} / ${esc(c.company.state)}</td><td><span class="status-pill ${esc(c.status)}">${({pending:"Pendente",approved:"Aprovada",rejected:"Rejeitada",suspended:"Suspensa"})[c.status]||esc(c.status)}</span></td><td><div class="table-actions"><button class="button button-secondary button-small" data-company-detail="${c.id}">Analisar</button>${c.status==="pending"?`<button class="button button-primary button-small" data-admin-action="approve" data-user-id="${c.id}">Aprovar</button>`:c.status==="approved"?`<button class="button button-danger button-small" data-admin-action="suspend" data-user-id="${c.id}">Suspender</button>`:c.status==="suspended"?`<button class="button button-secondary button-small" data-admin-action="reinstate" data-user-id="${c.id}">Reativar</button>`:`<button class="button button-secondary button-small" data-admin-action="approve" data-user-id="${c.id}">Aprovar</button>`}</div></td></tr>`).join("");
  $("#admin-view").innerHTML=`<section class="admin-heading"><div><span class="eyebrow">CONTROLE DA PLATAFORMA</span><h1>Painel administrativo</h1><p>Analise empresas cadastradas e gerencie o acesso à central de oportunidades.</p></div><button class="button button-quiet" id="admin-refresh">Atualizar lista</button></section>
    <div class="admin-stats"><div class="admin-stat"><span>Total de empresas</span><strong>${companies.length}</strong></div><div class="admin-stat pending"><span>Aguardando aprovação</span><strong>${counts.pending||0}</strong></div><div class="admin-stat approved"><span>Aprovadas</span><strong>${counts.approved||0}</strong></div><div class="admin-stat rejected"><span>Rejeitadas / suspensas</span><strong>${(counts.rejected||0)+(counts.suspended||0)}</strong></div></div>
    <div class="admin-tabs"><button class="admin-tab ${state.adminTab==="companies"?"active":""}" data-admin-tab="companies">Empresas</button><button class="admin-tab ${state.adminTab==="history"?"active":""}" data-admin-tab="history">Histórico de aprovações</button><button class="admin-tab ${state.adminTab==="notifications"?"active":""}" data-admin-tab="notifications">E-mails enviados</button></div>
    <div id="admin-panel">${state.adminTab==="companies"?`<div class="admin-search-row"><span class="results-label">${companies.length} empresas cadastradas</span><label class="search-box"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg><input id="admin-search" type="search" value="${esc(state.adminSearch)}" placeholder="Buscar nome, e-mail ou CNPJ"></label></div><div class="admin-table-wrap"><table class="admin-table"><thead><tr><th>Empresa / responsável</th><th>CNPJ</th><th>Local</th><th>Status</th><th>Ações</th></tr></thead><tbody>${tableRows||'<tr><td colspan="5">Nenhuma empresa encontrada.</td></tr>'}</tbody></table></div>`:state.adminTab==="history"?`<div class="history-list">${state.adminHistory.length?state.adminHistory.map(h=>`<div class="history-row"><span class="history-dot"></span><div><p><strong>${esc(h.trade_name||h.company_name)}</strong> · ${esc(({approved:"aprovada",rejected:"rejeitada",suspended:"suspensa"})[h.action]||h.action)} por ${esc(h.admin_name)}</p><small>${esc(dateTimeFmt(h.created_at))}</small></div></div>`).join(""):'<div class="empty-state">Nenhuma decisão registrada.</div>'}</div>`:`<div id="notification-list" class="loading-state"><div class="spinner"></div></div>`}</div>`;
  $("#admin-refresh").addEventListener("click",loadAdmin);
  $$("[data-admin-tab]").forEach(b=>b.addEventListener("click",()=>{state.adminTab=b.dataset.adminTab;if(state.adminTab==="notifications")loadNotifications();else loadAdmin()}));
  $("#admin-search")?.addEventListener("input",debounce(e=>{state.adminSearch=e.target.value;loadAdmin()},300));
}
async function loadNotifications(){try{const data=await api("/api/admin/notifications");const list=$("#notification-list");if(!list)return;list.className="history-list";list.innerHTML=data.notifications.length?data.notifications.map(n=>`<div class="history-row"><span class="history-dot" style="background:${n.sent?"#6dd5a9":"#eac26e"}"></span><div><p><strong>${esc(n.subject)}</strong> · ${esc(n.recipient)}</p><small>${esc(dateTimeFmt(n.created_at))} · ${n.sent?"Enviado":"Registrado; SMTP não configurado ou envio indisponível"}</small></div></div>`).join(""):'<div class="empty-state">Nenhuma notificação registrada.</div>'}catch(e){toast(e.message,"error")}}
async function adminAction(action,userId){const labels={approve:"aprovar",reject:"rejeitar",suspend:"suspender o acesso de",reinstate:"reativar"};if(!window.confirm(`Confirma ${labels[action]} esta empresa?`))return;try{await post("/api/admin/action",{action,user_id:userId});toast("Cadastro atualizado. Uma notificação foi registrada.");await loadAdmin()}catch(e){toast(e.message,"error")}}
function openCompanyDetail(company){
  const c=company.company;openModal(`<div class="modal-header"><div><span class="eyebrow">ANÁLISE CADASTRAL</span><h2>${esc(c.trade_name)}</h2><p>${esc(company.name)} · ${esc(company.email)}</p></div><button class="modal-close" data-close-modal aria-label="Fechar">×</button></div><div class="modal-body"><div class="company-detail-grid"><div class="company-detail"><span>Razão social</span><strong>${esc(c.legal_name)}</strong></div><div class="company-detail"><span>Nome fantasia</span><strong>${esc(c.trade_name)}</strong></div><div class="company-detail"><span>CNPJ</span><strong>${esc(c.cnpj)}</strong></div><div class="company-detail"><span>Responsável</span><strong>${esc(company.name)} · ${esc(company.phone)}</strong></div><div class="company-detail"><span>Localização</span><strong>${esc(c.city)} / ${esc(c.state)}</strong></div><div class="company-detail"><span>Cadastro</span><strong>${esc(dateTimeFmt(company.created_at))}</strong></div><div class="company-detail full"><span>Atividade</span><strong>${esc(c.activity)}</strong></div><div class="company-detail full"><span>Produtos e serviços</span><div class="company-product-tags">${(c.products||[]).length?c.products.map(x=>`<span>${esc(x)}</span>`).join(""):'<span>Não informado</span>'}</div></div></div></div><div class="modal-footer">${company.status==="pending"?`<button class="button button-danger" data-admin-action="reject" data-user-id="${company.id}">Rejeitar cadastro</button><button class="button button-primary" data-admin-action="approve" data-user-id="${company.id}">Aprovar empresa</button>`:""}</div>`,true)
}
function debounce(fn,delay){let timer;return(...args)=>{clearTimeout(timer);timer=setTimeout(()=>fn(...args),delay)}}

init();
