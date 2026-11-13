"""Linha de comando: python -m ferramentas <comando>."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable

import yaml

from .compensacao import ErroCompensacao, area_compensacao, compensar
from .config import ErroConfig, Projeto, carregar_cfg_texto, carregar_projeto
from .espaco import ErroEspaco
from .fonte import (ARQ_PNG, PATCH_HUD, ErroFonte, bytes_realocados, etapa_fonte, extrair_fonte, ler_png,
                    planejar)
from .graficos import ErroGraficos, etapa_graficos, importar_tiles, item_por_nome
from .graficos import bytes_realocados as graficos_realocados
from .graficos import planejar as planejar_graficos
from .inline import etapa_inline, extrair_inline, itens_inline
from .ips import ErroIps, gerar_ips
from .nomes_menu import (bytes_nomes_menu, config_nomes_menu, etapa_nomes_menu,
                         extrair_nomes_menu)
from .patches import ErroPatch, carregar_patches, etapa_patches
from .repontavel import (ajustes_repontaveis, blocos_repontaveis, bytes_blocos,
                         bytes_repontaveis, etapa_repontavel, extrair_blocos,
                         extrair_repontaveis, itens_repontaveis)
from .revisao import LOTE_TODOS, ErroRevisao, gerar
from .script.desmontador import ErroScript
from .script.extracao import extrair_texto
from .script.montador import (ARQ_ESQUELETO, ErroMontagem, carregar_esqueleto, etapa_texto,
                              montar_texto, regiao_destino)
from .rom import ErroRom, carregar_rom, corrigir_cabecalho, hashes
from .tabela import ErroTabela, Tabela
from .textos import (STATUS, ErroTextos, Entrada, carregar_textos, carregar_todos, mesclar,
                     salvar_textos)
from .tiles import ErroTiles
from .verificacao import CHECAGENS_PADRAO, Achado, Contexto, formatar, rodar, tem_erros

ERROS_ESPERADOS = (ErroRom, ErroTabela, ErroTextos, ErroIps, ErroTiles, ErroConfig, ErroMontagem,
                   ErroScript, ErroFonte, ErroEspaco, ErroGraficos, ErroPatch,
                   ErroCompensacao, ErroRevisao)

# Etapas de inserção na ROM, em ordem. O texto reserva a região livre primeiro; as
# strings inline repontáveis, os nomes curtos dos menus, a fonte e depois os gráficos
# (blocos que não cabem no lugar) vão depois dele (Projeto.regiao). Por último, os patches
# de código (config/patches.yaml). Depois das etapas e do cabeçalho, a compensação do CRC32 e
# do checksum (ferramentas/compensacao.py) grava os últimos 8 bytes da ROM.
ETAPAS: list[Callable[[bytearray, Projeto], None]] = [etapa_texto, etapa_inline, etapa_repontavel,
                                                      etapa_nomes_menu, etapa_fonte,
                                                      etapa_graficos, etapa_patches]

NOME_BIN = "wbmw-ptbr.bin"
NOME_IPS = "wbmw-ptbr.ips"
NOME_RELATORIO = "relatorio.txt"


def _caminho_rom(projeto: Projeto, rom: str | None) -> Path:
    return Path(rom) if rom else projeto.caminho_rom


def _verificar(projeto: Projeto, rom: bytes | None = None
               ) -> tuple[list[Achado], dict[str, list[Entrada]], dict | None]:
    """Roda as checagens; devolve (achados, textos, montagem), com ``montagem`` do espaço.

    Com ``rom`` (a ROM base), o espaço inclui os blocos da fonte e dos itens gráficos
    (``config/graficos.yaml``) que não cabem no lugar.
    """
    achados: list[Achado] = []
    ctx = _contexto(projeto, achados)
    textos = ctx.textos
    fonte = graficos = 0
    if "fonte" in ctx.extra and rom is not None:
        fonte = bytes_realocados(planejar(rom, ctx.extra["fonte"]))
    if rom is not None:
        graficos = graficos_realocados(planejar_graficos(rom, projeto.raiz))
    _calcular_montagem(projeto, ctx, fonte, graficos)
    achados.extend(rodar(ctx, CHECAGENS_PADRAO))
    return achados, textos, ctx.extra.get("montagem")


def _contexto(projeto: Projeto, achados: list[Achado] | None = None) -> Contexto:
    """Contexto das checagens (textos, tabela, glossário, janelas, esqueleto, fonte), sem
    a montagem. Avisos de arquivo ausente vão para ``achados``."""
    trad = projeto.raiz / "traducao"
    achados = [] if achados is None else achados
    arq_tbl = trad / "tabela.tbl"
    if arq_tbl.is_file():
        tabela = Tabela.carregar(arq_tbl)
    else:
        tabela = Tabela({})
        achados.append(Achado("aviso", "tabela", str(arq_tbl), "tabela.tbl não encontrada"))
    textos = carregar_todos(trad / "textos")
    arq_glos = trad / "glossario.yaml"
    glossario = []
    if arq_glos.is_file():
        try:
            glossario = yaml.safe_load(arq_glos.read_text(encoding="utf-8")) or []
        except yaml.YAMLError as e:
            raise ErroTextos(f"glossario.yaml: YAML inválido: {e}") from None
    ctx = Contexto(tabela=tabela, textos=textos, glossario=glossario)
    if (projeto.raiz / "config" / "texto.yaml").is_file():
        cfg = carregar_cfg_texto(projeto.raiz)
        ctx.extra["inline"] = itens_inline(cfg)
        ctx.extra["repontavel"] = itens_repontaveis(cfg)
        ctx.extra["repontavel_ajustes"] = ajustes_repontaveis(cfg)
        ctx.extra["repontavel_blocos"] = blocos_repontaveis(cfg)
        ctx.extra["nomes_menu"] = config_nomes_menu(cfg)
        ctx.extra["largura_linha"] = cfg.get("largura_linha")
        ctx.extra["linhas_por_caixa"] = cfg.get("linhas_por_caixa")
        ctx.extra["janelas"] = cfg.get("janelas")
        ctx.extra["acentos"] = cfg.get("acentos")
    ctx.extra["hud"] = any(p.id == PATCH_HUD for p in carregar_patches(projeto))
    if (projeto.raiz / ARQ_ESQUELETO).is_file():
        ctx.extra["esqueleto"] = carregar_esqueleto(projeto.raiz)  # fluxo para a largura
    if (projeto.raiz / ARQ_PNG).is_file():
        ctx.extra["fonte"] = ler_png(projeto.raiz / ARQ_PNG)
    return ctx


def _calcular_montagem(projeto: Projeto, ctx: Contexto, fonte: int = 0,
                       graficos: int = 0) -> None:
    """Monta o texto (sem ROM) para a checagem de espaço e soma as strings inline
    repontáveis, a fonte e os gráficos realocados.

    Sem esqueleto o texto conta 0 (e, sem nada a realocar, não há montagem). O padding de
    alinhamento de blocos crus não é contado (no máximo 1 byte por bloco).
    """
    tem_esqueleto = (projeto.raiz / ARQ_ESQUELETO).is_file()
    pts = {e.id: e.pt for e in ctx.textos.get("inline", [])}
    ens = {e.id: e.en for e in ctx.textos.get("inline", [])}
    nm = ctx.extra.get("nomes_menu")
    curtos = {e.id: e.pt for e in ctx.textos.get(nm["arquivo"], [])} if nm else {}
    inline = (bytes_repontaveis(ctx.extra.get("repontavel", []), pts, ctx.tabela)
              + bytes_blocos(ctx.extra.get("repontavel_blocos", []), pts, ens, ctx.tabela)
              + bytes_nomes_menu(nm, curtos, ctx.tabela))
    if not tem_esqueleto and not fonte and not graficos and not inline:
        return
    destino, limite = regiao_destino(carregar_cfg_texto(projeto.raiz))
    texto = 0
    if tem_esqueleto:
        esqueleto = carregar_esqueleto(projeto.raiz)
        try:
            layout = montar_texto(esqueleto, ctx.textos, ctx.tabela, destino, limite)
        except ErroMontagem as e:
            ctx.extra["montagem"] = {"erro": str(e)}
            return
        except ErroTabela:
            return  # caractere/código inválido: a checagem "caracteres" já reporta
        texto = layout.tamanho
    ctx.extra["montagem"] = {"usado": texto + inline + fonte + graficos, "texto": texto,
                             "inline": inline, "fonte": fonte, "graficos": graficos,
                             "destino": destino, "limite": limite}


def _linhas_espaco(regiao) -> str:
    """Linhas do relatório com o espaço usado na região livre ('' se nada foi gravado)."""
    if regiao is None or not regiao.usos:
        return ""
    linhas = [f"Espaço: {regiao.usado} bytes usados de {regiao.limite - regiao.inicio} "
              f"em 0x{regiao.inicio:X}–0x{regiao.limite:X}"]
    linhas += [f"  {nome}: {tam} bytes em 0x{ini:X}" for nome, ini, tam in regiao.usos]
    return "\n".join(linhas) + "\n"


def _progresso(textos: dict[str, list[Entrada]]) -> str:
    linhas = ["Progresso da tradução:"]
    total = {s: 0 for s in STATUS}
    for arquivo, entradas in sorted(textos.items()):
        cont = {s: sum(e.status == s for e in entradas) for s in STATUS}
        for s in STATUS:
            total[s] += cont[s]
        linhas.append(_linha_progresso(arquivo, cont))
    linhas.append(_linha_progresso("TOTAL", total))
    return "\n".join(linhas) + "\n"


def _linha_progresso(nome: str, cont: dict[str, int]) -> str:
    n = sum(cont.values())
    feitos = cont["traduzido"] + cont["revisado"]
    pct = round(100 * feitos / n) if n else 0
    return (f"  {nome}: {cont['pendente']} pendente, {cont['traduzido']} traduzido, "
            f"{cont['revisado']} revisado — {pct}%")


def cmd_checar_rom(projeto: Projeto, args) -> int:
    caminho = _caminho_rom(projeto, args.rom)
    rom = carregar_rom(caminho, projeto.rom)
    h = hashes(bytes(rom))
    print(f"ROM: {caminho}\n  sha1:    {h['sha1']}\n  crc32:   {h['crc32']}\n  tamanho: {len(rom)}")
    if not projeto.rom.get("sha1"):
        print("AVISO: sha1 não configurado em config/rom.yaml; preencha com o valor acima.")
    else:
        print("OK: hash confere.")
    return 0


def _rom_base_opcional(projeto: Projeto) -> bytes | None:
    """A ROM base validada, se estiver em rom/ (para somar a fonte ao espaço)."""
    try:
        return bytes(carregar_rom(projeto.caminho_rom, projeto.rom))
    except ErroRom:
        return None


def cmd_verificar(projeto: Projeto, args) -> int:
    achados, _, _ = _verificar(projeto, _rom_base_opcional(projeto))
    print(formatar(achados), end="")
    return 1 if tem_erros(achados) else 0


def _montar_rom(projeto: Projeto, original: bytes) -> bytearray:
    """Roda as etapas de inserção sobre a ROM base (sem verificar)."""
    rom = bytearray(original)
    projeto.regiao = None  # espaço livre novo a cada build (as etapas o compartilham)
    for etapa in ETAPAS:
        etapa(rom, projeto)
    corrigir_cabecalho(rom)
    # por último: CRC32 do arquivo e checksum do cabeçalho iguais aos da original
    area = area_compensacao(projeto, len(rom))
    if area is not None:
        compensar(rom, original, area)
    return rom


def cmd_construir(projeto: Projeto, args) -> int:
    if not projeto.rom.get("sha1"):
        raise ErroRom(
            "sha1 da ROM base não configurado em config/rom.yaml; o build exige ROM validada. "
            "Rode 'checar-rom' e preencha o hash."
        )
    original = bytes(carregar_rom(_caminho_rom(projeto, args.rom), projeto.rom))
    achados, textos, _ = _verificar(projeto, original)
    print(formatar(achados), end="")
    if tem_erros(achados):
        print("Build abortado: corrija os erros acima.", file=sys.stderr)
        return 1
    rom = _montar_rom(projeto, original)
    patch = gerar_ips(original, bytes(rom))
    relatorio = formatar(achados) + _linhas_espaco(projeto.regiao) + "\n" + _progresso(textos)
    destino = projeto.raiz / "build"
    destino.mkdir(exist_ok=True)
    (destino / NOME_BIN).write_bytes(rom)
    (destino / NOME_IPS).write_bytes(patch)
    (destino / NOME_RELATORIO).write_text(relatorio, encoding="utf-8", newline="\n")
    print(f"Gerados em {destino}: {NOME_BIN}, {NOME_IPS}, {NOME_RELATORIO}")
    return 0


def cmd_revisao(projeto: Projeto, args) -> int:
    """Relatório do lote em build/revisao/ (ferramentas/revisao.py)."""
    ctx = _contexto(projeto)
    rom = None
    if args.capturas:
        original = bytes(carregar_rom(_caminho_rom(projeto, args.rom), projeto.rom))
        achados, _, _ = _verificar(projeto, original)
        if tem_erros(achados):
            print(formatar(achados), end="")
            raise ErroRevisao("as capturas precisam da ROM traduzida: corrija os erros acima")
        rom = bytes(_montar_rom(projeto, original))
    for arq in gerar(projeto.raiz, ctx, args.lote, rom):
        print(f"Gerado: {arq}")
    return 0


def cmd_extrair(projeto: Projeto, args) -> int:
    rom = bytes(carregar_rom(_caminho_rom(projeto, args.rom), projeto.rom))
    cfg = carregar_cfg_texto(projeto.raiz)
    tabela = Tabela.carregar(projeto.raiz / "traducao" / "tabela.tbl")
    try:
        esqueleto, grupos = extrair_texto(rom, cfg, tabela)
    except ValueError as e:  # raizes/segmentos: tabela ou raiz inconsistente
        raise ErroScript(str(e)) from None
    itens = itens_inline(cfg)
    repontaveis = itens_repontaveis(cfg)
    blocos = blocos_repontaveis(cfg)
    if itens or repontaveis or blocos:
        grupos["inline"] = (extrair_inline(rom, itens, tabela)
                            + extrair_repontaveis(rom, repontaveis, tabela)
                            + extrair_blocos(rom, blocos, tabela))
    nm = config_nomes_menu(cfg)
    if nm is not None and "banco1_itens" in grupos:
        grupos[nm["arquivo"]] = extrair_nomes_menu(nm, grupos["banco1_itens"])
    destino = projeto.raiz / "dados" / "scripts"
    destino.mkdir(parents=True, exist_ok=True)
    (destino / "esqueleto.json").write_text(
        json.dumps(esqueleto, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")
    pasta = projeto.raiz / "traducao" / "textos"
    pasta.mkdir(parents=True, exist_ok=True)
    for arquivo, extraidas in sorted(grupos.items()):
        caminho = pasta / f"{arquivo}.yaml"
        existentes = carregar_textos(caminho) if caminho.is_file() else []
        salvar_textos(caminho, mesclar(existentes, extraidas))
        print(f"  {arquivo}: {len(extraidas)} entradas")
    print(f"Esqueleto: {len(esqueleto['trechos'])} trechos, {len(esqueleto['instrucoes'])} "
          f"instruções -> {destino / 'esqueleto.json'}")
    _extrair_fonte(projeto, rom, cfg)
    return 0


def _extrair_fonte(projeto: Projeto, rom: bytes, cfg: dict) -> None:
    """Gera graficos/fonte/ se o PNG ainda não existe (o PNG é editado à mão).

    A fonte gerada é a da ROM base com os desenhos do projeto: os glifos dos acentos
    (``GLIFOS_ACENTOS``) e o rótulo MOEDAS do HUD.
    """
    png = projeto.raiz / ARQ_PNG
    if png.is_file():
        print(f"Fonte: {ARQ_PNG.as_posix()} já existe (não sobrescrito)")
        return
    extrair_fonte(rom, cfg, png.parent)
    print(f"Fonte: {ARQ_PNG.as_posix()} (acentos e rótulo do HUD do projeto)")


def cmd_importar_tiles(projeto: Projeto, args) -> int:
    """Grava o PNG e os metadados de um item de ``config/graficos.yaml`` (sobrescreve)."""
    item = item_por_nome(projeto.raiz, args.item)
    origem = Path(args.origem)
    if not origem.is_file():
        raise ErroRom(f"ROM de origem não encontrada: {origem}")
    base = bytes(carregar_rom(_caminho_rom(projeto, args.rom), projeto.rom))
    importar_tiles(origem.read_bytes(), base, item, projeto.raiz)
    print(f"{item.nome}: {item.png.as_posix()} e {item.meta.as_posix()} "
          f"(blocos {', '.join(f'0x{b:X}' for b in item.blocos)})")
    return 0


def _configurar_saida() -> None:
    """Evita UnicodeEncodeError em pipes/arquivos/Git Bash no Windows (cp1252)."""
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            if fluxo.isatty():
                fluxo.reconfigure(errors="backslashreplace")
            else:
                fluxo.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _configurar_saida()
    parser = argparse.ArgumentParser(prog="python -m ferramentas",
                                     description="Ferramental da tradução PT-BR de WBiMW")
    parser.add_argument("--raiz", default=".", help="raiz do projeto (padrão: diretório atual)")
    sub = parser.add_subparsers(dest="comando", required=True)
    p = sub.add_parser("checar-rom", help="valida o hash da ROM base")
    p.add_argument("--rom")
    p.set_defaults(func=cmd_checar_rom)
    p = sub.add_parser("verificar", help="roda todas as checagens sem gerar ROM")
    p.set_defaults(func=cmd_verificar)
    p = sub.add_parser("construir", help="verifica, gera a ROM traduzida e o IPS em build/")
    p.add_argument("--rom")
    p.set_defaults(func=cmd_construir)
    p = sub.add_parser("extrair", help="extrai o texto da ROM para esqueleto.json e YAML")
    p.add_argument("--rom")
    p.set_defaults(func=cmd_extrair)
    p = sub.add_parser("revisao", help="relatório HTML de um lote de traducao/lotes.yaml")
    p.add_argument("--lote", required=True,
                   help=f"id do lote ou '{LOTE_TODOS}' (índice com o progresso)")
    p.add_argument("--capturas", action="store_true",
                   help="roda os diálogos do lote no emulador (lento; precisa da ROM e do core)")
    p.add_argument("--rom", help="ROM base (padrão: config/rom.yaml)")
    p.set_defaults(func=cmd_revisao)
    p = sub.add_parser("importar-tiles",
                       help="gera o PNG de um item de config/graficos.yaml a partir de uma ROM")
    p.add_argument("--origem", required=True, help="ROM de onde vêm os tiles do item")
    p.add_argument("--item", required=True, help="nome do item em config/graficos.yaml")
    p.add_argument("--rom", help="ROM base (padrão: config/rom.yaml)")
    p.set_defaults(func=cmd_importar_tiles)
    args = parser.parse_args(argv)
    try:
        projeto = carregar_projeto(Path(args.raiz))
        return args.func(projeto, args)
    except ERROS_ESPERADOS as e:
        print(f"ERRO: {e}", file=sys.stderr)
        return 1
