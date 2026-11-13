"""Strings inline repontáveis: texto novo em espaço livre e instruções repontadas."""

from pathlib import Path

import pytest
import yaml

from ferramentas.config import ErroConfig, Projeto, carregar_cfg_texto
from ferramentas.patches import Patch
from ferramentas.repontavel import (ajustes_repontaveis, aplicar_repontaveis, checar_repontaveis,
                                    etapa_repontavel, extrair_repontaveis, itens_repontaveis,
                                    planejar_repontaveis)
from ferramentas.script.montador import ErroMontagem
from ferramentas.tabela import Tabela
from ferramentas.textos import Entrada, carregar_textos
from ferramentas.verificacao import Contexto

RAIZ = Path(__file__).resolve().parent.parent
TABELA = Tabela.carregar(RAIZ / "traducao" / "tabela.tbl")

# ROM sintética: código em 0x100, string "Found " em 0x200, rotina em 0x180, livre em 0x400
LEA_BSR = 0x100       # lea $200(pc),a0 ; bsr.w $180
LEA_SO = 0x108        # lea $200(pc),a1
ABS = 0x10C           # move.l #$200,d0 -> operando em 0x10E
ADDI = 0x112          # addi.w #$1,d0 -> imediato em 0x114
STRING = 0x200
LIVRE = (0x400, 0x500)


def _rom() -> bytearray:
    rom = bytearray(b"\x4E\x71" * 0x100 + b"\xFF" * 0x400)
    rom[LEA_BSR:LEA_BSR + 8] = bytes.fromhex("41FA") + (STRING - (LEA_BSR + 2)).to_bytes(2, "big") \
        + bytes.fromhex("6100") + ((0x180 - (LEA_BSR + 6)) & 0xFFFF).to_bytes(2, "big")
    rom[LEA_SO:LEA_SO + 4] = bytes.fromhex("43FA") + (STRING - (LEA_SO + 2)).to_bytes(2, "big")
    rom[ABS:ABS + 6] = bytes.fromhex("203C") + STRING.to_bytes(4, "big")
    rom[ADDI:ADDI + 4] = bytes.fromhex("06400001")
    rom[STRING:STRING + 7] = b"Found \x00"
    return rom


def _item(**kw):
    it = {"id": "bau.achou", "end": STRING, "tam": 6,
          "refs": [{"end": LEA_BSR, "tipo": "lea_pc_bsr"}]}
    it.update(kw)
    return it


def _ajuste(**kw):
    aj = {"id": "bau.centro", "end": ADDI + 2, "base": -5, "soma": ["bau.achou"],
          "largura": {"max": 20, "variavel": 4}}
    aj.update(kw)
    return aj


def _projeto(tmp_path, itens, textos, ajustes=(), regiao=LIVRE):
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "traducao" / "textos").mkdir(parents=True, exist_ok=True)
    cfg = {"regiao_destino": list(regiao),
           "inline_repontavel": {"itens": itens, "ajustes": list(ajustes)}}
    (tmp_path / "config" / "texto.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    (tmp_path / "traducao" / "tabela.tbl").write_text(
        (RAIZ / "traducao" / "tabela.tbl").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "traducao" / "textos" / "inline.yaml").write_text(
        yaml.safe_dump(textos, allow_unicode=True), encoding="utf-8")
    return Projeto(raiz=tmp_path, rom={})


def _cfg(itens, ajustes=()):
    return {"inline_repontavel": {"itens": itens, "ajustes": list(ajustes)}}


def _desmontar(dados: bytes, end: int) -> list[tuple[str, str]]:
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_M68K_000)
    return [(i.mnemonic, i.op_str.replace(" ", "")) for i in md.disasm(dados, end)]


# ------------------------------------------------------------- config

def test_config_valida_e_vazia():
    assert itens_repontaveis({}) == [] and ajustes_repontaveis({}) == []
    assert itens_repontaveis(_cfg([_item()]))[0]["id"] == "bau.achou"


@pytest.mark.parametrize("ruim, msg", [
    ({"tam": 0}, "tam"),
    ({"end": "x"}, "end"),
    ({"refs": []}, "refs"),
    ({"refs": [{"end": 0x100, "tipo": "jmp"}]}, "tipo"),
    ({"refs": [{"end": 0x101, "tipo": "lea_pc"}]}, "par"),
])
def test_config_item_invalido(ruim, msg):
    with pytest.raises(ErroConfig, match=msg):
        itens_repontaveis(_cfg([_item(**ruim)]))


