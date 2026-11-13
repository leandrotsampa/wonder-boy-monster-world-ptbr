"""Strings inline repontáveis (``inline_repontavel`` em ``config/texto.yaml``).

Uma string inline de tamanho fixo (``ferramentas/inline.py``) só aceita um ``pt`` que
caiba no lugar do original. Aqui o texto traduzido vai para a região livre do build
(``ferramentas/espaco.py``) e cada instrução que lia o original passa a ler a cópia nova.
O original fica intacto na ROM. Com o ``pt`` vazio nada muda.

Cada item é ``{id, end, tam, refs, nota}``: ``end``/``tam`` = endereço e comprimento do
texto original (sem o terminador ``00``; servem para extrair o ``en`` e conferir as
referências) e ``refs`` = instruções que apontam para ``end``, ``{end, tipo}``:

- ``lea_pc``: ``lea d16(pc),An`` (4 bytes). Só troca o deslocamento; erro se a cópia
  nova ficar fora do alcance de ±32 KB.
- ``lea_pc_bsr``: ``lea d16(pc),An`` seguido de ``bsr.w alvo`` (8 bytes), trocados por
  ``lea abs.l,An`` + ``bsr.b alvo`` (mesmo tamanho; erro se o ``bsr.b`` não alcança).
- ``abs_l``: operando absoluto de 32 bits (``move.l #end``, ``lea end.l``...): ``end`` é
  o endereço dos 4 bytes do operando.
- ``trampolim``: ``lea d16(pc),An`` em ``end`` dentro de um trecho ``[ini, fim)`` de
  instruções inteiras (``fim - ini >= 6``; ``original`` = os bytes do trecho, em hex). O
  trecho vira ``jsr trampolim.l`` + ``nop`` e o trampolim (na região livre) refaz as
  instruções do trecho com o ``lea`` absoluto e volta (``rts``). Serve quando o ``lea``
  não alcança a cópia nova e não há um ``bsr`` para encurtar. As outras instruções do
  trecho são copiadas como estão: não podem usar o PC nem a pilha (o ``jsr`` empilha), e
  nenhum desvio pode cair no meio do trecho (``testes/test_menus.py`` confere os reais).

Antes de gravar, cada referência é conferida na ROM (opcode e alvo = ``end`` do item).

``ajustes`` são imediatos de 16 bits que dependem do tamanho dos textos (ex.: a
centralização da mensagem do baú): ``{id, end, base, soma, largura}`` grava em ``end``
o valor ``base + soma dos tamanhos`` dos itens de ``soma`` (o ``pt`` codificado ou, se
vazio, o original). O valor da ROM base tem de ser ``base + soma dos tam``. ``largura``
opcional, ``{max, variavel}``: a linha (textos + parte variável, ex.: nome do item) não
pode passar de ``max`` caracteres.

``blocos`` são listas de strings lidas juntas, que só podem mudar de lugar juntas (ex.:
um menu lido em sequência, ou por uma tabela de deslocamentos de 16 bits): ``{id, end,
prefixo, entradas, refs, tabela, trocas, iguais}``. Na ROM, a partir de ``end``, cada
entrada é ``prefixo`` bytes (ex.: coluna e linha, copiados do original) + texto + ``00``.
``entradas`` = ``[{id, largura}]`` (``largura`` = colunas que cabem no painel; o
``verificar`` e o build dão erro acima disso). ``refs`` apontam para o início do bloco
(leitura em sequência). ``tabela`` = ``{end, refs}``: palavras com o deslocamento de cada
entrada a partir da própria tabela; no build ela é refeita na frente da cópia nova e as
``refs`` passam a apontar para ela. ``trocas`` = ``[{end, original, novo}]`` (hex, mesmo
tamanho; ``nota`` e ``origem`` opcionais): dados que mudam junto com o texto (ex.:
coordenadas). ``origem`` (opcional, no bloco) registra de onde vêm textos e arranjo.
``iguais`` = ids que precisam ter o mesmo tamanho (o jogo escreve um por cima do outro sem limpar). Se alguma
entrada tem ``pt``, o bloco inteiro é copiado (as sem ``pt`` com o texto original); se
nenhuma tem, nada muda. Tudo é conferido na ROM antes, com ou sem ``pt``.
"""

