# Componentes redistribuídos

- Pyodide 0.27.7, distribuição oficial fixada: https://cdn.jsdelivr.net/pyodide/v0.27.7/full/ — licença em `licenses/PYODIDE-LICENSE.txt`.
- CPython/WebAssembly distribuído pelo Pyodide — licença PSF em `licenses/PYTHON-LICENSE.txt`.
- Pacotes sqlite3, hashlib e OpenSSL do lockfile oficial do Pyodide. SQLite é domínio público (https://sqlite.org/copyright.html); OpenSSL 1.1.1w: `licenses/OPENSSL-LICENSE.txt`.
- xhr-shim 0.1.3, MIT: https://www.npmjs.com/package/xhr-shim — `licenses/XHR-SHIM-LICENSE.txt`.
- Ícones CF e modelo de atualização/cache reutilizados do Controle de Frotas da instalação FlashCore, sem alterar esse projeto.

`RUNTIME-SHA256.json` registra URL, tamanho e hash dos arquivos oficiais fixados. O build confere os bytes antes de incluir a dependência. Nenhuma biblioteca é buscada de CDN durante a operação offline.

Referências de arquitetura: https://pyodide.org/en/0.27.7/usage/service-worker.html e https://pyodide.org/en/0.27.7/usage/file-system.html.
