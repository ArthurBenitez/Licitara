# Licitara

Plataforma web para localizar oportunidades de compras públicas compatíveis com pequenas e médias empresas brasileiras. A aplicação usa Python 3.10+ e SQLite, sem dependências externas de Python ou Node.

## Acesso livre

Não há cadastro, login, aprovação nem painel administrativo: qualquer pessoa abre a central e já vê as licitações. Nenhum dado pessoal é coletado ou guardado no servidor — os filtros escolhidos e as licitações salvas ficam apenas no navegador do visitante (`localStorage`).

## Executar localmente

No PowerShell, na pasta do projeto:

```powershell
python server.py
```

Abra `http://127.0.0.1:8000`. O banco SQLite é criado automaticamente em `data/licitara.db` e guarda somente o cache das oportunidades consultadas.

## Fontes e comportamento dos dados

- A central consulta a operação oficial `GET /api/consulta/v1/contratacoes/proposta`, publicada pelo PNCP, que retorna contratações com recebimento de propostas aberto. O servidor envia `dataFinal` no formato `yyyyMMdd` com uma janela de 15 dias (quem ainda vai encerrar propostas — usar a data de hoje devolvia só 221 editais no Brasil inteiro e esvaziava os filtros), `pagina`, `tamanhoPagina=50` e, quando há exatamente um estado selecionado, o UF. A consulta e o JSON do Swagger foram verificados em `https://pncp.gov.br/pncp-consulta/v3/api-docs`.
- **Filtros de local:** cada estado selecionado é consultado individualmente (`uf`), em vez de filtrar uma única página nacional — por isso o filtro de estado realmente altera a lista. Regiões são expandidas para os estados correspondentes no servidor.
- **Momento da licitação:** "Propostas abertas" usa `/v1/contratacoes/proposta` (padrão). "Licitações futuras" usa `/v1/contratacoes/publicacao` dos últimos 15 dias para Pregão Eletrônico, Concorrência Eletrônica, Concorrência Presencial, Pregão Presencial e Leilão Eletrônico, mantendo apenas as contratações cuja `dataAberturaProposta` ainda está no futuro. Se não houver nenhuma, a lista aparece vazia: exemplos nunca são inventados.
- Os itens usam a API pública oficial de dados do PNCP, `GET /api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens`, consultados sob demanda em `/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens`. A disponibilidade varia por contratação; campos ausentes aparecem como "Não informado".
- Cada URL do PNCP fica em cache por cinco minutos; o botão "Atualizar" força uma nova consulta (a faixa mostra a hora real do dado) e a página se atualiza sozinha a cada 60 segundos enquanto estiver visível. Uma rotina em segundo plano renova propostas abertas e futuras a cada três minutos.
- Se o PNCP ficar lento, cair ou limitar as requisições (429), o servidor responde com os últimos editais reais já salvos no SQLite e marca "PNCP sem resposta agora" — exemplos fictícios só aparecem quando não há nenhum dado real ainda.
- Se a rota de propostas abertas (`/v1/contratacoes/proposta`) não responder, o servidor usa a rota de publicações recentes (`/v1/contratacoes/publicacao`, últimos sete dias) e sinaliza a origem na faixa superior. Como o PNCP entrega 50 registros por página e limita o IP, um coletor em segundo plano percorre 12 páginas de sete modalidades (inclusive Dispensa e Inexigibilidade) dia a dia — começando por hoje, quando praticamente todas as contratações ainda recebem propostas — e acumula milhares de editais: as primeiras centenas aparecem na hora e a lista cresce sozinha, com paginação. Uma falha nunca vira uma lista vazia sem aviso: o que não dá para consultar aparece como aviso, não como "nenhuma oportunidade".
- **Produtos e serviços:** o filtro usa o índice de busca do próprio PNCP (`/api/search`), que pesquisa objeto **e itens** de todo o acervo — por isso um edital com objeto genérico ("aquisição de mobiliário") mas com "cadeira giratória" nos itens aparece. A consulta leva todas as palavras do item em uma frase e, quando há estados selecionados, é restrita a eles (`ufs`, um estado por consulta). Editais já conhecidos pelo servidor entram com prazos e valores oficiais; os demais entram com os dados do índice e "Encerramento: consultar no PNCP". Se o índice não responder, o servidor volta a varrer as páginas do PNCP e comparar o objeto do edital.
- A busca livre (`q`) continua filtrando apenas os editais carregados na consulta atual, porque a rota de consulta do PNCP não expõe pesquisa textual.
- "Baixar edital" baixa o arquivo publicado pelo órgão: o servidor lê os documentos oficiais da contratação, prefere o edital/aviso e devolve o arquivo como anexo (`Content-Disposition: attachment`), com limite de 30 MB e apenas endereços públicos. Quando o órgão não publica arquivo, a tela avisa e indica o botão "Site oficial".

## API

| Método | Rota | Observações |
| --- | --- | --- |
| GET | `/api/catalog` | Categorias e produtos usados nos filtros. |
| GET | `/api/opportunities` | `q`, `state` (repetido), `region` (repetido), `city`, `period=open\|future`, `sort=date\|value`, `page`, `product` (repetido), `refresh=1`, `min_value`. |
| GET | `/api/opportunities/{id}/items` | Itens e documentos oficiais da contratação. |
| GET | `/api/opportunities/{id}/download` | Baixa o arquivo do edital publicado pelo órgão (anexo). |
| POST | `/api/chat` | `{"message": "...", "products": ["..."]}`. Sem conta e sem histórico persistido. |

## Produção

1. Sirva atrás de um proxy HTTPS e defina `HOST`/`PORT` conforme a infraestrutura.
2. Aplique limites de taxa no proxy: o servidor já espaça as chamadas ao PNCP em 1s, usa cache de cinco minutos e serve dados salvos quando a fonte falha, mas continua sendo um único processo.
3. Inclua backups do SQLite no processo operacional. O banco contém apenas cache de dados públicos.
4. Opcionalmente configure `OPENAI_API_KEY` e `OPENAI_MODEL`. O servidor envia à API de IA apenas a pergunta e até cinco registros PNCP recuperados. Sem a chave, o chat usa busca determinística nos registros oficiais persistidos.

Na primeira inicialização, tabelas da versão com contas (`users`, `companies`, `sessions`, `approval_history`, `notifications`, `chat_history`) são removidas do banco local, já que o acesso não usa mais contas.

## Testes

```powershell
python -m unittest discover -s tests -v
```

Os testes cobrem o acesso público às oportunidades, o repasse dos filtros para a API do PNCP, a consulta por estado, o filtro de licitações futuras, os itens sob demanda e o chat sem conta.