from __future__ import annotations

import re
from typing import Callable

from .config import ErroConfig, Projeto, carregar_cfg_texto
from .script.montador import ErroMontagem
from .tabela import ErroTabela, Tabela
from .textos import Entrada, carregar_todos

ARQUIVO = "inline"
CHAVE = "inline_repontavel"
#: tamanho em bytes da(s) instrução(ões) de cada tipo de referência (trampolim: fim - ini)
TAMANHO_REF = {"lea_pc": 4, "lea_pc_bsr": 8, "abs_l": 4, "trampolim": None}
#: opcodes do trampolim: jsr abs.l, nop, rts
JSR_L, NOP, RTS = bytes.fromhex("4EB9"), bytes.fromhex("4E71"), bytes.fromhex("4E75")
#: maior texto aceito ao percorrer um bloco na ROM (sem 00 antes disso = config errada)
MAX_TEXTO_BLOCO = 64

#: ``reservar(nome, tamanho, alinhamento=1)`` -> endereço na região livre
Reservar = Callable[..., int]


def _inteiro(valor, onde: str, campo: str, minimo: int | None = 0) -> int:
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ErroConfig(f"texto.yaml: {onde}: {campo} deve ser inteiro (veio {valor!r})")
    if minimo is not None and valor < minimo:
        raise ErroConfig(f"texto.yaml: {onde}: {campo} deve ser >= {minimo}")
    return valor


def _secao(cfg: dict) -> dict:
    sec = cfg.get(CHAVE) or {}
    if not isinstance(sec, dict):
        raise ErroConfig(f"texto.yaml: {CHAVE} deve ter 'itens' e 'ajustes'")
    return sec


def _faixa_ref(r: dict) -> tuple[int, int]:
    if r["tipo"] == "trampolim":
        return r["ini"], r["fim"]
    return r["end"], r["end"] + TAMANHO_REF[r["tipo"]]


def _refs_bloco(b: dict) -> list[dict]:
    return list(b["refs"]) + list((b.get("tabela") or {}).get("refs") or [])


def _faixas(itens: list[dict], ajustes: list[dict],
            blocos: list[dict] = ()) -> list[tuple[int, int, str]]:
    """Bytes que a etapa pode gravar no código: (início, fim, dono)."""
    faixas = [(*_faixa_ref(r), it["id"]) for it in itens for r in it["refs"]]
    faixas += [(a["end"], a["end"] + 2, a["id"]) for a in ajustes]
    for b in blocos:
        faixas += [(*_faixa_ref(r), b["id"]) for r in _refs_bloco(b)]
        faixas += [(t["end"], t["end"] + len(bytes.fromhex(t["original"])), b["id"])
                   for t in b.get("trocas") or []]
    return sorted(faixas)


def _checar_sobreposicao(faixas: list[tuple[int, int, str]]) -> None:
    for a, b in zip(faixas, faixas[1:]):
        if a[1] > b[0]:
            raise ErroConfig(f"texto.yaml: {CHAVE}: {a[2]} ({a[0]:#x}) sobrepõe {b[2]} "
                             f"({b[0]:#x})")


def itens_repontaveis(cfg: dict) -> list[dict]:
    """Itens validados (``ErroConfig`` se faltar campo ou houver conflito)."""
    itens = _secao(cfg).get("itens") or []
    fixos = {it.get("id") for it in cfg.get("inline") or []}
    vistos: set[str] = set()
    for it in itens:
        for campo in ("id", "end", "tam", "refs"):
            if campo not in it:
                raise ErroConfig(f"texto.yaml: item repontável {it!r} sem o campo {campo!r}")
        id_ = it["id"]
        _inteiro(it["end"], id_, "end")
        _inteiro(it["tam"], id_, "tam", 1)
        if id_ in vistos:
            raise ErroConfig(f"texto.yaml: id repontável duplicado {id_!r}")
        if id_ in fixos:
            raise ErroConfig(f"texto.yaml: {id_!r} está em inline e em {CHAVE} (gravaria duas "
                             f"vezes)")
        vistos.add(id_)
        if not isinstance(it["refs"], list) or not it["refs"]:
            raise ErroConfig(f"texto.yaml: {id_}: refs deve listar ao menos uma instrução")
        for r in it["refs"]:
            _validar_ref(id_, r)
    _checar_sobreposicao(_faixas(itens, []))
    return itens