def test_config_id_duplicado_e_refs_sobrepostas():
    with pytest.raises(ErroConfig, match="duplicado"):
        itens_repontaveis(_cfg([_item(), _item()]))
    with pytest.raises(ErroConfig, match="sobrep"):
        itens_repontaveis(_cfg([_item(), _item(id="b", refs=[{"end": LEA_BSR + 4,
                                                               "tipo": "lea_pc"}])]))


def test_config_ajuste_invalido():
    with pytest.raises(ErroConfig, match="soma"):
        ajustes_repontaveis(_cfg([_item()], [_ajuste(soma=["nada"])]))
    with pytest.raises(ErroConfig, match="largura"):
        ajustes_repontaveis(_cfg([_item()], [_ajuste(largura={"max": 20})]))


def test_config_nao_repete_id_do_inline_fixo():
    cfg = _cfg([_item()])
    cfg["inline"] = [{"id": "bau.achou", "end": 0x300, "tam": 2, "preencher": "espaco"}]
    with pytest.raises(ErroConfig, match="inline"):
        itens_repontaveis(cfg)


# ------------------------------------------------------------- build

def test_extrair_en():
    es = extrair_repontaveis(bytes(_rom()), [_item()], TABELA)
    assert [(e.id, e.en) for e in es] == [("bau.achou", "Found ")]


def test_pt_vazio_nao_muda_nada(tmp_path):
    p = _projeto(tmp_path, [_item()], [{"id": "bau.achou", "en": "Found ", "pt": ""}],
                 [_ajuste()])
    rom = _rom()
    etapa_repontavel(rom, p)
    assert rom == _rom()
    assert p.regiao is None   # nada reservado


def test_lea_pc_bsr_vira_lea_abs_e_bsr_curto(tmp_path):
    p = _projeto(tmp_path, [_item()], [{"id": "bau.achou", "en": "Found ", "pt": "Você achou "}])
    rom = _rom()
    etapa_repontavel(rom, p)
    novo = LIVRE[0]
    dados = TABELA.codificar("Você achou ", "t") + b"\x00"
    assert rom[novo:novo + len(dados)] == dados
    assert _desmontar(bytes(rom[LEA_BSR:LEA_BSR + 8]), LEA_BSR) == [
        ("lea.l", f"${novo:x}.l,a0"), ("bsr.b", "$180")]
    # texto antigo e o resto do código intactos
    fora = [i for i in range(len(rom)) if rom[i] != _rom()[i]
            and not LEA_BSR <= i < LEA_BSR + 8 and not novo <= i < novo + len(dados)]
    assert fora == []
    assert p.regiao.usos == [("inline:bau.achou", novo, len(dados))]


def test_lea_pc_no_alcance_so_troca_deslocamento():
    rom = _rom()
    it = _item(refs=[{"end": LEA_SO, "tipo": "lea_pc"}])
    plano = planejar_repontaveis(rom, [it], [], {"bau.achou": "Achou "}, TABELA,
                                 lambda nome, tam: 0x300)
    aplicar_repontaveis(rom, plano)
    assert _desmontar(bytes(rom[LEA_SO:LEA_SO + 4]), LEA_SO) == [("lea.l", "$300(pc),a1")]


def test_lea_pc_fora_do_alcance_e_erro():
    it = _item(refs=[{"end": LEA_SO, "tipo": "lea_pc"}])
    with pytest.raises(ErroMontagem, match="alcance"):
        planejar_repontaveis(_rom(), [it], [], {"bau.achou": "Achou "}, TABELA,
                             lambda nome, tam: 0x20000)


def test_bsr_curto_fora_do_alcance_e_erro():
    rom = _rom()
    rom[LEA_BSR + 6:LEA_BSR + 8] = (0x7F00 - (LEA_BSR + 6)).to_bytes(2, "big")
    with pytest.raises(ErroMontagem, match="bsr"):
        planejar_repontaveis(rom, [_item()], [], {"bau.achou": "Achou "}, TABELA,
                             lambda nome, tam: 0x400)


