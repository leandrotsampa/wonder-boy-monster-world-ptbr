"""python -m ferramentas.emulador <roteiro.yaml> [--rom CAMINHO] [--core CAMINHO] [--destino PASTA]"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..config import carregar_projeto
from .libretro import CORE_PADRAO, RAIZ
from .roteiro import executar_roteiro


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ferramentas.emulador",
                                     description="Executa um roteiro de captura no emulador.")
    parser.add_argument("roteiro", type=Path)
    parser.add_argument("--rom", type=Path, help="ROM a rodar (padrão: ROM base de config/rom.yaml)")
    parser.add_argument("--core", type=Path, default=CORE_PADRAO, help="core libretro")
    parser.add_argument("--destino", type=Path,
                        help="pasta das saídas (padrão: build/capturas/<roteiro>)")
    args = parser.parse_args(argv)

    rom = args.rom or carregar_projeto(RAIZ).caminho_rom
    destino = args.destino or RAIZ / "build" / "capturas" / args.roteiro.stem
    try:
        executar_roteiro(args.roteiro, destino, caminho_rom=rom, caminho_core=args.core)
    except (FileNotFoundError, ValueError, RuntimeError) as erro:
        print(f"erro: {erro}", file=sys.stderr)
        return 1
    print(f"saídas em {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