def _hex(valor, onde: str, campo: str) -> bytes:
    try:
        return bytes.fromhex(valor)
    except (TypeError, ValueError):
        raise ErroConfig(f"texto.yaml: {onde}: {campo} deve ser hex (veio {valor!r})") from None


def _validar_ref(id_: str, r) -> None:
    if not isinstance(r, dict) or r.get("tipo") not in TAMANHO_REF:
        raise ErroConfig(f"texto.yaml: {id_}: ref {r!r} com tipo inválido (use "
                         f"{', '.join(TAMANHO_REF)})")
    if _inteiro(r.get("end"), id_, "end da ref") % 2:
        raise ErroConfig(f"texto.yaml: {id_}: ref em {r['end']:#x} não é endereço par")
    if r["tipo"] != "trampolim":
        return
    ini = _inteiro(r.get("ini"), id_, "ini do trampolim")
    fim = _inteiro(r.get("fim"), id_, "fim do trampolim")
    if ini % 2 or fim % 2 or not ini <= r["end"] <= fim - 4 or fim - ini < 6:
        raise ErroConfig(f"texto.yaml: {id_}: trampolim em {r['end']:#x}: [ini, fim) deve ter "
                         f"endereços pares, >= 6 bytes e conter o lea (4 bytes)")
    if len(_hex(r.get("original"), id_, "original do trampolim")) != fim - ini:
        raise ErroConfig(f"texto.yaml: {id_}: trampolim em {r['end']:#x}: original deve ter "
                         f"{fim - ini} bytes")


def ajustes_repontaveis(cfg: dict) -> list[dict]:
    itens = itens_repontaveis(cfg)
    ids = {it["id"] for it in itens}
    ajustes = _secao(cfg).get("ajustes") or []
    vistos: set[str] = set()
    for aj in ajustes:
        for campo in ("id", "end", "base", "soma"):
            if campo not in aj:
                raise ErroConfig(f"texto.yaml: ajuste {aj!r} sem o campo {campo!r}")
        id_ = aj["id"]
        if id_ in vistos or id_ in ids:
            raise ErroConfig(f"texto.yaml: id de ajuste duplicado {id_!r}")
        vistos.add(id_)
        if _inteiro(aj["end"], id_, "end") % 2:
            raise ErroConfig(f"texto.yaml: {id_}: end não é endereço par")
        _inteiro(aj["base"], id_, "base", None)
        if (not isinstance(aj["soma"], list) or not aj["soma"]
                or not set(aj["soma"]) <= ids):
            raise ErroConfig(f"texto.yaml: {id_}: soma deve listar ids de {CHAVE}")
        larg = aj.get("largura")
        if larg is not None and (not isinstance(larg, dict) or set(larg) != {"max", "variavel"}):
            raise ErroConfig(f"texto.yaml: {id_}: largura deve ser {{max, variavel}}")
        if larg is not None:
            _inteiro(larg["max"], id_, "largura.max", 1)
            _inteiro(larg["variavel"], id_, "largura.variavel")
    _checar_sobreposicao(_faixas(itens, ajustes))
    return ajustes