def test_abs_l_troca_endereco():
    rom = _rom()
    it = _item(refs=[{"end": ABS + 2, "tipo": "abs_l"}])
    plano = planejar_repontaveis(rom, [it], [], {"bau.achou": "Achou "}, TABELA,
                                 lambda nome, tam: 0x412)
    aplicar_repontaveis(rom, plano)
    assert _desmontar(bytes(rom[ABS:ABS + 6]), ABS) == [("move.l", "#$412,d0")]


@pytest.mark.parametrize("tipo, end", [("lea_pc_bsr", LEA_SO), ("lea_pc", ABS),
                                       ("abs_l", LEA_BSR)])
def test_instrucao_original_diferente_e_erro(tipo, end):
    it = _item(refs=[{"end": end, "tipo": tipo}])
    with pytest.raises(ErroMontagem, match="esperad"):
        planejar_repontaveis(_rom(), [it], [], {"bau.achou": "Achou "}, TABELA,
                             lambda nome, tam: 0x400)


def test_ajuste_recalculado_e_conferido():
    rom = _rom()
    # original: base -5 + len("Found ") = 1
    plano = planejar_repontaveis(rom, [_item()], [_ajuste()], {"bau.achou": "Você achou "},
                                 TABELA, lambda nome, tam: 0x400)
    aplicar_repontaveis(rom, plano)
    assert rom[ADDI:ADDI + 4] == bytes.fromhex("06400006")
    errado = _rom()
    errado[ADDI + 3] = 2
    with pytest.raises(ErroMontagem, match="esperad"):
        planejar_repontaveis(errado, [_item()], [_ajuste()], {}, TABELA, lambda n, t: 0x400)


def test_ajuste_largura_estourada_e_erro():
    with pytest.raises(ErroMontagem, match="largura"):
        planejar_repontaveis(_rom(), [_item()], [_ajuste()],
                             {"bau.achou": "Você encontrou aqui "}, TABELA, lambda n, t: 0x400)


def test_sobreposicao_com_patch_e_erro(tmp_path):
    p = _projeto(tmp_path, [_item()], [{"id": "bau.achou", "en": "Found ", "pt": "Achou "}])
    (tmp_path / "config" / "patches.yaml").write_text(yaml.safe_dump({"patches": [
        {"id": "x", "end": LEA_BSR + 6, "original": "6100", "novo": "4E71"}]}), encoding="utf-8")
    rom = _rom()
    with pytest.raises(ErroConfig, match="patch"):
        etapa_repontavel(rom, p)
    assert rom == _rom()


def test_checar_repontaveis():
    ctx = Contexto(tabela=TABELA, textos={"inline": [Entrada("bau.achou", "Found ",
                                                             pt="Você encontrou aqui ")]},
                   glossario=[], extra={"repontavel": [_item()], "repontavel_ajustes": [_ajuste()]})
    achados = checar_repontaveis(ctx)
    assert [a.nivel for a in achados] == ["erro"] and "largura" in achados[0].mensagem
    ctx.textos["inline"][0].pt = "Achou "
    assert checar_repontaveis(ctx) == []
    ctx.textos["inline"][0].pt = "Achou [nada]"
    assert [a.nivel for a in checar_repontaveis(ctx)] == ["erro"]


# ------------------------------------------------------------- ROM real

IDS_BAU = ["bau.achou_o", "bau.ponto", "bau.achou", "bau.ouro"]


def test_config_real_baus(rom_base):
    cfg = carregar_cfg_texto(RAIZ)
    itens = itens_repontaveis(cfg)
    assert [it["id"] for it in itens] == IDS_BAU
    en = {e.id: e.en for e in extrair_repontaveis(rom_base, itens, TABELA)}
    assert en == {"bau.achou_o": "Found the ", "bau.ponto": ".", "bau.achou": "Found ",
                  "bau.ouro": " GOLD."}
    # saíram da lista de tamanho fixo (nada grava duas vezes); status.ouro não tem leitor
    fixos = {it["id"] for it in cfg["inline"]}
    assert not fixos & set(IDS_BAU) and "status.ouro" not in fixos
    # as referências e os ajustes conferem com a ROM base (sem tradução, nada muda)
    rom = bytearray(rom_base)
    plano = planejar_repontaveis(rom, itens, ajustes_repontaveis(cfg), {}, TABELA,
                                 lambda n, t: pytest.fail("não devia reservar"))
    aplicar_repontaveis(rom, plano)
    assert rom == rom_base


