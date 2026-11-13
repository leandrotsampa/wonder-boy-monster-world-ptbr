"""Nomes de itens curtos nos menus (``nomes_menu`` em ``config/texto.yaml``).

O nome do item vem do banco 1 em todo lugar. Os diálogos e a loja (``[s0:02]``, subop
``0B 06``) o imprimem pelo motor de texto; o baú e as duas listas do menu do START (itens
e equipamentos por categoria) o copiam para o buffer do nome (``$AB00`` com os patches
``buffer_nome.*``; ``$8CE0`` na base) com a rotina ``0x1E6A``.
Aqui as chamadas dessa rotina feitas pelos menus passam a usar uma rotina nova que lê
primeiro uma segunda tabela de nomes (os curtos, ``traducao/textos/banco1_menu.yaml``,
ids ``b1m.XXX``, ``XXX`` = índice do item em hex como no banco 1); item sem nome curto
cai na rotina original (banco 1, nome completo). Diálogos, loja e baú não mudam. Sem
nenhum nome curto nada é gravado (ida e volta igual à base).

Config ``nomes_menu``:

- ``arquivo``: o YAML dos nomes curtos (sem extensão).
- ``rotina``: ``{end, original, preparo}``: a rotina que copia o nome, com o seu prólogo
  (``original``, em hex: o preparo do buffer e a busca do endereço no banco 1). A rotina
  nova refaz os ``preparo`` primeiros bytes do prólogo (instruções que não usam o PC nem
  a pilha) e segue o laço de cópia original, em ``end + len(original)``. Os patches de
  ``config/patches.yaml`` são gravados depois desta etapa: o preparo refeito é o do
  prólogo já com os patches que o tocam (o ``lea`` do buffer do nome, ``buffer_nome.*``),
  e a ROM continua conferida com o ``original``.
- ``chamadas``: ``[{tela, end, ini, fim, original}]``: ``end`` = a chamada da rotina
  (``jsr abs.w``, ``jsr abs.l`` ou ``bsr.w``) no fim de um trecho ``[ini, fim)`` de
  instruções inteiras (``fim - ini >= 6``). O trecho vira ``jsr trampolim.l`` (+ ``nop``)
  e o trampolim, na região livre, refaz as instruções chamando a rotina nova (como os
  trampolins de ``ferramentas/repontavel.py``: nada no trecho usa o PC nem a pilha e
  nenhum desvio cai no meio dele; ``testes/test_nomes_menu.py`` confere os reais).
- ``telas``: ``{nome: {itens: [primeiro, último], largura, nota}}``: os itens que cada
  tela mostra e quantas colunas cabem. O ``verificar`` e o build dão erro se o nome que a
  tela mostra (o curto, ou o completo do banco 1 quando não há curto) passa disso.
"""

from __future__ import annotations

import re

from .config import ErroConfig, Projeto, carregar_cfg_texto
from .repontavel import JSR_L, NOP, RTS, Reservar, _codificar
from .script.montador import ErroMontagem
from .tabela import ErroTabela, Tabela
from .textos import Entrada, carregar_todos

CHAVE = "nomes_menu"
ARQUIVO = "banco1_menu"
PREFIXO_ID = "b1m"
JMP_L = bytes.fromhex("4EF9")


def id_menu(item: int) -> str:
    return f"{PREFIXO_ID}.{item:03X}"


def _item_do_id(id_: str) -> int | None:
    m = re.fullmatch(rf"{PREFIXO_ID}\.([0-9A-F]{{3}})", id_)
    return int(m.group(1), 16) if m else None


def _int(valor, onde: str, campo: str, minimo: int = 0) -> int:
    if isinstance(valor, bool) or not isinstance(valor, int) or valor < minimo:
        raise ErroConfig(f"texto.yaml: {CHAVE}: {onde}: {campo} deve ser inteiro >= {minimo} "
                         f"(veio {valor!r})")
    return valor


def _hex(valor, onde: str, campo: str) -> bytes:
    try:
        return bytes.fromhex(valor)
    except (TypeError, ValueError):
        raise ErroConfig(f"texto.yaml: {CHAVE}: {onde}: {campo} deve ser hex "
                         f"(veio {valor!r})") from None