def blocos_repontaveis(cfg: dict) -> list[dict]:
    """Blocos validados (``ErroConfig`` se faltar campo ou houver conflito)."""
    itens = itens_repontaveis(cfg)
    ajustes = ajustes_repontaveis(cfg)
    blocos = _secao(cfg).get("blocos") or []
    usados = ({it["id"] for it in itens} | {a["id"] for a in ajustes}
              | {it.get("id") for it in cfg.get("inline") or []})
    for b in blocos:
        for campo in ("id", "end", "prefixo", "entradas"):
            if campo not in b:
                raise ErroConfig(f"texto.yaml: bloco {b!r} sem o campo {campo!r}")
        id_ = b["id"]
        _inteiro(b["end"], id_, "end")
        _inteiro(b["prefixo"], id_, "prefixo")
        if not isinstance(b["entradas"], list) or not b["entradas"]:
            raise ErroConfig(f"texto.yaml: {id_}: entradas deve listar ao menos uma")
        ids = [id_]
        for e in b["entradas"]:
            if not isinstance(e, dict) or "id" not in e:
                raise ErroConfig(f"texto.yaml: {id_}: entrada {e!r} sem id")
            if e.get("largura") is not None:
                _inteiro(e["largura"], f"{id_}:{e['id']}", "largura", 1)
            ids.append(e["id"])
        for x in ids:
            if x in usados:
                raise ErroConfig(f"texto.yaml: id {x!r} duplicado (bloco {id_}; inline ou "
                                 f"{CHAVE})")
            usados.add(x)
        b.setdefault("refs", [])
        tab = b.get("tabela")
        if tab is not None:
            if not isinstance(tab, dict) or not tab.get("refs"):
                raise ErroConfig(f"texto.yaml: {id_}: tabela deve ter end e refs")
            if _inteiro(tab.get("end"), id_, "end da tabela") % 2:
                raise ErroConfig(f"texto.yaml: {id_}: tabela em endereço ímpar")
        if not isinstance(b["refs"], list) or not _refs_bloco(b):
            raise ErroConfig(f"texto.yaml: {id_}: refs (ou tabela.refs) deve listar ao menos "
                             f"uma instrução")
        for r in _refs_bloco(b):
            _validar_ref(id_, r)
        for t in b.get("trocas") or []:
            if (not isinstance(t, dict) or set(t) - {"end", "original", "novo", "nota", "origem"}
                    or not t.get("original")
                    or len(_hex(t.get("original"), id_, "trocas.original"))
                    != len(_hex(t.get("novo"), id_, "trocas.novo"))):
                raise ErroConfig(f"texto.yaml: {id_}: trocas = [{{end, original, novo}}], "
                                 f"original e novo em hex do mesmo tamanho")
            _inteiro(t.get("end"), id_, "trocas.end")
        iguais = b.get("iguais") or []
        if not isinstance(iguais, list) or not set(iguais) <= set(ids[1:]):
            raise ErroConfig(f"texto.yaml: {id_}: iguais deve listar ids das entradas")
    _checar_sobreposicao(_faixas(itens, ajustes, blocos))
    return blocos


def _entradas_rom(rom, b: dict) -> list[tuple[int, bytes, bytes]]:
    """``(início, prefixo, texto)`` de cada entrada do bloco na ROM base."""
    res = []
    pos = b["end"]
    for e in b["entradas"]:
        ini = pos
        pos += b["prefixo"]
        try:
            fim = bytes(rom[pos:pos + MAX_TEXTO_BLOCO + 1]).index(0)
        except ValueError:
            raise ErroMontagem(f"{b['id']}:{e['id']}: sem o terminador 00 até "
                               f"{pos + MAX_TEXTO_BLOCO:#x}") from None
        res.append((ini, bytes(rom[ini:pos]), bytes(rom[pos:pos + fim])))
        pos += fim + 1
    return res


def extrair_blocos(rom: bytes, blocos: list[dict], tabela: Tabela) -> list[Entrada]:
    return [Entrada(e["id"], tabela.decodificar(texto))
            for b in blocos for e, (_, _, texto) in zip(b["entradas"], _entradas_rom(rom, b))]


def _erros_bloco(b: dict, tam: dict[str, int]) -> list[tuple[str, str]]:
    """``(id, mensagem)`` de largura (por entrada) e de ``iguais``; ``tam`` = colunas."""
    erros = []
    for e in b["entradas"]:
        if e.get("largura") is not None and e["id"] in tam and tam[e["id"]] > e["largura"]:
            erros.append((e["id"], f"{e['id']}: largura estourada: {tam[e['id']]} colunas "
                                   f"(o painel tem {e['largura']}; bloco {b['id']})"))
    iguais = [i for i in b.get("iguais") or [] if i in tam]
    if len({tam[i] for i in iguais}) > 1:
        erros.append((iguais[0], f"{b['id']}: {', '.join(iguais)} precisam ter o mesmo tamanho "
                                 f"(o jogo escreve um por cima do outro): "
                                 f"{', '.join(str(tam[i]) for i in iguais)}"))
    return erros


