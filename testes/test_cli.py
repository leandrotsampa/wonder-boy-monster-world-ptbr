import pytest
import yaml

from ferramentas import cli
from ferramentas.cli import main
from ferramentas.ips import aplicar_ips
from ferramentas.rom import hashes


@pytest.fixture
def projeto(tmp_path, rom_sintetica, monkeypatch):
    # ROM sintética não tem texto: as etapas de inserção ficam de fora
    monkeypatch.setattr(cli, "ETAPAS", [])
    (tmp_path / "rom").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "traducao" / "textos").mkdir(parents=True)
    (tmp_path / "rom" / "base.bin").write_bytes(rom_sintetica)
    cfg = {"nome_arquivo": "base.bin", "sha1": hashes(bytes(rom_sintetica))["sha1"]}
    (tmp_path / "config" / "rom.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    (tmp_path / "traducao" / "tabela.tbl").write_text(
        "41=A\n4F=O\n69=i\n80=ã\nFF=[fim]\n", encoding="utf-8")
    (tmp_path / "traducao" / "glossario.yaml").write_text("[]\n", encoding="utf-8")
    return tmp_path


def _textos(raiz, conteudo):
    (raiz / "traducao" / "textos" / "t.yaml").write_text(conteudo, encoding="utf-8")


def _cfg_sha1(raiz, sha1):
    arq = raiz / "config" / "rom.yaml"
    cfg = yaml.safe_load(arq.read_text(encoding="utf-8"))
    cfg["sha1"] = sha1
    arq.write_text(yaml.safe_dump(cfg), encoding="utf-8")


def test_checar_rom_ok(projeto):
    assert main(["--raiz", str(projeto), "checar-rom"]) == 0


def test_checar_rom_sem_hash_configurado(projeto, capsys):
    _cfg_sha1(projeto, None)
    assert main(["--raiz", str(projeto), "checar-rom"]) == 0
    assert "sha1" in capsys.readouterr().out.lower()


def test_checar_rom_errada(projeto, capsys):
    _cfg_sha1(projeto, "00" * 20)
    assert main(["--raiz", str(projeto), "checar-rom"]) == 1
    assert "esperado" in capsys.readouterr().err


def test_verificar_ok_e_erro(projeto):
    _textos(projeto, "- {id: a, en: Hi, pt: Oi, status: traduzido}\n")
    assert main(["--raiz", str(projeto), "verificar"]) == 0
    _textos(projeto, "- {id: a, en: Hi, pt: Oç, status: traduzido}\n")
    assert main(["--raiz", str(projeto), "verificar"]) == 1


def test_construir_gera_artefatos(projeto, rom_sintetica):
    assert main(["--raiz", str(projeto), "construir"]) == 0
    b = projeto / "build"
    rom = (b / "wbmw-ptbr.bin").read_bytes()
    assert (b / "relatorio.txt").is_file()
    assert aplicar_ips(bytes(rom_sintetica), (b / "wbmw-ptbr.ips").read_bytes()) == rom


def test_construir_deterministico(projeto):
    b = projeto / "build"
    main(["--raiz", str(projeto), "construir"])
    primeiro = ((b / "wbmw-ptbr.bin").read_bytes(), (b / "wbmw-ptbr.ips").read_bytes())
    main(["--raiz", str(projeto), "construir"])
    assert primeiro == ((b / "wbmw-ptbr.bin").read_bytes(), (b / "wbmw-ptbr.ips").read_bytes())


def test_construir_com_erro_nao_grava(projeto):
    _textos(projeto, "- {id: a, en: Hi, pt: Oç, status: traduzido}\n")
    assert main(["--raiz", str(projeto), "construir"]) == 1
    assert not (projeto / "build").exists()


def test_construir_rom_errada_nao_grava(projeto):
    _cfg_sha1(projeto, "00" * 20)
    assert main(["--raiz", str(projeto), "construir"]) == 1
    assert not (projeto / "build").exists()


def test_yaml_quebrado_sem_traceback(projeto, capsys):
    _textos(projeto, "- {id: [\n")
    assert main(["--raiz", str(projeto), "verificar"]) == 1
    assert "Traceback" not in capsys.readouterr().err


def test_relatorio_progresso(projeto):
    _textos(projeto, "- {id: a, en: Hi, pt: Oi, status: traduzido}\n- {id: b, en: Yo}\n")
    assert main(["--raiz", str(projeto), "construir"]) == 0
    assert "50%" in (projeto / "build" / "relatorio.txt").read_text(encoding="utf-8")


def test_saida_unicode_sem_crash(projeto):
    import subprocess
    import sys
    _textos(projeto, "- {id: a, en: Hi, pt: \"A♪\", status: traduzido}\n")
    r = subprocess.run([sys.executable, "-m", "ferramentas", "--raiz", str(projeto), "verificar"],
                       capture_output=True, cwd=str(__import__("pathlib").Path(__file__).parent.parent))
    assert r.returncode == 1
    assert b"Traceback" not in r.stderr
    assert "♪".encode("utf-8") in r.stdout


def test_construir_sem_sha1_recusa(projeto, capsys):
    _cfg_sha1(projeto, None)
    assert main(["--raiz", str(projeto), "construir"]) == 1
    assert "sha1" in capsys.readouterr().err
    assert not (projeto / "build").exists()