def test_auditoria_referencias(rom_base):
    """Toda instrução do código que aponta para as strings do baú (PC-relativo, absoluto ou
    imediato) está na config; o "GOLD" de 0x84E7 só era lido pelo HUD (patch da Task 1)."""
    from ferramentas.patches import aplicar_patches, carregar_patches
    from ferramentas.script.auditoria import referencias_a

    cfg = carregar_cfg_texto(RAIZ)
    for it in itens_repontaveis(cfg):
        achadas = referencias_a(rom_base, it["end"], it["end"] + it["tam"])
        assert sorted(achadas) == sorted(r["end"] for r in it["refs"]), it["id"]
    assert referencias_a(rom_base, 0x84E7, 0x84EC) == [0x85A0]
    rom = bytearray(rom_base)
    aplicar_patches(rom, carregar_patches(Projeto(raiz=RAIZ, rom={})))
    assert referencias_a(bytes(rom), 0x84E7, 0x84EC) == []
    # AP/DP/SP: um lea só (0x84C8), o laço de 0x84CE lê as 3 em sequência
    assert referencias_a(rom_base, 0x84DE, 0x84E7) == [0x84C8]


def test_ajustes_reais_centralizam(rom_base):
    """Os imediatos de centralização (addi.w #6/#5,d0) batem com os tamanhos originais."""
    cfg = carregar_cfg_texto(RAIZ)
    ajs = {a["id"]: a for a in ajustes_repontaveis(cfg)}
    assert _desmontar(rom_base[0x1EF8:0x1EFC], 0x1EF8) == [("addi.w", "#$6,d0")]
    assert _desmontar(rom_base[0x1F5C:0x1F60], 0x1F5C) == [("addi.w", "#$5,d0")]
    assert ajs["bau.centro_item"]["end"] == 0x1EFA and ajs["bau.centro_ouro"]["end"] == 0x1F5E


def test_textos_inline_tem_os_ids():
    entradas = {e.id: e for e in carregar_textos(RAIZ / "traducao" / "textos" / "inline.yaml")}
    assert set(IDS_BAU) <= set(entradas) and "status.ouro" not in entradas
    assert "MOEDAS" in entradas["bau.ouro"].pt


def test_build_real_reponta_baus(rom_base, tmp_path):
    import shutil

    from ferramentas.cli import main

    for rel in ("config", "traducao", "graficos"):
        shutil.copytree(RAIZ / rel, tmp_path / rel)
    (tmp_path / "dados" / "scripts").mkdir(parents=True)
    shutil.copy(RAIZ / "dados" / "scripts" / "esqueleto.json", tmp_path / "dados" / "scripts")
    arq = tmp_path / "base.bin"
    arq.write_bytes(rom_base)
    assert main(["--raiz", str(tmp_path), "construir", "--rom", str(arq)]) == 0
    rom = (tmp_path / "build" / "wbmw-ptbr.bin").read_bytes()
    pts = {e.id: e.pt for e in carregar_textos(RAIZ / "traducao" / "textos" / "inline.yaml")}
    cfg = carregar_cfg_texto(RAIZ)
    for it in itens_repontaveis(cfg):
        ref = it["refs"][0]["end"]
        ins = _desmontar(rom[ref:ref + 8], ref)
        assert ins[0][0] == "lea.l" and ins[1] == ("bsr.b", "$1f8e"), ins
        novo = int(ins[0][1].split(".")[0][1:], 16)
        assert novo >= cfg["regiao_destino"][0]
        dados = TABELA.codificar(pts[it["id"]], it["id"]) + b"\x00"
        assert rom[novo:novo + len(dados)] == dados
        assert rom[it["end"]:it["end"] + it["tam"]] == rom_base[it["end"]:it["end"] + it["tam"]]
    ln = {k: len(TABELA.codificar(pts[k], k)) for k in IDS_BAU}
    assert int.from_bytes(rom[0x1EFA:0x1EFC], "big") == ln["bau.achou_o"] + ln["bau.ponto"] - 5
    assert int.from_bytes(rom[0x1F5E:0x1F60], "big") == ln["bau.achou"] + ln["bau.ouro"] - 7


# ------------------------------------------------------------- no jogo