def config_nomes_menu(cfg: dict) -> dict | None:
    """A seção validada (``None`` se ausente); ``ErroConfig`` se algo estiver errado."""
    nm = cfg.get(CHAVE)
    if not nm:
        return None
    if not isinstance(nm, dict):
        raise ErroConfig(f"texto.yaml: {CHAVE} deve ser um mapeamento")
    if not isinstance(nm.get("arquivo"), str) or not nm["arquivo"]:
        raise ErroConfig(f"texto.yaml: {CHAVE}: arquivo (nome do YAML dos nomes curtos) "
                         f"obrigatório")
    rot = nm.get("rotina")
    if not isinstance(rot, dict):
        raise ErroConfig(f"texto.yaml: {CHAVE}: rotina = {{end, original, preparo}}")
    if _int(rot.get("end"), "rotina", "end") % 2:
        raise ErroConfig(f"texto.yaml: {CHAVE}: rotina em endereço ímpar")
    prologo = _hex(rot.get("original"), "rotina", "original")
    prep = _int(rot.get("preparo"), "rotina", "preparo")
    if prep % 2 or prep >= len(prologo):
        raise ErroConfig(f"texto.yaml: {CHAVE}: rotina: preparo ({prep}) deve ser par e menor "
                         f"que o prólogo ({len(prologo)} bytes)")
    telas = nm.get("telas")
    if not isinstance(telas, dict) or not telas:
        raise ErroConfig(f"texto.yaml: {CHAVE}: telas deve listar ao menos uma")
    donos: dict[int, str] = {}
    for nome, t in telas.items():
        if not isinstance(t, dict):
            raise ErroConfig(f"texto.yaml: {CHAVE}: tela {nome} = {{itens, largura}}")
        itens = t.get("itens")
        if (not isinstance(itens, list) or len(itens) != 2
                or not 0 <= _int(itens[0], nome, "itens") <= _int(itens[1], nome, "itens")
                <= 0xFF):
            raise ErroConfig(f"texto.yaml: {CHAVE}: tela {nome}: itens = [primeiro, último]")
        _int(t.get("largura"), nome, "largura", 1)
        for i in range(itens[0], itens[1] + 1):
            if i in donos:
                raise ErroConfig(f"texto.yaml: {CHAVE}: item {i:#04x} em duas telas "
                                 f"({donos[i]} e {nome})")
            donos[i] = nome
    chamadas = nm.get("chamadas")
    if not isinstance(chamadas, list) or not chamadas:
        raise ErroConfig(f"texto.yaml: {CHAVE}: chamadas deve listar ao menos uma")
    faixas = []
    for c in chamadas:
        if not isinstance(c, dict) or c.get("tela") not in telas:
            raise ErroConfig(f"texto.yaml: {CHAVE}: chamada {c!r}: tela deve ser uma de "
                             f"{', '.join(telas)}")
        onde = f"chamada em {c.get('end')!r}"
        ini, fim, end = (_int(c.get(k), onde, k) for k in ("ini", "fim", "end"))
        if ini % 2 or fim % 2 or end % 2 or fim - ini < 6 or not ini <= end <= fim - 4:
            raise ErroConfig(f"texto.yaml: {CHAVE}: {onde}: [ini, fim) deve ter endereços "
                             f"pares, >= 6 bytes e conter a chamada")
        if len(_hex(c.get("original"), onde, "original")) != fim - ini:
            raise ErroConfig(f"texto.yaml: {CHAVE}: {onde}: original deve ter {fim - ini} "
                             f"bytes")
        if not _tam_chamada(c) or end + _tam_chamada(c) != fim:
            raise ErroConfig(f"texto.yaml: {CHAVE}: {onde}: o trecho deve terminar na chamada "
                             f"(jsr abs.w, jsr abs.l ou bsr.w em end)")
        faixas.append((ini, fim))
    for a, b in zip(sorted(faixas), sorted(faixas)[1:]):
        if a[1] > b[0]:
            raise ErroConfig(f"texto.yaml: {CHAVE}: chamadas em {a[0]:#x} e {b[0]:#x} se "
                             f"sobrepõem")
    return nm


def faixas_nomes_menu(nm: dict | None) -> list[tuple[int, int, str]]:
    """Bytes do código que a etapa pode gravar: (início, fim, dono)."""
    if not nm:
        return []
    return [(c["ini"], c["fim"], f"{CHAVE}@{c['ini']:#x}") for c in nm["chamadas"]]


def _tela_de(nm: dict) -> dict[int, str]:
    return {i: nome for nome, t in nm["telas"].items()
            for i in range(t["itens"][0], t["itens"][1] + 1)}


