# PCP — by FlashCore

PWA individual de gestão de obras e setores. Mantém a interface e as regras do PCP local. Não há sincronização, login multiusuário nem backend online nesta versão.

## Abrir a prévia no Windows

Use `PWA/Abrir previa PCP.cmd`. A prévia fica em **http://127.0.0.1:8891/dist/**. O lançador original `Abrir PCP.cmd`, na raiz, continua abrindo a versão Python/SQLite na porta 8771. São armazenamentos separados: não alterne entre eles esperando sincronização.

Para gerar o pacote reproduzível, na raiz do repositório:

```powershell
python PWA/build.py 1.0.0
python -m unittest discover -s PWA/tests -p 'test_*.py' -v
```

O resultado publicável é **somente `PWA/dist`**. Não abra index.html diretamente por `file://`: Service Worker requer HTTPS ou origem local de teste.

## Arquitetura e preservação

Os módulos originais de `servidor` são copiados sem alterar suas regras e executados no navegador por **Pyodide 0.27.7/WebAssembly**. Um adaptador (`PWA/src/bridge.py`) substitui o transporte HTTP por operações locais no Service Worker. SQLite e anexos ficam em sistema de arquivos virtual persistido transacionalmente em **IndexedDB/IDBFS**. A resposta de sucesso só é entregue após a confirmação desse armazenamento.

Isso evita portar novamente os fluxos aprovados, mantém o formato de banco e permite importar o backup completo da versão Python (esquema 5). O custo é um primeiro download de aproximadamente **16 MB**, mais memória e alguns segundos na inicialização a frio. Todo o runtime é servido junto ao aplicativo; não depende de CDN durante o uso offline.

Os dados são separados por origem e caminho de instalação, sem localStorage como banco principal. Mudar URL, navegador, perfil ou dispositivo exige exportar/importar backup. O cache guarda apenas código e recursos estáticos. Os dados pessoais não integram o build, o Git nem a publicação.

## Instalar e usar offline

Na primeira abertura, aguarde a preparação dos recursos e a mensagem de dados carregados. Use **Instalar** no Chrome/Edge ou o menu de instalação do navegador. No iPhone, após publicação HTTPS: Safari → Compartilhar → Adicionar à Tela de Início. Instalação efetiva e disponibilidade dependem do sistema/navegador; os dispositivos físicos Android/iPhone não foram validados nesta entrega.

Depois da preparação inicial, interface, regras, dados e anexos funcionam offline. Não é necessário manter o servidor Python do PCP rodando. Para abrir a prévia local no navegador sem instalação, o lançador disponibiliza a origem inicial; uma instalação publicada usa a origem HTTPS própria.

## Migrar os dados existentes

1. No PCP Python, gere um backup completo pelo mecanismo existente (`python -B -m servidor.backup`, na pasta PCP).
2. Na PWA, finalize edições abertas e use **Importar backup**.
3. Selecione o ZIP, confira e confirme a restauração. O banco, estruturas, manifesto e hashes dos documentos são validados antes da substituição.
4. Use **Abrir dados restaurados**, confira setores, registros e anexos e exporte um novo backup da PWA.
5. Preserve o banco e o backup originais até concluir a conferência. Não existe importação automática de arquivos do PC pela versão publicada.

Somente backups completos do esquema SQLite **5** são aceitos nesta etapa. Backups antigos de outro esquema exigem conversão assistida sem apagar o original.

## Backup e restauração

**Exportar backup** gera ZIP portátil com SQLite, configurações, histórico, vínculos, anexos ativos e documentos preservados pela lixeira. O manifesto inclui versão do formato 1, esquema 5, hash do banco e hashes dos anexos. O backup completo anterior do PCP também é aceito.

**Importar backup** valida antes de substituir e mantém uma cópia do estado anterior, disponível para download logo após a restauração. Falha de validação não troca os dados atuais. A persistência IndexedDB é atômica; em caso de falha de espaço/gravação, o aplicativo não confirma sucesso e reabre o estado persistido. Abas anteriores ficam impedidas de gravar com a sessão antiga após uma restauração.

