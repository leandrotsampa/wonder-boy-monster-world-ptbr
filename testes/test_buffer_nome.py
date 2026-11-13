"""Buffer do nome de item em RAM livre maior (config/patches.yaml, ``buffer_nome.*``).

A rotina 0x1E6A copia o nome do banco 1 em duas linhas (de cima: marcas FE/FF; de baixo:
as letras) que o baú (0x1EEC) e as listas do menu (0x7AD6, 0x8428) leem logo depois. Na
base as linhas ficam em $8CE0 e $8CF0 (16 colunas, com a pilha das strings aninhadas em
$8D00 logo depois); os patches as levam para $AB00 e $AB20 (32 colunas cada), numa área
que o jogo não usa (prova em docs/tecnico/mapa-rom.md §6, "Buffer do nome de item")."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from ferramentas.config import Projeto
from ferramentas.patches import aplicar_patches, carregar_patches
from ferramentas.tabela import Tabela
from ferramentas.textos import Entrada, carregar_textos
from ferramentas.verificacao import Contexto

RAIZ = Path(__file__).resolve().parent.parent
TABELA = Tabela.carregar(RAIZ / "traducao" / "tabela.tbl")

ANTIGO, ANTIGO_LETRAS = 0x8CE0, 0x8CF0
# referências ao buffer antigo na base (auditoria abaixo): endereço -> (original, novo)
PATCHES = {
    0x1E72: ("47F88CE0", "47F8AB00"),   # lea $8CE0.w,a3       (0x1E6A: preparo da cópia)
    0x1EC4: ("17430010", "17430020"),   # move.b d3,$10(a3)    (letras = linha de cima + 16)
    0x1F18: ("41F88CE0", "41F8AB00"),   # lea $8CE0.w,a0       (baú: lê as duas linhas)
    0x1F26: ("10280010", "10280020"),   # move.b $10(a0),d0
    0x7AEE: ("43F88CE0", "43F8AB00"),   # lea $8CE0.w,a1       (tela ITEM: linha de cima)
    0x7AFA: ("43F88CF0", "43F8AB20"),   # lea $8CF0.w,a1       (tela ITEM: letras)
    0x8446: ("41F88CE0", "41F8AB00"),   # lea $8CE0.w,a0       (equipamentos: linha de cima)
    0x844C: ("41F88CF0", "41F8AB20"),   # lea $8CF0.w,a0       (equipamentos: letras)
}


def _desmontar(dados: bytes, end: int) -> list[tuple[str, str]]:
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_M68K_000)
    return [(i.mnemonic, i.op_str.replace(" ", "")) for i in md.disasm(dados, end)]


def _patches_buffer():
    return [p for p in carregar_patches(Projeto(raiz=RAIZ, rom={}))
            if p.id.startswith("buffer_nome.")]


def test_constantes_e_limite():
    """Linha de cima em $AB00, letras em +$20; o limite é o menor entre o buffer (32) e a
    linha do baú ("Você achou " + nome + "." em 30 colunas: 18)."""
    from ferramentas.verificacao import (BUFFER_NOME_ITEM, BUFFER_NOME_ITEM_LETRAS,
                                         MAX_NOME_ITEM, MAX_NOME_ITEM_BAU)

    assert (BUFFER_NOME_ITEM, BUFFER_NOME_ITEM_LETRAS) == (0xAB00, 0xAB20)
    assert MAX_NOME_ITEM_BAU == 30 - len("Você achou ") - len(".") == 18
    assert MAX_NOME_ITEM == min(BUFFER_NOME_ITEM_LETRAS - BUFFER_NOME_ITEM,
                                MAX_NOME_ITEM_BAU) == 18
    pts = {e.id: e.pt for e in carregar_textos(RAIZ / "traducao" / "textos" / "inline.yaml")}
    assert 30 - len(pts["bau.achou_o"]) - len(pts["bau.ponto"]) == MAX_NOME_ITEM_BAU


def test_auditoria_do_buffer_na_base(rom_base):
    """Toda referência a $8CE0-$8CFF no código (força bruta em cada endereço par): as 7
    do buffer, mais 0x1F16, que é o meio de 'bsr.w $1F8E; lea $8CE0.w,a0' (0x1F14) lido
    fora de fase. As letras são lidas por deslocamento: $10(a3) em 0x1EC4 e $10(a0) em
    0x1F26; as listas usam o endereço $8CF0 direto."""
    from ferramentas.script.auditoria import referencias_ram

    achadas = referencias_ram(rom_base, ANTIGO, ANTIGO + 0x20)
    assert achadas == sorted([*(a for a in PATCHES if a not in (0x1EC4, 0x1F26)), 0x1F16])
    assert _desmontar(rom_base[0x1F14:0x1F1C], 0x1F14) == [("bsr.w", "$1f8e"),
                                                           ("lea.l", "$8ce0.w,a0")]
    for end, (original, _) in PATCHES.items():
        assert rom_base[end:end + 4] == bytes.fromhex(original), hex(end)
    assert _desmontar(rom_base[0x1EC4:0x1EC8], 0x1EC4) == [("move.b", "d3,$10(a3)")]
    assert _desmontar(rom_base[0x1F26:0x1F2A], 0x1F26) == [("move.b", "$10(a0),d0")]


def test_patches_reapontam_o_buffer(rom_base):
    """Um patch por referência, mesmo tamanho; com eles nada no código aponta para o
    buffer antigo e as 7 referências (mais o falso 0x1F16) vão para o novo."""
    from ferramentas.script.auditoria import referencias_ram
    from ferramentas.verificacao import BUFFER_NOME_ITEM, BUFFER_NOME_ITEM_LETRAS

    ps = _patches_buffer()
    assert {p.end: (p.original.hex().upper(), p.novo.hex().upper()) for p in ps} == PATCHES
    assert all(p.descricao and p.origem for p in ps)
    rom = bytearray(rom_base)
    aplicar_patches(rom, carregar_patches(Projeto(raiz=RAIZ, rom={})))
    assert referencias_ram(rom, ANTIGO, ANTIGO + 0x30) == []
    assert referencias_ram(rom, BUFFER_NOME_ITEM, BUFFER_NOME_ITEM + 0x40) == sorted(
        [*(a for a in PATCHES if a not in (0x1EC4, 0x1F26)), 0x1F16])
    assert _desmontar(bytes(rom[0x1E72:0x1E76]), 0x1E72) == [("lea.l", "$ab00.w,a3")]
    assert _desmontar(bytes(rom[0x1EC4:0x1ECA]), 0x1EC4) == [("move.b", "d3,$20(a3)"),
                                                            ("move.b", "d2,(a3)+")]
    assert _desmontar(bytes(rom[0x1F18:0x1F2A]), 0x1F18)[0] == ("lea.l", "$ab00.w,a0")
    assert _desmontar(bytes(rom[0x1F26:0x1F2A]), 0x1F26) == [("move.b", "$20(a0),d0")]
    for end, reg in ((0x7AEE, "a1"), (0x8446, "a0")):
        assert _desmontar(bytes(rom[end:end + 4]), end) == [("lea.l", f"$ab00.w,{reg}")]
    for end, reg in ((0x7AFA, "a1"), (0x844C, "a0")):
        assert _desmontar(bytes(rom[end:end + 4]), end) == [
            ("lea.l", f"${BUFFER_NOME_ITEM_LETRAS:x}.w,{reg}")]


def test_area_nova_sem_referencias_no_codigo(rom_base):
    """Nenhuma instrução do código endereça $A3C0-$BFFF (a última variável antes é
    $A3BE; a de depois, $C000, é a primeira página da tabela de objetos). Os dois
    achados ficam em 0x96BC+, dados passados por 'lea $96BC(pc),a0' (0x9682) depois do
    rts de 0x96BA."""
    from ferramentas.script.auditoria import referencias_ram

    assert referencias_ram(rom_base, 0xA3C0, 0xC000) == [0x96CC, 0x96CE]
    assert _desmontar(rom_base[0x9682:0x9686], 0x9682) == [("lea.l", "$96bc(pc),a0")]
    assert _desmontar(rom_base[0x96BA:0x96BC], 0x96BA) == [("rts", "")]
    assert referencias_ram(rom_base, 0xAA00, 0xAC00) == []


def test_verificar_barra_nome_acima_do_limite():
    """N = 18 passa; N + 1 é erro (com as aninhadas expandidas)."""
    from ferramentas.verificacao import MAX_NOME_ITEM, checar_nomes_itens

    def ctx(*entradas):
        return Contexto(tabela=TABELA, textos={"banco1_itens": list(entradas)}, glossario=[])
    cabe = "Armadura do Guarda"
    assert len(cabe) == MAX_NOME_ITEM
    assert checar_nomes_itens(ctx(Entrada("b1.00E.t00", "Leather Armor", pt=cabe))) == []
    achados = checar_nomes_itens(ctx(Entrada("b1.00E.t00", "Leather Armor", pt=cabe + "s")))
    assert [a.nivel for a in achados] == ["erro"]
    assert "19 colunas" in achados[0].mensagem and "18" in achados[0].mensagem
    assert "$AB00" in achados[0].mensagem and "baú" in achados[0].mensagem


# ------------------------------------------------------------- build real

def _copiar_projeto(destino: Path, rom_base: bytes, trocas: dict[str, str] | None = None) -> Path:
    for rel in ("config", "traducao", "graficos"):
        shutil.copytree(RAIZ / rel, destino / rel)
    (destino / "dados" / "scripts").mkdir(parents=True)
    shutil.copy(RAIZ / "dados" / "scripts" / "esqueleto.json", destino / "dados" / "scripts")
    if trocas:   # ids b1.XXX.t00 (banco1_itens) ou b1m.XXX (banco1_menu)
        for nome in ("banco1_itens", "banco1_menu"):
            arq = destino / "traducao" / "textos" / f"{nome}.yaml"
            dados = yaml.safe_load(arq.read_text(encoding="utf-8"))
            for e in dados:
                if e["id"] in trocas:
                    e["pt"] = trocas[e["id"]]
            arq.write_text(yaml.safe_dump(dados, allow_unicode=True, sort_keys=False),
                           encoding="utf-8")
    arq = destino / "base.bin"
    arq.write_bytes(rom_base)
    return arq


def _construir(destino: Path, rom_base: bytes, trocas: dict[str, str] | None = None) -> bytes:
    from ferramentas.cli import main

    arq = _copiar_projeto(destino, rom_base, trocas)
    assert main(["--raiz", str(destino), "construir", "--rom", str(arq)]) == 0
    return (destino / "build" / "wbmw-ptbr.bin").read_bytes()


def test_rotina_dos_menus_usa_o_buffer_novo(rom_base, tmp_path):
    """A rotina dos nomes curtos refaz o preparo de 0x1E6A: com o patch, o 'lea' dela
    também vai para $AB00 (o build lê o preparo com os patches aplicados)."""
    rom = _construir(tmp_path, rom_base)
    regiao = yaml.safe_load((RAIZ / "config" / "texto.yaml").read_text(encoding="utf-8"))[
        "regiao_destino"]
    livre = rom[regiao[0]:regiao[1]]
    preparo_novo = bytes.fromhex("42788D1042788CDE47F8AB00")
    assert livre.count(preparo_novo) == 1
    assert bytes.fromhex("47F88CE0") not in livre
    # e a rotina original também
    assert rom[0x1E6A:0x1E76] == preparo_novo


def test_ida_e_volta_sem_traducoes(rom_base, tmp_path):
    """Sem nenhum pt, o código (0x200-0x1C600: rotina do nome, baú, menus) só muda pelos
    patches declarados em config/patches.yaml."""
    from ferramentas.cli import main
    from ferramentas.textos import salvar_textos

    arq = _copiar_projeto(tmp_path, rom_base)
    for f in (tmp_path / "traducao" / "textos").glob("*.yaml"):
        salvar_textos(f, [Entrada(e.id, e.en, nota=e.nota) for e in carregar_textos(f)])
    assert main(["--raiz", str(tmp_path), "construir", "--rom", str(arq)]) == 0
    rom = (tmp_path / "build" / "wbmw-ptbr.bin").read_bytes()
    ref = bytearray(rom_base)
    aplicar_patches(ref, carregar_patches(Projeto(raiz=RAIZ, rom={})))
    assert rom[0x200:0x1C600] == ref[0x200:0x1C600]
    for p in _patches_buffer():
        assert rom[p.end:p.end + len(p.novo)] == p.novo


# ------------------------------------------------------------- no jogo

def test_bau_com_o_nome_mais_longo_no_jogo(rom_base, tmp_path):
    """Baú com um nome de 18 colunas (MAX_NOME_ITEM, só na cópia do projeto): inteiro,
    centrado, bordas intactas; o nome está no buffer novo e o antigo nem é tocado."""
    from test_repontavel import (ITEM_LONGO, _centrada, _com_gancho, _linha_janela,
                                 _rodar_bau)

    from ferramentas.emulador.libretro import CORE_PADRAO
    from ferramentas.verificacao import BUFFER_NOME_ITEM, BUFFER_NOME_ITEM_LETRAS, MAX_NOME_ITEM

    if not CORE_PADRAO.is_file():
        pytest.skip("core libretro ausente")
    nome = "Armadura do Guarda"
    assert len(nome) == MAX_NOME_ITEM and ITEM_LONGO == 0x0E
    # o menu (17 colunas nas telas de equipamento) recebe um nome curto só nesta cópia
    rom = _construir(tmp_path, rom_base, {"b1.00E.t00": nome, "b1m.00E": "Guarda"})
    arq = tmp_path / "teste.bin"
    arq.write_bytes(_com_gancho(rom))
    cap = RAIZ / "build" / "capturas" / "bau_nome_longo"
    _rodar_bau(arq, cap)
    pts = {e.id: e.pt for e in carregar_textos(RAIZ / "traducao" / "textos" / "inline.yaml")}
    texto = TABELA.codificar(pts["bau.achou_o"] + nome + pts["bau.ponto"], "t")
    assert len(texto) == 30
    vram = (cap / "item.vram").read_bytes()
    for lin, conteudo in ((9, _centrada(texto)), (8, b" " * 30)):
        linha = _linha_janela(vram, lin)
        assert linha[0] == linha[31] == 0x87A1, lin
        assert bytes(w & 0xFF for w in linha[1:31]) == conteudo, lin
    ram = (cap / "item.ram").read_bytes()
    letras = TABELA.codificar(nome, "t")
    assert ram[BUFFER_NOME_ITEM:BUFFER_NOME_ITEM + len(letras)] == b" " * len(letras)
    assert ram[BUFFER_NOME_ITEM_LETRAS:BUFFER_NOME_ITEM_LETRAS + len(letras)] == letras
    assert ram[ANTIGO:ANTIGO + 0x20] == bytes(0x20)
    from PIL import Image

    with Image.open(cap / "item.png") as im:
        im.crop((0, 56, im.width, 88)).resize((im.width * 3, 96), Image.NEAREST).save(
            RAIZ / "build" / "capturas" / "bau_nome_longo_zoom.png")


# Estalagem -> reinicia -> CONTINUE (o roteiro de testes/test_patches.py) na ROM do build
# (todos os patches) e nela com os patches do buffer desfeitos: tudo igual. A área nova
# (64 bytes) recebe um padrão logo depois da limpeza da RAM do boot (e de novo depois do
# reset) na ROM sem o buffer novo: o padrão sobrevive e o jogo fica idêntico.
_SCRIPT_SAVE = r'''
import hashlib, json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from ferramentas.emulador.libretro import CORE_PADRAO, Emulador

saida = Path(sys.argv[3]); canario = sys.argv[4] == "1"
LO, HI = 0xAB00, 0xAB40
PADRAO = bytes((0x5A ^ (7 * i)) & 0xFF for i in range(HI - LO))
emu = Emulador(CORE_PADRAO, Path(sys.argv[2]))
intacto = []
def cena(nome):
    emu.quadro_png(saida / f"{nome}.png")
    ram = emu.ram()
    intacto.append(ram[LO:HI] == PADRAO)
    return hashlib.sha1(ram[:LO] + ram[HI:]).hexdigest()
emu.avancar(10)                          # a limpeza da RAM do boot acaba no 2.o quadro
if canario: emu.escrever_ram(LO, PADRAO)
emu.avancar(290); emu.avancar(2, {"start"}); emu.avancar(100); emu.avancar(80)
emu.avancar(2, {"start"}); emu.avancar(80)
h = [cena("menu_sem_save")]
emu.avancar(2, {"start"}); emu.avancar(600)
for _ in range(10):
    emu.avancar(2, {"c"}); emu.avancar(600)
emu._lib.retro_reset()
emu.avancar(10)
if canario: emu.escrever_ram(LO, PADRAO)
emu.avancar(290); emu.avancar(2, {"start"}); emu.avancar(240)
emu.avancar(2, {"start"}); emu.avancar(80)
h.append(cena("menu"))
emu.avancar(2, {"baixo"}); emu.avancar(30)
h.append(cena("menu_continue"))
emu.avancar(2, {"start"}); emu.avancar(600)
h.append(cena("carregado"))
print(json.dumps({"ram": h, "intacto": intacto}))
emu.fechar()
'''


def test_save_e_load_com_todos_os_patches(rom_base, tmp_path):
    from PIL import Image, ImageChops

    from ferramentas.emulador.libretro import CORE_PADRAO

    if not CORE_PADRAO.is_file():
        pytest.skip("core libretro ausente")
    from test_nomes_menu import _trocar_dialogo_0

    (tmp_path / "proj").mkdir()
    com = bytearray(_trocar_dialogo_0(_construir(tmp_path / "proj", rom_base), 46))
    sem = bytearray(com)
    for p in _patches_buffer():
        assert com[p.end:p.end + len(p.novo)] == p.novo
        sem[p.end:p.end + len(p.original)] = p.original
    regiao = yaml.safe_load((RAIZ / "config" / "texto.yaml").read_text(encoding="utf-8"))[
        "regiao_destino"]
    rotina = bytes(sem).index(bytes.fromhex("42788D1042788CDE47F8AB00"), regiao[0])
    sem[rotina + 8:rotina + 12] = bytes.fromhex("47F88CE0")   # o preparo da rotina dos menus
    assert com != sem
    script = tmp_path / "save.py"
    script.write_text(_SCRIPT_SAVE, encoding="utf-8")
    procs = {}
    for nome, rom, canario in (("com", com, "0"), ("sem", sem, "0"), ("canario", sem, "1")):
        pasta = tmp_path / nome
        pasta.mkdir()
        (pasta / "rom.bin").write_bytes(bytes(rom))
        procs[nome] = subprocess.Popen(
            [sys.executable, str(script), str(RAIZ), str(pasta / "rom.bin"), str(pasta), canario],
            cwd=str(RAIZ), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    res = {}
    for nome, p in procs.items():
        out, err = p.communicate(timeout=900)
        assert p.returncode == 0, err.decode(errors="replace")[-2000:]
        res[nome] = json.loads(out.decode().strip().splitlines()[-1])

    def igual(x, y):
        with Image.open(x) as i, Image.open(y) as j:
            return ImageChops.difference(i.convert("RGB"), j.convert("RGB")).getbbox() is None

    telas = ("menu_sem_save", "menu", "menu_continue", "carregado")
    d = tmp_path / "com"
    assert not igual(d / "menu_sem_save.png", d / "menu.png")       # apareceu o CONTINUE
    assert not igual(d / "menu_continue.png", d / "carregado.png")  # carregou
    for outro in ("sem", "canario"):
        for t in telas:
            assert igual(d / f"{t}.png", tmp_path / outro / f"{t}.png"), (outro, t)
        assert res[outro]["ram"] == res["com"]["ram"], outro
    assert res["canario"]["intacto"] == [True] * 4
    shutil.copy(d / "carregado.png", RAIZ / "build" / "capturas" / "save_todos_patches.png")