# Truque para abrir as mensagens do baú sem achar um baú: só na ROM de teste, o início de
# 0x400 (troca de tarefa, chamada pelas tarefas a cada quadro) vira 'jmp' para um toco em
# espaço livre (0x9F900) que, se o ouro ($FF962C) tiver um valor mágico (maior que o
# limite 999999, impossível no jogo), zera o ouro e chama a rotina do baú de ouro
# (0x1FCA, d0 = valor) ou do baú de item (0x1FD0, d0 = item), com os registradores
# salvos, e segue a troca de tarefa original.
GANCHO, TOCO = 0x400, 0x9F900
MAGICO_OURO, MAGICO_ITEM = 0xABCDE0, 0xABCDE1
VALOR_OURO = 999999          # 6 dígitos: a linha mais larga possível
ITEM_LONGO = 0x0E            # b1.00E "Leather Armor" (13 letras, o maior nome em inglês)


def _toco() -> bytes:
    def chamar(arg: int, rotina: int) -> bytes:
        return (bytes.fromhex("42B8962C48E7FFFE203C") + arg.to_bytes(4, "big")    # clr.l; movem
                + bytes.fromhex("4EB8") + rotina.to_bytes(2, "big")               # jsr rotina.w
                + bytes.fromhex("4CDF7FFF"))                                       # movem
    original = bytes.fromhex("3A788A4C205F4EF9") + (GANCHO + 6).to_bytes(4, "big")
    c_ouro, c_item = chamar(VALOR_OURO, 0x1FCA), chamar(ITEM_LONGO, 0x1FD0)
    p_orig = 20
    p_ouro = p_orig + len(original)
    p_item = p_ouro + len(c_ouro) + 2
    cod = bytearray(bytes.fromhex("0CB8") + MAGICO_OURO.to_bytes(4, "big") + b"\x96\x2C")
    cod += bytes([0x67, p_ouro - (len(cod) + 2)])
    cod += bytes.fromhex("0CB8") + MAGICO_ITEM.to_bytes(4, "big") + b"\x96\x2C"
    cod += bytes([0x67, p_item - (len(cod) + 2)])
    cod += original + c_ouro
    cod += bytes([0x60, (p_orig - (len(cod) + 2)) & 0xFF])
    cod += c_item
    cod += bytes([0x60, (p_orig - (len(cod) + 2)) & 0xFF])
    return bytes(cod)


def _com_gancho(rom: bytes) -> bytes:
    rom = bytearray(rom)
    toco = _toco()
    assert set(rom[TOCO:TOCO + len(toco)]) == {0xFF}
    assert rom[GANCHO:GANCHO + 6] == bytes.fromhex("3A788A4C205F")
    rom[TOCO:TOCO + len(toco)] = toco
    rom[GANCHO:GANCHO + 6] = bytes.fromhex("4EF9") + TOCO.to_bytes(4, "big")
    return bytes(rom)


def test_toco_desmonta():
    ins = _desmontar(_toco(), TOCO)
    assert ins[:7] == [("cmpi.l", f"#${MAGICO_OURO:x},$962c.w"), ("beq.b", "$9f920"),
                       ("cmpi.l", f"#${MAGICO_ITEM:x},$962c.w"), ("beq.b", "$9f938"),
                       ("movea.w", "$8a4c.w,a5"), ("movea.l", "(a7)+,a0"), ("jmp", "$406.l")]
    assert ("jsr", "$1fca.w") in ins and ("jsr", "$1fd0.w") in ins
    assert ins.count(("bra.b", "$9f914")) == 2