def _colunas(dados: bytes) -> int:
    """Colunas do nome copiado por 0x1E6A: FE/FF + caractere ocupam uma só."""
    n = i = 0
    while i < len(dados):
        i += 2 if dados[i] >= 0xFE else 1
        n += 1
    return n


def _curtos(nm: dict, pts: dict[str, str], tabela: Tabela) -> dict[int, bytes]:
    """Nomes curtos codificados por item; ``ErroMontagem`` se algum é inválido."""
    tela_de = _tela_de(nm)
    res = {}
    for id_, pt in sorted(pts.items()):
        if not pt:
            continue
        item = _item_do_id(id_)
        if item is None or item not in tela_de:
            raise ErroMontagem(f"{id_}: o item não aparece em nenhuma tela do menu "
                               f"({', '.join(nm['telas'])}); use o banco 1")
        dados = _codificar({"id": id_}, pt, tabela)
        tela = tela_de[item]
        larg = nm["telas"][tela]["largura"]
        if _colunas(dados) > larg:
            raise ErroMontagem(f"{id_}: nome de menu com {_colunas(dados)} colunas; a tela "
                               f"{tela} tem {larg}")
        res[item] = dados
    return res


def _preparo(nm: dict, patches=()) -> bytes:
    """Os ``preparo`` primeiros bytes do prólogo (conferido na ROM por ``_conferir``) com
    os patches que caem neles já aplicados."""
    rot = nm["rotina"]
    ini = rot["end"]
    preparo = bytearray(bytes.fromhex(rot["original"])[:rot["preparo"]])
    for p in patches:
        for i, b in enumerate(p.novo):
            if 0 <= p.end + i - ini < len(preparo):
                preparo[p.end + i - ini] = b
    return bytes(preparo)


def _rotina(nm: dict, tabela_end: int, n: int, patches=()) -> bytes:
    """Código da rotina nova (ver o docstring do módulo)."""
    rot = nm["rotina"]
    prologo = bytes.fromhex(rot["original"])
    preparo = _preparo(nm, patches)
    continua = rot["end"] + len(prologo)
    ini = (bytes.fromhex("3600")                         # move.w d0,d3
           + bytes.fromhex("024300FF")                   # andi.w #$ff,d3
           + bytes.fromhex("0C43") + n.to_bytes(2, "big"))   # cmpi.w #n,d3
    meio = (bytes.fromhex("D643")                        # add.w d3,d3
            + bytes.fromhex("45F9") + tabela_end.to_bytes(4, "big")   # lea tabela.l,a2
            + bytes.fromhex("36323000"))                 # move.w (a2,d3.w),d3
    fim = (bytes.fromhex("D4C3")                         # adda.w d3,a2
           + preparo + JMP_L + continua.to_bytes(4, "big"))
    # bcc.b / beq.b -> jmp rotina.l (último)
    p_bcc = len(ini)
    p_beq = p_bcc + 2 + len(meio)
    p_fb = p_beq + 2 + len(fim)
    return (ini + bytes([0x64, p_fb - (p_bcc + 2)]) + meio + bytes([0x67, p_fb - (p_beq + 2)])
            + fim + JMP_L + rot["end"].to_bytes(4, "big"))


def _conferir(rom, nm: dict) -> None:
    rot = nm["rotina"]
    prologo = bytes.fromhex(rot["original"])
    atual = bytes(rom[rot["end"]:rot["end"] + len(prologo)])
    if atual != prologo:
        raise ErroMontagem(f"{CHAVE}: rotina em {rot['end']:#x}: esperado {prologo.hex().upper()}, "
                           f"a ROM tem {atual.hex().upper()}")
    for c in nm["chamadas"]:
        original = bytes.fromhex(c["original"])
        atual = bytes(rom[c["ini"]:c["fim"]])
        if atual != original:
            raise ErroMontagem(f"{CHAVE}: chamada em {c['ini']:#x}: esperado o original "
                               f"{original.hex().upper()}, a ROM tem {atual.hex().upper()}")
        if _alvo_chamada(rom, c["end"])[0] != rot["end"]:
            raise ErroMontagem(f"{CHAVE}: em {c['end']:#x} esperado uma chamada de "
                               f"{rot['end']:#x} (jsr ou bsr.w), a ROM tem "
                               f"{bytes(rom[c['end']:c['end'] + 6]).hex().upper()}")


#: tamanho das instruções de chamada aceitas: jsr abs.w, jsr abs.l, bsr.w
TAMANHO_CHAMADA = {0x4EB8: 4, 0x4EB9: 6, 0x6100: 4}


