---
repo: architecture
path: docs/architecture/aw-app-devctl.md
source: generated
edited: false
checksum: sha256:e91ad2483916b6299239c96540ebc1ca41bd63d1df3d1860acbcc968124ca620
---
# DevCtl

- **repo**: aw-app-devctl
- **layer**: app
- **technologies**: python, react
- **health** (derived): planned

Dev-control panel for the workspace: (1) a piloted browser — observes and controls the aw-app-browser container over CDP (aw-app-browser:9223), live screenshot, screencast over a WebSocket, navigate, click/type/key/scroll, evaluate/inject JS; (2) a tab relay — remote JS eval into the USER's OWN live browser tab (moved from the aw-workspace monolith, ADR "Apps Own Their Front + Back Routes" Decision 5), with a [dev] top-nav toggle and an agent-driven local /eval + /tabs escape hatch. Runs standalone too (Decision 4). Backend routes under /api/apps/devctl; a devctl-browser MCP tool wrapper (piloted-browser navigate/click/type/eval/screenshot) is contributed for agents via mcp.json.

## Connections
- `http` → **aw-workspace** — routes mounted at /api/apps/devctl

## MCP tools
_none exposed_

## Requirements
### A identidade da aba vem do que o guard já verificou, e nunca é reverificada aqui
- Given uma aba do navegador da pessoa se registrando como alvo de eval, no modo integrado, atrás do IdentityGuard do runtime
- When o handler lê as claims já depositadas no escopo do WebSocket (repos/aw-app-devctl/devctl_app/routes.py::build_routes.tab_ws:150, lendo scope["aw_identity"])
- Then o usuário sai de sub ou email, o app apenas lê e nunca revalida o JWT, e no modo standalone, sem guard, as claims faltam e a aba registra como "unknown" — reverificar seria um segundo verificador de token dentro de um app, com sua própria chance de divergir do de verdade. O custo é explícito: em standalone a atribuição de dono é nominal, então esse modo não serve para separar usuários
- intended_status: `not_implemented` · derived health: `not_implemented`
- tests: `repos/aw-app-devctl/tests/test_routes.py` (passing)

### Eval sem nenhuma aba conectada responde ok=false em vez de estourar
- Given um agente pedindo para rodar JS numa aba do usuário, sem que nenhuma aba esteja registrada no momento
- When o eval é tentado e a exceção é capturada na rota (repos/aw-app-devctl/devctl_app/routes.py::build_routes.eval_in_tab:181)
- Then a resposta é 200 com {"ok": false, "error": ...} e código ausente é 400 com a mesma forma — a distinção é intencional: pedir sem código é erro de quem chama, enquanto não haver aba é um estado normal do mundo, que muda sozinho quando alguém abre o navegador. Um agente que recebe ok=false relê e espera; um que recebe 500 costuma tratar como falha do sistema
- intended_status: `not_implemented` · derived health: `not_implemented`
- tests: `repos/aw-app-devctl/tests/test_routes.py` (passing)

### Só /eval e /tabs são alcançáveis sem JWT, e só de dentro do workspace
- Given o agente chama de 127.0.0.1, de dentro do workspace, e não carrega um JWT de usuário
- When as rotas são montadas com a declaração de local_paths do manifesto (repos/aw-app-devctl/devctl_app/routes.py:9-12, contra contributes.routes.local_paths em aw-app.json)
- Then exatamente /eval e /tabs dispensam o JWT para um chamador local, e toda OUTRA rota e todo OUTRO chamador seguem exigindo — a lista é explícita e curta de propósito, porque essas duas rodam JavaScript arbitrário na aba de alguém: a isenção é o mínimo que faz o agente funcionar, e cada caminho a mais nela amplia o que é alcançável sem autenticação
- intended_status: `not_implemented` · derived health: `not_implemented`
- tests: _none linked_

### Uma aba que cai é removida do registro pelo finally, não pelo caminho feliz
- Given abas registradas num dicionário em memória, que fecham a qualquer momento, inclusive de forma abrupta
- When o laço de recepção termina por desconexão ou por qualquer outra exceção (repos/aw-app-devctl/devctl_app/routes.py:173-175)
- Then o pop do registro está no finally, então a entrada some em qualquer saída, e uma mensagem malformada da aba é ignorada com continue sem derrubar a conexão (routes.py:170-172) — limpar só no caminho de desconexão limpa deixaria abas fantasmas no /tabs, e um eval endereçado a uma delas ficaria esperando até o timeout por alguém que não está mais lá
- intended_status: `not_implemented` · derived health: `not_implemented`
- tests: `repos/aw-app-devctl/tests/test_routes.py` (passing)