# Processo à parte (o emulador da sessão está preso à ROM base): NEW GAME, fala de
# abertura, sai de casa; daí, para cada baú, põe o valor mágico no ouro e grava tela e
# VRAM 20 quadros depois; por fim abre o menu do START (tela de status).
_SCRIPT_BAU = r'''
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from ferramentas.emulador.libretro import CORE_PADRAO, Emulador

saida = Path(sys.argv[3])
saida.mkdir(parents=True, exist_ok=True)
emu = Emulador(CORE_PADRAO, Path(sys.argv[2]))
emu.avancar(300); emu.avancar(2, {"start"}); emu.avancar(240)
for _ in range(3):
    emu.avancar(2, {"start"}); emu.avancar(120)
for _ in range(144):
    emu.avancar(2, {"c"}); emu.avancar(18)
emu.avancar(20, {"baixo"}); emu.avancar(60)
campo = emu.salvar_estado()
for nome, magico in (("ouro", MAGICO_OURO), ("item", MAGICO_ITEM)):
    emu.carregar_estado(campo)
    emu.escrever_ram(0x962C, magico.to_bytes(4, "big"))
    emu.avancar(20)
    emu.quadro_png(saida / f"{nome}.png")
    (saida / f"{nome}.vram").write_bytes(emu.vram())
    (saida / f"{nome}.ram").write_bytes(emu.ram())
emu.carregar_estado(campo)
emu.avancar(2, {"start"}); emu.avancar(30)
emu.quadro_png(saida / "status.png")
(saida / "status.vram").write_bytes(emu.vram())
emu.fechar()
'''.replace("MAGICO_OURO", str(MAGICO_OURO)).replace("MAGICO_ITEM", str(MAGICO_ITEM))


def _rodar_bau(rom: Path, destino: Path) -> None:
    import subprocess
    import sys

    script = destino.parent / "bau.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(_SCRIPT_BAU, encoding="utf-8")
    r = subprocess.run([sys.executable, str(script), str(RAIZ), str(rom), str(destino)],
                       cwd=str(RAIZ), capture_output=True, timeout=900)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-2000:]


def _linha_janela(vram: bytes, lin: int) -> list[int]:
    return [int.from_bytes(vram[0xD800 + 2 * (32 * lin + c):][:2], "big") for c in range(32)]


def _centrada(texto: bytes) -> bytes:
    """As 30 colunas da mensagem como o jogo as monta: o texto começa (33 - L) & ~1 bytes
    depois da borda ($8D12), isto é, na coluna (33 - L) // 2 (a borda é a coluna 0)."""
    esq = (33 - len(texto)) // 2 - 1
    return b" " * esq + texto + b" " * (30 - esq - len(texto))


def _tem_gold(vram: bytes) -> bool:
    """Algum tilemap com G, O, L, D seguidos (mesmos atributos)."""
    for i in range(0xC000, 0x10000 - 8, 2):
        w = [int.from_bytes(vram[i + 2 * k:i + 2 * k + 2], "big") for k in range(4)]
        if bytes(x & 0xFF for x in w) == b"GOLD" and len({x >> 8 for x in w}) == 1:
            return True
    return False


