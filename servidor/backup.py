"""Cópia consistente do SQLite. Não altera o banco em uso."""
from pathlib import Path
import json
from .armazenamento import Store

if __name__ == '__main__':
    root = Path(__file__).resolve().parent.parent
    store = Store(root / 'dados', json.loads((root / 'servidor/seed.json').read_text(encoding='utf-8')))
    print(store.backup_full())
