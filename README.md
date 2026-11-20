# Licitara

Plataforma web para localizar oportunidades de compras públicas compatíveis com pequenas e médias empresas brasileiras. A aplicação usa Python 3.10+ e SQLite, sem dependências externas de Python ou Node.

## Executar localmente

No PowerShell, na pasta do projeto:

```powershell
$env:DEMO_MODE = "1"
python server.py
```

Abra `http://127.0.0.1:8000`. O banco SQLite é criado automaticamente em `data/licitara.db`.

Contas locais de demonstração:

- Empresa: `empresa@licitara.demo` / `EmpresaDemo#2026`
- Administração: `admin@licitara.demo` / `AdminDemo#2026`

Os exemplos exibidos quando o PNCP está indisponível são identificados visualmente como demonstração. Eles não são editais reais e seus documentos não são baixáveis.

## Fontes e comportamento dos dados

- A central consulta a operação oficial `GET /api/consulta/v1/contratacoes/proposta`, publicada pelo PNCP, que retorna contratações com recebimento de propostas aberto. O servidor envia `dataFinal` no formato `yyyyMMdd`, `pagina`, `tamanhoPagina=50` e, quando possível, UF ou código IBGE do município. A consulta e o JSON do Swagger foram verificados em `https://pncp.gov.br/pncp-consulta/v3/api-docs`.
- Os itens usam a API pública oficial de dados do PNCP, `GET /api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens`. Esse caminho pertence à API de dados (não à API de consulta), documentada em `https://pncp.gov.br/api/pncp/v3/api-docs` e validada com uma contratação real. Os itens ficam no SQLite após a consulta.
- Os resultados são normalizados, filtrados, mantidos em cache por cinco minutos e persistidos no SQLite. Uma rotina em segundo plano renova a primeira página nacional a cada cinco minutos; filtros/páginas adicionais são carregados sob demanda.
- Os itens são consultados sob demanda em `/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens`. A disponibilidade varia por contratação. Campos ausentes aparecem como “Não informado”; contagem de anexos não é presumida.
- “Baixar edital” e “Site oficial” abrem a página oficial do PNCP, pois a rota de consulta de oportunidades não garante um URL direto para um PDF.
- Não foi adicionada uma consulta cadastral automática do CNPJ: o cadastro valida o dígito verificador localmente e não depende de um serviço de terceiros ou credencial.

## Produção

Antes de disponibilizar o serviço publicamente:

1. Configure `DEMO_MODE=0`. Isso impede a criação das contas de demonstração.
2. Defina `ADMIN_EMAIL`, `ADMIN_PASSWORD` (mínimo de 12 caracteres) e, opcionalmente, `ADMIN_NAME` para criar o primeiro administrador. A inicialização só cria esse usuário se ainda não existir.
3. Defina `COOKIE_SECURE=1` e publique atrás de um proxy HTTPS. Para acesso externo, configure o host conforme a infraestrutura e restrinja o banco e os segredos ao servidor.
4. Configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` e `SMTP_FROM` para enviar mensagens de aprovação e rejeição. Sem SMTP, o sistema registra cada aviso na área administrativa, mas não consegue entregá-lo por e-mail.
5. Defina uma chave forte para SQLite com permissões restritas no disco e inclua backups/monitoramento no processo operacional. Para múltiplas instâncias concorrentes, migre o banco SQLite para PostgreSQL e use um servidor WSGI/ASGI e proxy apropriados.
6. Opcionalmente configure `OPENAI_API_KEY` e `OPENAI_MODEL`. O servidor envia à API de IA apenas a pergunta, produtos da empresa e até cinco registros PNCP recuperados. Sem a chave, o chat usa busca determinística nos registros oficiais persistidos.

O modo de demonstração, o servidor HTTP embutido e o SQLite foram pensados para desenvolvimento e validação local, não como substitutos de hardening, observabilidade, backups e infraestrutura de produção.

## Testes

```powershell
python -m unittest discover -s tests -v
```

Os testes cobrem validação do CNPJ, autenticação, cadastro pendente, isolamento de privilégios e liberação do acesso após aprovação.