def _tam_chamada(c: dict) -> int:
    """Tamanho da chamada em ``c['end']`` pelo ``original`` (0 = não é chamada aceita)."""
    p = 2 * (c["end"] - c["ini"])
    return TAMANHO_CHAMADA.get(int(c["original"][p:p + 4] or "0", 16), 0)


def _alvo_chamada(rom, end: int) -> tuple[int | None, int]:
    """(alvo, tamanho) de ``jsr abs.w``, ``jsr abs.l`` ou ``bsr.w`` em ``end``."""
    op = int.from_bytes(rom[end:end + 2], "big")
    if op == 0x4EB8:
        alvo = int.from_bytes(rom[end + 2:end + 4], "big")
        return (alvo | 0xFF0000 if alvo & 0x8000 else alvo), 4
    if op == 0x4EB9:
        return int.from_bytes(rom[end + 2:end + 6], "big"), 6
    if op == 0x6100:
        d = int.from_bytes(rom[end + 2:end + 4], "big")
        return end + 2 + (d - 0x10000 if d & 0x8000 else d), 4
    return None, 0


def _trampolim(rom, c: dict, novo: int) -> bytes:
    _, tam = _alvo_chamada(rom, c["end"])
    return (bytes(rom[c["ini"]:c["end"]]) + JSR_L + novo.to_bytes(4, "big")
            + bytes(rom[c["end"] + tam:c["fim"]]) + RTS)


def _tamanho_tabela(nm: dict) -> int:
    return max(t["itens"][1] for t in nm["telas"].values()) + 1