def _planejar_bloco(rom, b: dict, pts: dict[str, str], tabela: Tabela):
    """Confere o bloco na ROM; devolve ``None`` (nenhum pt) ou ``montar(reservar)``."""
    orig = _entradas_rom(rom, b)
    tab = b.get("tabela")
    if tab is not None:
        lidas = [_s16(_word(rom, tab["end"] + 2 * i)) for i in range(len(orig))]
        esperadas = [ini - tab["end"] for ini, _, _ in orig]
        if lidas != esperadas:
            raise ErroMontagem(f"{b['id']}: tabela em {tab['end']:#x} não aponta para as "
                               f"entradas (lidas {lidas}, esperadas {esperadas})")
        for ref in tab["refs"]:
            _repontar(rom, {"id": b["id"], "end": tab["end"]}, ref, tab["end"])
    for ref in b["refs"]:
        _repontar(rom, {"id": b["id"], "end": b["end"]}, ref, b["end"])
    for t in b.get("trocas") or []:
        original = bytes.fromhex(t["original"])
        if bytes(rom[t["end"]:t["end"] + len(original)]) != original:
            raise ErroMontagem(f"{b['id']}: troca em {t['end']:#x}: esperado "
                               f"{t['original'].upper()}, a ROM tem "
                               f"{bytes(rom[t['end']:t['end'] + len(original)]).hex().upper()}")
    textos = {e["id"]: (_codificar(e, pts[e["id"]], tabela) if pts.get(e["id"]) else texto)
              for e, (_, _, texto) in zip(b["entradas"], orig)}
    if erros := _erros_bloco(b, {k: len(v) for k, v in textos.items()}):
        raise ErroMontagem("; ".join(m for _, m in erros))
    if not any(pts.get(e["id"]) for e in b["entradas"]):
        return None

    def montar(reservar: Reservar) -> list[tuple[int, bytes]]:
        corpo, offs = b"", []
        n_tab = 2 * len(orig) if tab is not None else 0
        for e, (_, prefixo, _) in zip(b["entradas"], orig):
            offs.append(n_tab + len(corpo))
            corpo += prefixo + textos[e["id"]] + b"\x00"
        cabeca = b"".join(o.to_bytes(2, "big") for o in offs) if tab is not None else b""
        base = reservar(f"inline:{b['id']}", len(cabeca) + len(corpo), 2 if tab else 1)
        gravar = [(base, cabeca + corpo)]
        for ref in b["refs"]:
            gravar += _gravar_ref(rom, {"id": b["id"], "end": b["end"]}, ref, base + n_tab,
                                  b["id"], reservar)
        for ref in (tab or {}).get("refs") or []:
            gravar += _gravar_ref(rom, {"id": b["id"], "end": tab["end"]}, ref, base,
                                  b["id"], reservar)
        gravar += [(t["end"], bytes.fromhex(t["novo"])) for t in b.get("trocas") or []]
        return gravar
    return montar


def bytes_blocos(blocos: list[dict], pts: dict[str, str], ens: dict[str, str],
                 tabela: Tabela) -> int:
    """Bytes que os blocos traduzidos ocupam na região livre (tabela, entradas e
    trampolins; sem contar o padding de alinhamento). Sem ROM: o texto sem ``pt`` conta
    pelo ``en``."""
    total = 0
    for b in blocos:
        if not any(pts.get(e["id"]) for e in b["entradas"]):
            continue
        for e in b["entradas"]:
            try:   # as mesmas regras do build: pt só texto; sem pt, o original
                dados = (_codificar(e, pts[e["id"]], tabela) if pts.get(e["id"])
                         else tabela.codificar(ens.get(e["id"], ""), e["id"]))
            except (ErroMontagem, ErroTabela):
                continue   # pt inválido conta 0 (o verificar já acusa)
            total += b["prefixo"] + len(dados) + 1
        total += 2 * len(b["entradas"]) if b.get("tabela") else 0
        total += sum(_tamanho_ref(r) for r in _refs_bloco(b))
    return total


def extrair_repontaveis(rom: bytes, itens: list[dict], tabela: Tabela) -> list[Entrada]:
    return [Entrada(it["id"], tabela.decodificar(bytes(rom[it["end"]:it["end"] + it["tam"]])))
            for it in itens]