Mantenha o ZIP fora do navegador. Os dados não são sincronizados nem criptografados por esta aplicação. Não use modo privado para armazenamento definitivo. Limpar dados do site, desinstalar com remoção dos dados ou mudar de origem pode removê-los. **Sobre → Solicitar proteção do armazenamento** solicita retenção adicional, que o navegador pode negar.

Anexos mantêm os formatos e limite configurado do PCP (padrão: 30 MB/arquivo). Importação de backup tem limite de 512 MB comprimidos e descomprimidos. Operações grandes exigem memória/espaço e ainda não foram validadas em celulares. Mensagens de falta de espaço recusam a confirmação da gravação; o navegador continua tendo limites próprios.

## Atualizar

**Verificar atualização** consulta o Service Worker. O botão **Atualizar aplicativo** só aparece quando há um build novo realmente instalado e aguardando ativação. Finalize ou cancele formulários e uploads em todas as abas. A ativação solicita confirmação de prontidão às abas, troca apenas os recursos estáticos e mantém IndexedDB e anexos. Não é necessário reinstalar.

O build identifica a versão exata em **Sobre**. Para publicar versão futura, altere a versão no comando de build e no workflow, valide e publique um único pacote completo. Migrações futuras de esquema precisam de compatibilidade e backup próprios; não são autorizadas implicitamente por uma atualização de interface.

## GitHub e GitHub Pages — aguardando autorização

Não havia repositório PCP específico entre os repositórios acessíveis durante a inspeção. O repositório local é preparado com uma lista explícita de arquivos públicos. **Não foi criado repositório remoto, não houve push nem publicação.** Bancos, backups, anexos, capturas e evidências privadas ficam fora do versionamento.

Após aprovação explícita:

1. Criar ou vincular o repositório PCP, verificando novamente que não existe um equivalente.
2. Revisar os arquivos versionados e autorizar a visibilidade. GitHub Pages no plano gratuito pessoal exige repositório público; não mudar um repositório privado para público sem autorização. O Controle de Frotas atual usa Cloudflare Pages com repositório privado, embora a PWA e o mecanismo de atualização tenham sido reaproveitados para este build de GitHub Pages.
3. Enviar somente os arquivos revisados. Nas configurações Pages, selecionar **GitHub Actions** como origem.
4. Executar manualmente o workflow **Publicar interface PCP (manual)**. Não há deploy por push automático.
5. Conferir manifesto, instalação, recarga offline, anexos, backup e atualização na URL final. Importar os dados por backup no dispositivo do usuário; nunca adicioná-los ao repositório.

O workflow reproduz o build e publica apenas `PWA/dist`. Os caminhos, manifesto, caches e identificadores são relativos ao subdiretório. Não é necessário domínio pago ou serviço de banco online. A disponibilidade e os limites da hospedagem dependem do plano do GitHub.

## Evidências de teste e limitações

Testes locais incluem 15 verificações de integração executadas no navegador com base fictícia, reabertura do runtime/IndexedDB, atualização 1.0.0 → 1.0.1 com preservação dos registros e hash do anexo, ausência de alerta falso, abertura e edição com servidor estático desligado e reabertura offline. Quatro testes Python adicionais validam o adaptador, restauração nativa/portátil, bloqueio de sessão antiga, corrupção de hash e caminhos indevidos.

Os 82 testes anteriores do PCP são históricos; as regras originais não foram reimplementadas. As evidências detalhadas permanecem localmente em `PWA/tests`, fora da publicação. Permanecem as limitações operacionais já documentadas do PCP v1.0. Não há login multiusuário, permissões reais por funcionário, sincronização nem recursos financeiros restritos nesta migração. Não foram realizados testes físicos de instalação Windows/Android/iOS nem teste de volume próximo dos limites de memória/quota.

Para futura versão compartilhada, substituir o adaptador local por API autenticada, permissões no servidor e armazenamento privado de arquivos, mantendo os identificadores e as regras. Não disponibilizar o antigo `http.server` publicamente.

Consulte também `ESTADO_DO_PROJETO.md` na instalação local para recuperação, pendências anteriores e continuidade. Esse documento operacional não integra o pacote publicável.
