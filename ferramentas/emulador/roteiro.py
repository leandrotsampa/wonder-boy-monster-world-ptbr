"""Roteiros de captura: listas YAML de passos executados no emulador.

Passos aceitos (um por item da lista):

- ``{esperar: N}`` — avança N quadros sem botões;
- ``{apertar: [start, a], quadros: 2}`` — segura os botões por ``quadros`` (padrão 1);
- ``{capturar: nome}`` — grava ``nome.png`` com o quadro atual;
- ``{vram: nome}`` — grava ``nome.vram`` (64 KB);
- ``{estado_salvar: nome}`` — grava ``nome.estado`` e guarda o estado na memória;
- ``{estado_carregar: nome}`` — volta ao estado salvo (da memória ou de ``nome.estado``);
- ``{checar_fonte: nome}`` — grava ``nome.ram`` (64 KB da RAM do 68000) e falha
  (``RuntimeError``) se a invariante da fonte não vale: ``$A144`` > 40 ou slots 5–7
  sem os blocos 5–7 (ver ``vram_cenas.checar_invariante_fonte`` e vram.md §3.1);
- ``{repetir: N, passos: [...]}`` — executa a sublista ``passos`` N vezes
  (inteiro de 0 a ``MAX_REPETIR``; 0 é aceito e não faz nada).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .libretro import CORE_PADRAO, Emulador
from .vram_cenas import checar_invariante_fonte

PASSOS = ("esperar", "apertar", "capturar", "vram", "estado_salvar", "estado_carregar",
          "checar_fonte", "repetir")
MAX_REPETIR = 10_000
_OPCIONAIS = {"apertar": {"quadros"}, "repetir": {"passos"}}


def _validar(passos: object, origem: str) -> None:
    if not isinstance(passos, list):
        raise ValueError(f"{origem}: o roteiro deve ser uma lista de passos")
    for i, passo in enumerate(passos, 1):
        if not isinstance(passo, dict):
            raise ValueError(f"{origem}: passo {i} não é um mapeamento: {passo!r}")
        chaves = [c for c in passo if c in PASSOS]
        permitidas = set(PASSOS) | (_OPCIONAIS.get(chaves[0], set()) if len(chaves) == 1 else set())
        if len(chaves) != 1 or set(passo) - permitidas:
            raise ValueError(f"{origem}: passo {i} inválido: {passo!r}")
        if "repetir" in passo:
            n = passo["repetir"]
            if (isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= MAX_REPETIR
                    or "passos" not in passo):
                raise ValueError(f"{origem}: passo {i} inválido: {passo!r}")
            _validar(passo["passos"], f"{origem} (passo {i})")


def carregar_roteiro(caminho: Path) -> list[dict]:
    passos = yaml.safe_load(Path(caminho).read_text(encoding="utf-8")) or []
    _validar(passos, str(caminho))
    return passos


def executar_roteiro(caminho: Path, destino: Path, *, emulador: Emulador | None = None,
                     caminho_rom: Path | None = None,
                     caminho_core: Path = CORE_PADRAO) -> None:
    """Executa o roteiro gravando as saídas em ``destino``.

    Usa ``emulador`` se for passado (sem fechá-lo); senão abre um com
    ``caminho_core``/``caminho_rom`` e fecha ao terminar.
    """
    passos = carregar_roteiro(caminho)
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    proprio = emulador is None
    if proprio:
        if caminho_rom is None:
            raise ValueError("informe emulador ou caminho_rom")
        emulador = Emulador(caminho_core, caminho_rom)
    estados: dict[str, bytes] = {}

    def rodar(lista: list[dict]) -> None:
        for passo in lista:
            if "repetir" in passo:
                for _ in range(int(passo["repetir"])):
                    rodar(passo["passos"])
            elif "esperar" in passo:
                emulador.avancar(int(passo["esperar"]))
            elif "apertar" in passo:
                botoes = passo["apertar"]
                if isinstance(botoes, str):
                    botoes = [botoes]
                emulador.avancar(int(passo.get("quadros", 1)), set(botoes))
            elif "capturar" in passo:
                emulador.quadro_png(destino / f"{passo['capturar']}.png")
            elif "vram" in passo:
                (destino / f"{passo['vram']}.vram").write_bytes(emulador.vram())
            elif "estado_salvar" in passo:
                nome = str(passo["estado_salvar"])
                estados[nome] = emulador.salvar_estado()
                (destino / f"{nome}.estado").write_bytes(estados[nome])
            elif "checar_fonte" in passo:
                nome = str(passo["checar_fonte"])
                ram = emulador.ram()
                (destino / f"{nome}.ram").write_bytes(ram)
                problemas = checar_invariante_fonte(ram)
                if problemas:
                    raise RuntimeError(f"invariante da fonte quebrada em {nome!r}: "
                                       + "; ".join(problemas))
            elif "estado_carregar" in passo:
                nome = str(passo["estado_carregar"])
                dados = estados.get(nome)
                if dados is None:
                    dados = (destino / f"{nome}.estado").read_bytes()
                emulador.carregar_estado(dados)

    try:
        rodar(passos)
    finally:
        if proprio:
            emulador.fechar()