def _codificar(it: dict, pt: str, tabela: Tabela) -> bytes:
    """``pt`` codificado; só texto: a rotina que imprime (ex.: ``0x1F8E``) não interpreta
    códigos de controle nem tags (sairiam como glifos e desfariam a centralização)."""
    if re.search(r"\[[^\[\]]*\]", pt):
        raise ErroMontagem(f"{it['id']}: tags e códigos ([...]) não são aceitos aqui; só texto")
    try:
        dados = tabela.codificar(pt, it["id"])
    except ErroTabela as e:
        raise ErroMontagem(str(e)) from None
    if baixo := sorted({b for b in dados if b < 0x20}):
        raise ErroMontagem(f"{it['id']}: bytes de controle ({', '.join(f'{b:02X}' for b in baixo)}) "
                           f"não são aceitos aqui; só texto")
    return dados


def bytes_repontaveis(itens: list[dict], pts: dict[str, str], tabela: Tabela) -> int:
    """Bytes que a etapa reserva na região livre (texto + ``00`` + trampolins); pt inválido
    conta 0."""
    total = 0
    for it in itens:
        if pts.get(it["id"]):
            try:
                total += len(_codificar(it, pts[it["id"]], tabela)) + 1
                total += sum(_tamanho_ref(r) for r in it["refs"])
            except ErroMontagem:
                pass
    return total


def _word(rom, end: int) -> int:
    return int.from_bytes(rom[end:end + 2], "big")


def _s16(v: int) -> int:
    return v - 0x10000 if v & 0x8000 else v


def _conferir_lea(rom, it: dict, end: int) -> int:
    """Confere ``lea d16(pc),An`` em ``end`` apontando para o item; devolve ``n``."""
    op = _word(rom, end)
    alvo = end + 2 + _s16(_word(rom, end + 2))
    if op & 0xF1FF != 0x41FA or alvo != it["end"]:
        raise ErroMontagem(f"{it['id']}: em {end:#x} esperado 'lea {it['end']:#x}(pc),An', "
                           f"a ROM tem {bytes(rom[end:end + 4]).hex().upper()}")
    return (op >> 9) & 7


def _repontar(rom, it: dict, ref: dict, novo: int) -> bytes:
    """Bytes novos da referência (confere os originais antes). ``it`` = ``{id, end}``, com
    ``end`` = o endereço para onde a referência aponta na ROM base. Para ``trampolim``,
    devolve o código do trampolim com o ``lea`` apontando para ``novo`` (ver
    ``_gravar_ref``)."""
    end, tipo = ref["end"], ref["tipo"]
    if tipo == "abs_l":
        atual = int.from_bytes(rom[end:end + 4], "big")
        if atual != it["end"]:
            raise ErroMontagem(f"{it['id']}: em {end:#x} esperado o operando {it['end']:#08x}, "
                               f"a ROM tem {atual:#08x}")
        return novo.to_bytes(4, "big")
    if tipo == "trampolim":
        ini, fim = ref["ini"], ref["fim"]
        if bytes(rom[ini:fim]) != bytes.fromhex(ref["original"]):
            raise ErroMontagem(f"{it['id']}: trampolim em {ini:#x}: esperado o original "
                               f"{ref['original'].upper()}, a ROM tem "
                               f"{bytes(rom[ini:fim]).hex().upper()}")
    n = _conferir_lea(rom, it, end)
    if tipo == "trampolim":
        return (bytes(rom[ref["ini"]:end]) + bytes([0x41 | (n << 1), 0xF9])
                + novo.to_bytes(4, "big") + bytes(rom[end + 4:ref["fim"]]) + RTS)
    if tipo == "lea_pc":
        desl = novo - (end + 2)
        if not -0x8000 <= desl <= 0x7FFF:
            raise ErroMontagem(f"{it['id']}: {novo:#x} fora do alcance do lea (pc) em {end:#x} "
                               f"(use lea_pc_bsr ou um trampolim)")
        return bytes([0x41 | (n << 1), 0xFA]) + (desl & 0xFFFF).to_bytes(2, "big")
    # lea_pc_bsr
    if _word(rom, end + 4) != 0x6100:
        raise ErroMontagem(f"{it['id']}: em {end + 4:#x} esperado 'bsr.w', a ROM tem "
                           f"{bytes(rom[end + 4:end + 8]).hex().upper()}")
    alvo = end + 6 + _s16(_word(rom, end + 6))
    curto = alvo - (end + 8)
    if not -0x80 <= curto <= 0x7F or curto in (0, -1):
        raise ErroMontagem(f"{it['id']}: o bsr.b em {end + 6:#x} não alcança {alvo:#x}")
    return (bytes([0x41 | (n << 1), 0xF9]) + novo.to_bytes(4, "big")
            + bytes([0x61, curto & 0xFF]))