def planejar_nomes_menu(rom, nm: dict, pts: dict[str, str], tabela: Tabela,
                        reservar: Reservar, patches=()) -> list[tuple[int, bytes]]:
    """Gravações ``(endereço, bytes)``; confere a ROM antes, com ou sem nomes curtos.
    ``patches``: os de ``config/patches.yaml``, gravados depois (ver ``_preparo``)."""
    _conferir(rom, nm)
    curtos = _curtos(nm, pts, tabela)
    if not curtos:
        return []
    n = _tamanho_tabela(nm)
    corpo, offs = b"", [0] * n
    for item in sorted(curtos):
        offs[item] = 2 * n + len(corpo)
        corpo += curtos[item] + b"\x00"
    rot = reservar(f"{CHAVE}:rotina", len(_rotina(nm, 0, n)), 2)
    tab = reservar(f"{CHAVE}:tabela", 2 * n + len(corpo), 2)
    gravar = [(rot, _rotina(nm, tab, n, patches)),
              (tab, b"".join(o.to_bytes(2, "big") for o in offs) + corpo)]
    for c in nm["chamadas"]:
        dados = _trampolim(rom, c, rot)
        t = reservar(f"{CHAVE}:trampolim@{c['ini']:#x}", len(dados), 2)
        nops = NOP * ((c["fim"] - c["ini"] - 6) // 2)
        gravar += [(t, dados), (c["ini"], JSR_L + t.to_bytes(4, "big") + nops)]
    return gravar


def bytes_nomes_menu(nm: dict | None, pts: dict[str, str], tabela: Tabela) -> int:
    """Bytes que a etapa reserva na região livre (sem o padding de alinhamento); nome
    curto inválido = 0 (o verificar já acusa)."""
    if not nm:
        return 0
    try:
        curtos = _curtos(nm, pts, tabela)
    except ErroMontagem:
        return 0
    if not curtos:
        return 0
    n = _tamanho_tabela(nm)
    total = len(_rotina(nm, 0, n)) + 2 * n + sum(len(d) + 1 for d in curtos.values())
    # trampolim: o trecho com a chamada trocada por jsr abs.l, mais o rts
    total += sum(c["fim"] - c["ini"] - _tam_chamada(c) + 6 + 2 for c in nm["chamadas"])
    return total


def extrair_nomes_menu(nm: dict, banco1: list[Entrada]) -> list[Entrada]:
    """Uma entrada por item das telas, com o ``en`` do nome no banco 1."""
    en = {e.id.rpartition(".t")[0]: e.en for e in banco1}
    return [Entrada(id_menu(i), en.get(f"b1.{i:03X}", ""))
            for i in sorted(_tela_de(nm)) if f"b1.{i:03X}" in en]


def _pts(textos: dict[str, list[Entrada]], nm: dict) -> dict[str, str]:
    return {e.id: e.pt for e in textos.get(nm["arquivo"], [])}


def conferir_conflitos(projeto: Projeto, cfg: dict, nm: dict) -> None:
    """Erro se um trecho trocado sobrepõe um patch (config/patches.yaml) ou uma
    referência das strings repontáveis (``inline_repontavel``)."""
    from .patches import carregar_patches
    from .repontavel import _faixas, ajustes_repontaveis, blocos_repontaveis, itens_repontaveis

    outros = [(p.end, p.end + len(p.original), f"o patch {p.id}")
              for p in carregar_patches(projeto)]
    outros += [(a, b, f"{dono} (inline_repontavel)") for a, b, dono in
               _faixas(itens_repontaveis(cfg), ajustes_repontaveis(cfg), blocos_repontaveis(cfg))]
    for ini, fim, dono in faixas_nomes_menu(nm):
        for a, b, outro in outros:
            if ini < b and a < fim:
                raise ErroConfig(f"texto.yaml: {dono} ({ini:#x}) sobrepõe {outro} ({a:#x})")


def etapa_nomes_menu(rom: bytearray, projeto: Projeto) -> None:
    if not (projeto.raiz / "config" / "texto.yaml").is_file():
        return
    cfg = carregar_cfg_texto(projeto.raiz)
    nm = config_nomes_menu(cfg)
    if nm is None:
        return
    conferir_conflitos(projeto, cfg, nm)
    trad = projeto.raiz / "traducao"
    arq_tbl = trad / "tabela.tbl"
    if not arq_tbl.is_file():
        raise ErroMontagem(f"{arq_tbl} não encontrada")

    def reservar(nome: str, tamanho: int, alinhamento: int = 1) -> int:
        from .espaco import regiao_livre

        return regiao_livre(projeto, len(rom)).reservar(nome, tamanho, alinhamento)

    from .patches import carregar_patches

    plano = planejar_nomes_menu(rom, nm, _pts(carregar_todos(trad / "textos"), nm),
                                Tabela.carregar(arq_tbl), reservar,
                                patches=carregar_patches(projeto))
    for end, dados in plano:
        rom[end:end + len(dados)] = dados


def checar_nomes_menu(ctx):
    """Erro se o nome que uma tela do menu mostra passa da largura dela: o curto
    (``banco1_menu``) ou, sem ele, o completo do banco 1 (com as strings aninhadas
    expandidas); e se um nome curto não codifica ou é de item fora das telas."""
    from .verificacao import Achado, _Estado, _Larguras, _Relato

    nm = ctx.extra.get("nomes_menu")
    if not nm:
        return []
    achados = []
    tela_de = _tela_de(nm)
    curtos: set[int] = set()
    for e in ctx.textos.get(nm["arquivo"], []):
        if not e.pt:
            continue
        local = f"{nm['arquivo']}:{e.id}"
        item = _item_do_id(e.id)
        if item is None or item not in tela_de:
            achados.append(Achado("erro", "nome_menu", local,
                                  f"o item não aparece em nenhuma tela do menu "
                                  f"({', '.join(nm['telas'])}); o nome dele é o do banco 1"))
            continue
        tela = tela_de[item]
        larg = nm["telas"][tela]["largura"]
        try:
            n = _colunas(_codificar({"id": e.id}, e.pt, ctx.tabela))
        except (ErroMontagem, ErroTabela) as erro:
            achados.append(Achado("erro", "nome_menu", local, str(erro)))
            continue
        curtos.add(item)
        if n > larg:
            achados.append(Achado("erro", "nome_menu", local,
                                  f"nome de menu com {n} colunas; a tela {tela} tem {larg}"))
    medidor = _Larguras(ctx.textos)
    for e in ctx.textos.get("banco1_itens", []):
        chave = e.id.rpartition(".t")[0]
        if not re.fullmatch(r"b1\.[0-9A-F]+", chave):
            continue
        item = int(chave[3:], 16)
        if item not in tela_de or item in curtos:
            continue
        rel = _Relato()
        medidor.expandir(chave, _Estado(recuo=0), None, rel)
        n = max(rel.linhas)
        tela = tela_de[item]
        larg = nm["telas"][tela]["largura"]
        if n > larg:
            achados.append(Achado(
                "erro", "nome_menu", f"banco1_itens:{e.id}",
                f"nome com {n} colunas aparece na tela {tela} do menu, que tem {larg}: "
                f"encurte-o ou dê um nome curto em {nm['arquivo']} ({id_menu(item)})"))
    return achados