def test_baus_e_status_no_jogo(rom_base, tmp_path):
    import shutil

    from PIL import Image

    from ferramentas.cli import main
    from ferramentas.emulador.libretro import CORE_PADRAO

    if not CORE_PADRAO.is_file():
        pytest.skip("core libretro ausente")
    for rel in ("config", "traducao", "graficos"):
        shutil.copytree(RAIZ / rel, tmp_path / rel)
    (tmp_path / "dados" / "scripts").mkdir(parents=True)
    shutil.copy(RAIZ / "dados" / "scripts" / "esqueleto.json", tmp_path / "dados" / "scripts")
    arq_base = tmp_path / "base.bin"
    arq_base.write_bytes(rom_base)
    assert main(["--raiz", str(tmp_path), "construir", "--rom", str(arq_base)]) == 0
    teste_base, teste_nova = tmp_path / "teste_base.bin", tmp_path / "teste_nova.bin"
    teste_base.write_bytes(_com_gancho(rom_base))
    teste_nova.write_bytes(_com_gancho((tmp_path / "build" / "wbmw-ptbr.bin").read_bytes()))
    cap_base = RAIZ / "build" / "capturas" / "bau_base"
    cap_nova = RAIZ / "build" / "capturas" / "bau_ptbr"
    _rodar_bau(teste_base, cap_base)
    _rodar_bau(teste_nova, cap_nova)

    pts = {e.id: e.pt for e in carregar_textos(RAIZ / "traducao" / "textos" / "inline.yaml")}
    # item 0x0E: o baú mostra o nome completo do banco 1 (no menu ele tem nome curto,
    # traducao/textos/banco1_menu.yaml; testes/test_nomes_menu.py)
    b1 = {e.id: e for e in carregar_textos(RAIZ / "traducao" / "textos" / "banco1_itens.yaml")}
    nome = b"Leather Armor"
    nome_pt = TABELA.codificar(b1["b1.00E.t00"].pt or b1["b1.00E.t00"].en, "b1.00E")
    num = str(VALOR_OURO).encode()

    def cod(id_: str) -> bytes:
        return TABELA.codificar(pts[id_], id_)
    esperado = {
        (cap_base, "ouro"): b"Found " + num + b" GOLD.",
        (cap_base, "item"): b"Found the " + nome + b".",
        (cap_nova, "ouro"): cod("bau.achou") + num + cod("bau.ouro"),
        (cap_nova, "item"): cod("bau.achou_o") + nome_pt + cod("bau.ponto"),
    }
    for (pasta, msg), texto in esperado.items():
        vram = (pasta / f"{msg}.vram").read_bytes()
        # mensagem na linha 9 da janela, entre as bordas (0x87A1), centrada; a linha 8
        # (marcas de cima, FE/FF) só tem espaços (o nome do item usa a paleta 1: 0xA020)
        for lin, conteudo in ((9, _centrada(texto)), (8, b" " * 30)):
            linha = _linha_janela(vram, lin)
            assert linha[0] == linha[31] == 0x87A1, (pasta.name, msg, lin)
            assert bytes(w & 0xFF for w in linha[1:31]) == conteudo, (pasta.name, msg, lin)
        if msg == "ouro":
            # só o valor em amarelo (paleta 1, 0xA0xx) na tradução (bau.valor_amarelo_*);
            # na base tudo branco (0x80xx)
            linha = _linha_janela(vram, 9)[1:31]
            ini = _centrada(texto).index(texto) + (len(cod("bau.achou")) if pasta == cap_nova
                                                    else len(b"Found "))
            altos = [w >> 8 for w in linha]
            amarelos = {i for i, a in enumerate(altos) if a == 0xA0}
            esperado_am = set(range(ini, ini + len(num))) if pasta == cap_nova else set()
            assert amarelos == esperado_am, (pasta.name, altos)
            assert all(a in (0x80, 0xA0) for a in altos), (pasta.name, altos)

    for msg in ("ouro", "item"):
        with Image.open(cap_base / f"{msg}.png") as a, Image.open(cap_nova / f"{msg}.png") as b:
            pa, pb = a.convert("RGB").load(), b.convert("RGB").load()
            linhas = {y // 8 for y in range(a.size[1]) for x in range(a.size[0])
                      if pa[x, y] != pb[x, y]}
        # muda só a mensagem (linha 9) e o rótulo do HUD (linhas 4-5, Task 1)
        assert 9 in linhas and linhas <= {4, 5, 9}, (msg, sorted(linhas))

    # tela de status (menu do START): não tem rótulo de ouro (o HUD da base tem); sem
    # AP/DP/SP traduzidos fica igual à da base
    assert _tem_gold((cap_base / "ouro.vram").read_bytes())
    assert not _tem_gold((cap_base / "status.vram").read_bytes())
    assert not _tem_gold((cap_nova / "status.vram").read_bytes())
    if not any(pts.get(k) for k in ("status.ap", "status.dp", "status.sp")):
        with Image.open(cap_base / "status.png") as a, Image.open(cap_nova / "status.png") as b:
            assert list(a.convert("RGB").getdata()) == list(b.convert("RGB").getdata())


# ------------------------------------------------------------- correções (rodada 1)

@pytest.mark.parametrize("pt", ["Achou[linha]", "Achou [$05]", "[cor]Achou", "Achou [s0:02]"])
def test_tags_e_controles_recusados(pt):
    ctx = Contexto(tabela=TABELA, textos={"inline": [Entrada("bau.achou", "Found ", pt=pt)]},
                   glossario=[], extra={"repontavel": [_item()], "repontavel_ajustes": []})
    achados = checar_repontaveis(ctx)
    assert [a.nivel for a in achados] == ["erro"] and "só texto" in achados[0].mensagem
    with pytest.raises(ErroMontagem, match="só texto"):
        planejar_repontaveis(_rom(), [_item()], [], {"bau.achou": pt}, TABELA,
                             lambda n, t: 0x400)


def test_byte_de_controle_recusado():
    """Um caractere que a tabela codifique abaixo de 0x20 também é recusado."""
    tabela = Tabela({bytes([c]): chr(c) for c in range(0x41, 0x5B)} | {b"\x09": "~"})
    with pytest.raises(ErroMontagem, match="09"):
        planejar_repontaveis(_rom(), [_item()], [], {"bau.achou": "AB~C"}, tabela,
                             lambda n, t: 0x400)