def _gravar_ref(rom, it: dict, ref: dict, novo: int, dono: str,
                reservar: Reservar) -> list[tuple[int, bytes]]:
    """Gravações que fazem ``ref`` apontar para ``novo`` (o trampolim vai para a região
    livre, em endereço par; o trecho original vira ``jsr`` + ``nop``)."""
    dados = _repontar(rom, it, ref, novo)
    if ref["tipo"] != "trampolim":
        return [(ref["end"], dados)]
    t = reservar(f"trampolim:{dono}@{ref['ini']:#x}", len(dados), 2)
    nops = NOP * ((ref["fim"] - ref["ini"] - 6) // 2)
    return [(t, dados), (ref["ini"], JSR_L + t.to_bytes(4, "big") + nops)]


def _tamanho_ref(ref: dict) -> int:
    """Bytes que a referência ocupa na região livre (só o trampolim ocupa)."""
    return ref["fim"] - ref["ini"] + 4 if ref["tipo"] == "trampolim" else 0


def _tamanhos(itens: list[dict], codificados: dict[str, bytes]) -> dict[str, int]:
    return {it["id"]: len(codificados[it["id"]]) if it["id"] in codificados else it["tam"]
            for it in itens}


def _erro_largura(aj: dict, tam: dict[str, int]) -> str | None:
    larg = aj.get("largura")
    if not larg:
        return None
    total = sum(tam[i] for i in aj["soma"]) + larg["variavel"]
    if total > larg["max"]:
        return (f"{aj['id']}: largura da linha estourada: {' + '.join(aj['soma'])} = "
                f"{total - larg['variavel']} caracteres + {larg['variavel']} da parte variável "
                f"= {total} (máximo {larg['max']})")
    return None


def planejar_repontaveis(rom, itens: list[dict], ajustes: list[dict], pts: dict[str, str],
                         tabela: Tabela, reservar: Reservar,
                         blocos: list[dict] = ()) -> list[tuple[int, bytes]]:
    """Gravações ``(endereço, bytes)``; confere tudo antes (``ErroMontagem``)."""
    codificados = {it["id"]: _codificar(it, pts[it["id"]], tabela)
                   for it in itens if pts.get(it["id"])}
    tam = _tamanhos(itens, codificados)
    gravar: list[tuple[int, bytes]] = []
    for aj in ajustes:
        original = aj["base"] + sum(next(i["tam"] for i in itens if i["id"] == s)
                                    for s in aj["soma"])
        atual = _word(rom, aj["end"])
        if atual != original & 0xFFFF:
            raise ErroMontagem(f"{aj['id']}: em {aj['end']:#x} esperado {original & 0xFFFF:#06x} "
                               f"(base + tamanhos originais), a ROM tem {atual:#06x}")
        if erro := _erro_largura(aj, tam):
            raise ErroMontagem(erro)
        valor = aj["base"] + sum(tam[s] for s in aj["soma"])
        if not -0x8000 <= valor <= 0x7FFF:
            raise ErroMontagem(f"{aj['id']}: valor {valor} não cabe em 16 bits")
        gravar.append((aj["end"], (valor & 0xFFFF).to_bytes(2, "big")))
    for it in itens:   # confere todas as referências, traduzidas ou não
        for ref in it["refs"]:
            _repontar(rom, it, ref, it["end"])
    for it in itens:
        if it["id"] not in codificados:
            continue
        dados = codificados[it["id"]] + b"\x00"
        novo = reservar(f"inline:{it['id']}", len(dados))
        gravar.append((novo, dados))
        for ref in it["refs"]:
            gravar += _gravar_ref(rom, it, ref, novo, it["id"], reservar)
    planos = [_planejar_bloco(rom, b, pts, tabela) for b in blocos]   # confere todos antes
    for b, montar in zip(blocos, planos):
        if montar is not None:
            gravar += montar(reservar)
    return gravar


def aplicar_repontaveis(rom: bytearray, plano: list[tuple[int, bytes]]) -> None:
    for end, dados in plano:
        rom[end:end + len(dados)] = dados


def _pts(textos: dict[str, list[Entrada]]) -> dict[str, str]:
    return {e.id: e.pt for e in textos.get(ARQUIVO, [])}


def _conferir_patches(projeto: Projeto, itens: list[dict], ajustes: list[dict],
                      blocos: list[dict] = ()) -> None:
    from .patches import carregar_patches

    for p in carregar_patches(projeto):
        for ini, fim, dono in _faixas(itens, ajustes, blocos):
            if ini < p.end + len(p.original) and p.end < fim:
                raise ErroConfig(f"texto.yaml: {CHAVE}: {dono} ({ini:#x}) sobrepõe o patch "
                                 f"{p.id} ({p.end:#x}) de config/patches.yaml")


def etapa_repontavel(rom: bytearray, projeto: Projeto) -> None:
    if not (projeto.raiz / "config" / "texto.yaml").is_file():
        return
    cfg = carregar_cfg_texto(projeto.raiz)
    itens = itens_repontaveis(cfg)
    blocos = blocos_repontaveis(cfg)
    if not itens and not blocos:
        return
    ajustes = ajustes_repontaveis(cfg)
    _conferir_patches(projeto, itens, ajustes, blocos)
    trad = projeto.raiz / "traducao"
    arq_tbl = trad / "tabela.tbl"
    if not arq_tbl.is_file():
        raise ErroMontagem(f"{arq_tbl} não encontrada")

    def reservar(nome: str, tamanho: int, alinhamento: int = 1) -> int:
        from .espaco import regiao_livre

        return regiao_livre(projeto, len(rom)).reservar(nome, tamanho, alinhamento)

    plano = planejar_repontaveis(rom, itens, ajustes, _pts(carregar_todos(trad / "textos")),
                                 Tabela.carregar(arq_tbl), reservar, blocos)
    aplicar_repontaveis(rom, plano)


def checar_repontaveis(ctx):
    """Erro se algum ``pt`` não codifica, estoura a largura de um ajuste ou do painel de
    um bloco, ou quebra um ``iguais`` (sem ROM: o texto sem ``pt`` conta pelo ``en``)."""
    from .verificacao import Achado

    achados = []
    pts = _pts(ctx.textos)
    itens = ctx.extra.get("repontavel", [])
    codificados: dict[str, bytes] = {}
    for it in itens:
        pt = pts.get(it["id"], "")
        if not pt:
            continue
        try:
            codificados[it["id"]] = _codificar(it, pt, ctx.tabela)
        except ErroMontagem as e:
            achados.append(Achado("erro", "inline", f"{ARQUIVO}:{it['id']}", str(e)))
    falhos = {it["id"] for it in itens if pts.get(it["id"])} - set(codificados)
    tam = _tamanhos(itens, codificados)
    for aj in ctx.extra.get("repontavel_ajustes", []):
        if falhos & set(aj["soma"]):
            continue
        if erro := _erro_largura(aj, tam):
            achados.append(Achado("erro", "inline", f"{ARQUIVO}:{aj['id']}", erro))
    ens = {e.id: e.en for e in ctx.textos.get(ARQUIVO, [])}
    for b in ctx.extra.get("repontavel_blocos", []):
        tam_bloco: dict[str, int] = {}
        for e in b["entradas"]:
            pt = pts.get(e["id"], "")
            try:
                tam_bloco[e["id"]] = len(_codificar(e, pt, ctx.tabela) if pt
                                   else ctx.tabela.codificar(ens.get(e["id"], ""), e["id"]))
            except (ErroMontagem, ErroTabela) as erro:
                achados.append(Achado("erro", "inline", f"{ARQUIVO}:{e['id']}", str(erro)))
        for id_, msg in _erros_bloco(b, tam_bloco):
            achados.append(Achado("erro", "inline", f"{ARQUIVO}:{id_}", msg))
    return achados