def test_montagem_conta_repontaveis(tmp_path):
    from ferramentas.cli import _calcular_montagem

    p = _projeto(tmp_path, [_item(), _item(id="b", end=0x210, refs=[{"end": LEA_SO,
                                                                     "tipo": "lea_pc"}])], [])
    textos = {"inline": [Entrada("bau.achou", "Found ", pt="Você achou "),
                         Entrada("b", "x", pt="")]}
    ctx = Contexto(tabela=TABELA, textos=textos, glossario=[],
                   extra={"repontavel": itens_repontaveis(carregar_cfg_texto(tmp_path))})
    _calcular_montagem(p, ctx, fonte=7, graficos=3)
    m = ctx.extra["montagem"]
    n = len(TABELA.codificar("Você achou ", "t")) + 1   # texto + 00; "b" sem pt não conta
    assert m["inline"] == n and m["usado"] == n + 7 + 3
    assert (m["destino"], m["limite"]) == LIVRE


def test_max_nome_item_vem_do_buffer(rom_base):
    """0x1E6A grava a linha de cima (marcas FE/FF) com 'lea buffer.w,a3; move.b d2,(a3)+'
    e as letras com 'move.b d3,$xx(a3)'; os patches buffer_nome.* levam o buffer de
    $8CE0/$8CF0 (16 colunas) para $AB00/$AB20 (32). A largura do baú usa o limite."""
    from ferramentas.patches import aplicar_patches, carregar_patches
    from ferramentas.verificacao import BUFFER_NOME_ITEM, BUFFER_NOME_ITEM_LETRAS, MAX_NOME_ITEM

    rom = bytearray(rom_base)
    aplicar_patches(rom, carregar_patches(Projeto(raiz=RAIZ, rom={})))
    assert _desmontar(rom[0x1E72:0x1E76], 0x1E72) == [("lea.l", f"${BUFFER_NOME_ITEM:x}.w,a3")]
    assert _desmontar(rom[0x1EC4:0x1ECA], 0x1EC4) == [
        ("move.b", f"d3,${BUFFER_NOME_ITEM_LETRAS - BUFFER_NOME_ITEM:x}(a3)"),
        ("move.b", "d2,(a3)+")]
    assert MAX_NOME_ITEM == 18
    ajs = {a["id"]: a for a in ajustes_repontaveis(carregar_cfg_texto(RAIZ))}
    assert ajs["bau.centro_item"]["largura"]["variavel"] == MAX_NOME_ITEM


def test_checar_nomes_itens():
    from ferramentas.verificacao import checar_nomes_itens

    def ctx(*entradas):
        return Contexto(tabela=TABELA, textos={"banco1_itens": list(entradas)}, glossario=[])
    ok = Entrada("b1.00E.t00", "Leather Armor", pt="Armadura de Couro")   # 17
    assert checar_nomes_itens(ctx(ok)) == []
    longo = Entrada("b1.00E.t00", "Leather Armor", pt="Armadura de Couro Velho")   # 23
    achados = checar_nomes_itens(ctx(longo))
    assert [(a.nivel, a.local) for a in achados] == [("erro", "banco1_itens:b1.00E.t00")]
    assert "23" in achados[0].mensagem and "18" in achados[0].mensagem
    assert "linha de cima em $AB00" in achados[0].mensagem
    assert "letras em $AB20" in achados[0].mensagem
    # aninhado: "Grande " (7) + b1.002 "Espada de Cristal" (17) = 24 -> erro só no b1.001
    pai = Entrada("b1.001.t00", "x", pt="Grande [item:02]")
    filho = Entrada("b1.002.t00", "x", pt="Espada de Cristal")
    assert [a.local for a in checar_nomes_itens(ctx(pai, filho))] == ["banco1_itens:b1.001.t00"]


def test_nomes_itens_atuais_passam():
    from ferramentas.textos import carregar_todos
    from ferramentas.verificacao import checar_nomes_itens

    textos = carregar_todos(RAIZ / "traducao" / "textos")
    assert checar_nomes_itens(Contexto(tabela=TABELA, textos=textos, glossario=[])) == []
