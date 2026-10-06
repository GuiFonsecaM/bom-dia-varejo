#!/usr/bin/env python3
"""
BOM DIA, VAREJO — gerador automático de vídeo vertical (9:16, ~75 s)
                  e de imagens para stories (1080x1920, mesmo visual do vídeo)

Como usar:
  python gera-video.py                  -> cole o JSON no terminal
  python gera-video.py roteiro.json     -> lê o JSON de um arquivo
  python gera-video.py --story          -> força o modo stories (imagens)
  python gera-video.py --feed           -> força o modo feed (até 5 imagens)
  python gera-video.py --testar-vozes   -> gera amostras de todas as vozes pt-BR

Modo servidor (GitHub Actions), sem janelas nem perguntas:
  python gera-video.py roteiro.json --categoria noticia --saida saida

O modo stories é escolhido sozinho quando o JSON tem a lista "stories"
(ou "formato": "story"). Antes de salvar, o script pergunta se o conteúdo é
NOTÍCIA ou CURIOSIDADE e coloca isso no nome do arquivo, para não haver
arquivos com o mesmo nome na pasta.

Música de fundo: coloque arquivos .mp3 numa pasta "musicas" ao lado do script.
  A cada vídeo, uma delas é sorteada.

Instalação (só uma vez):
  pip install edge-tts "moviepy>=2" requests pillow numpy

Banco de imagens (grátis): Pixabay -> https://pixabay.com/api/docs/
  Crie uma conta, copie a chave e cole em PIXABAY_API_KEY abaixo.
  (Pexels também funciona, se você já tiver uma chave.)

Vídeo: foto fixa escurecida, selo com logo no topo e legenda montada palavra por
  palavra, sincronizada com a voz. Na narração, **palavras entre asteriscos** saem em
  laranja, negrito e maiores (os asteriscos não são lidos). Sem asteriscos na cena,
  os números viram destaque. O "texto_tela" vira a etiqueta laranja da cena.

Resultado: uma janela do Explorador abre para você escolher onde salvar.
  Vídeo:   [data]_bom-dia-varejo_[noticia|curiosidade].mp4  + _legendas.txt
  Stories: [data]_story_[noticia|curiosidade].jpg  (uma imagem por JSON)
           Coloque um logo.png ao lado do script para usar seu logo na barra branca.
"""

import asyncio
import json
import os
import re
import random
import shutil
import sys
import tempfile
import time
from pathlib import Path

import edge_tts
import numpy as np
import requests
from moviepy import (AudioFileClip, ColorClip, CompositeAudioClip,
                     CompositeVideoClip, ImageClip, VideoClip, VideoFileClip,
                     afx, concatenate_videoclips, vfx)
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

# ============================ CONFIGURAÇÃO ============================
def _chave_local(nome_arquivo):
    """Lê a chave de um .txt ao lado do script (só no seu PC; nunca suba para o GitHub)."""
    arq = Path(__file__).resolve().parent / nome_arquivo
    return arq.read_text(encoding="utf-8").strip() if arq.exists() else ""


# No GitHub, as chaves vêm dos Secrets. No PC, de chave_pixabay.txt / chave_pexels.txt.
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY") or _chave_local("chave_pixabay.txt")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY") or _chave_local("chave_pexels.txt")
VOZ_PADRAO = "pt-BR-ThalitaMultilingualNeural"   # rode --testar-vozes e troque aqui
VELOCIDADE = "+20%"                   # aumente/diminua para ajustar a duração
TOM = "-2Hz"                         # grave/agudo: ex. "-4Hz" (mais sério), "+0Hz"
PASTA_INICIAL = Path.home() / "Videos"   # pasta sugerida na janela de salvar
PASTA_MUSICAS = Path(__file__).resolve().parent / "musicas"
VOLUME_MUSICA = 0.06                 # 0.06 = bem baixo | 0.15 = mais presente
APAGAR_TEMPORARIOS = True

W, H, FPS = 1080, 1920, 30
# Paleta: preto, branco e laranja
COR_DESTAQUE = (0, 0, 0)             # caixa de destaque: preta
COR_TEXTO_DESTAQUE = (255, 255, 255) # texto do destaque: branco
COR_TEXTO_MARCA = (255, 255, 255)    # nome do canal: branco
COR_MARCA = (0, 0, 0)                # selo do canal e fundo liso: preto
TAMANHO_LEGENDA = 54                 # legenda falada (antes era 74)
NOME_CANAL = "BOM DIA, VAREJO"
# Posições verticais (px) — afastadas da ilha/câmera e da barra do topo dos apps
Y_MARCA = 250        # selo "BOM DIA, VAREJO"
Y_FONTE = 365        # linha "Fonte: ..."
Y_DESTAQUE = int(1920 * 0.33)  # caixa de destaque da cena
DURACAO_MINIMA = 61                  # TikTok só monetiza vídeos com mais de 1 min
MIN_PALAVRAS_CENA = 8                # cenas menores são juntadas à seguinte
TRANSICAO = 0.3                      # segundos de fusão suave entre as cenas
# Visual do vídeo: foto estática bem escura + legenda montada palavra por palavra
OPACIDADE_FOTO = 0.30                # 0 = fundo preto liso | 1 = foto sem escurecer
DESFOQUE_FOTO = 3                    # desfoque leve da foto, para o texto se destacar
Y_SELO_VIDEO = 150                   # selo com logo e nome no topo
Y_CHAPEU = 470                       # etiqueta laranja da cena (texto_tela)
Y_TEXTO_INI, Y_TEXTO_FIM = 560, 1420 # área da legenda
X_TEXTO = 90                         # margem lateral da legenda
TAM_PALAVRA = 80                     # palavras normais (branco)
TAM_DESTAQUE = 100                   # palavras de destaque (laranja, negrito)
Y_FONTE_VIDEO = 1465                 # "Fonte: ..." (acima da área de legenda do Reels)
# Stories (imagem estática)
PASTA_INICIAL_STORIES = Path.home() / "Pictures"
# Visual do story (estilo manchete de portal): barra branca + fundo preto
STORY_TOPO_LIVRE = 230               # faixa preta no topo: indicadores e perfil do Instagram
STORY_ALT_BARRA = 170                # altura da barra branca
STORY_BASE_LIVRE = 300               # faixa livre embaixo: campo de resposta
STORY_MARGEM = 72                    # margem lateral do texto
STORY_TITULO = 104                   # tamanho máximo do título (diminui sozinho se faltar espaço)
STORY_TEXTO = 46                     # tamanho do texto de apoio
COR_STORY_FUNDO = (0, 0, 0)
COR_STORY_BARRA = (255, 255, 255)
COR_STORY_TITULO = (255, 255, 255)
COR_STORY_TEXTO = (175, 175, 175)
LOGO_ARQUIVO = Path(__file__).resolve().parent / "logo.png"   # opcional
# Feed (post do Instagram, até 5 imagens em carrossel)
FEED_W, FEED_H = 1080, 1350          # 4:5. Para quadrado, use 1080, 1080
FEED_MAX = 5
COR_FEED_FUNDO = (237, 237, 237)     # cinza claro
COR_FEED_SELO_TEXTO = (90, 90, 90)
COR_FEED_TEXTO = (17, 17, 17)        # texto do post: preto
COR_LARANJA_PADRAO = (242, 101, 34)  # usada se não houver logo.png para tirar a cor
QUALIDADE_JPG = 95
# ======================================================================

_HOME_FONTES = str(Path.home() / ".fonts")
_PASTA_FONTES = str(Path(__file__).resolve().parent / "fontes")
# Textos em Segoe UI (Windows). No GitHub, usa a Selawik, versão aberta da
# própria Microsoft com as mesmas medidas da Segoe UI.
FONTES = [
    "C:/Windows/Fonts/segoeuib.ttf",
    f"{_PASTA_FONTES}/segoeuib.ttf",
    f"{_HOME_FONTES}/selawkb.ttf",
    f"{_PASTA_FONTES}/selawkb.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/msttcorefonts/Arial_Bold.ttf",   # servidor Linux
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]
ABERTOS = []  # clipes que usam o FFmpeg; são fechados no final
SESSAO = requests.Session()
SESSAO.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) BomDiaVarejo/1.0"})
SESSAO.mount("https://", requests.adapters.HTTPAdapter(max_retries=requests.adapters.Retry(
    total=4, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"])))


# ------------------------------ ENTRADA -------------------------------
OPCOES_COM_VALOR = ("--categoria", "--saida", "--foto")


def opcao(nome):
    """Valor de uma opção da linha de comando, ex.: --saida pasta."""
    if nome in sys.argv:
        i = sys.argv.index(nome)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None


def posicionais():
    resto, pular = [], False
    for a in sys.argv[1:]:
        if pular:
            pular = False
        elif a in OPCOES_COM_VALOR:
            pular = True
        elif not a.startswith("--"):
            resto.append(a)
    return resto


SEM_JANELA = opcao("--saida") is not None   # modo servidor


_RTF_DESTINOS = frozenset((
    "aftncn aftnsep aftnsepc annotation atnauthor atndate atnicn atnid atnparent atnref "
    "atntime atrfend atrfstart author background bkmkend bkmkstart blipuid buptim category "
    "colorschememapping colortbl comment company creatim datafield datastore defchp defpap do "
    "doccomm docvar dptxbxtext ebcend ebcstart expandedcolortbl factoidname falt fchars "
    "ffdeftext ffentrymcr ffexitmcr ffformat ffhelptext ffl ffname ffstattext field file "
    "filetbl fldinst fldtype fname fontemb fontfile fonttbl footer footerf footerl footerr "
    "footnote formfield ftncn ftnsep ftnsepc g generator gridtbl header headerf headerl "
    "headerr hl hlfr hlinkbase hlloc hlsrc hsv htmltag info keycode keywords latentstyles "
    "lchars levelnumbers leveltext lfolevel linkval list listlevel listname listoverride "
    "listoverridetable listpicture liststylename listtable listtext lsdlockedexcept "
    "mailmerge manager nesttableprops nextfile nonesttables objalias objclass objdata object "
    "objname objsect objtime oldcprops oldpprops oldsprops oldtprops oleclsid operator "
    "panose password passwordhash pgp pgptbl picprop pict pn pnseclvl pntext pntxta pntxtb "
    "printim private propname protend protstart protusertbl pxe result revtbl revtim "
    "rsidtbl rxe shp shpgrp shpinst shppict shprslt shptxt sn sp staticval stylesheet "
    "subject sv svb tc template themedata title txe ud upr userprops wgrffmtfilter "
    "windowcaption writereservation writereservhash xe xform xmlattrname xmlattrvalue "
    "xmlclose xmlname xmlnstbl xmlopen").split())
_RTF_ESPECIAIS = {"par": "\n", "sect": "\n\n", "page": "\n\n", "line": "\n", "tab": "\t",
                  "emdash": "\u2014", "endash": "\u2013", "bullet": "\u2022",
                  "lquote": "\u2018", "rquote": "\u2019",
                  "ldblquote": "\u201c", "rdblquote": "\u201d"}


def rtf_para_texto(rtf):
    """Converte RTF (texto com formatação, como o iPhone às vezes copia) em texto puro."""
    padrao = re.compile(r"\\([a-z]{1,32})(-?\d{1,10})?[ ]?|\\'([0-9a-f]{2})|\\([^a-z])|([{}])|[\r\n]+|(.)",
                        re.I | re.S)
    pilha, ignorar, ucskip, pular, saida = [], False, 1, 0, []
    for m in padrao.finditer(rtf):
        palavra, arg, hexa, char, chave, letra = m.groups()
        if chave:
            pular = 0
            if chave == "{":
                pilha.append((ucskip, ignorar))
            elif pilha:
                ucskip, ignorar = pilha.pop()
        elif char:
            pular = 0
            if char == "*":
                ignorar = True
            elif not ignorar:
                if char == "~":
                    saida.append("\u00a0")
                elif char in "{}\\":
                    saida.append(char)
                elif char in "\r\n":
                    saida.append("\n")
        elif palavra:
            pular = 0
            if palavra in _RTF_DESTINOS:
                ignorar = True
            elif ignorar:
                continue
            elif palavra in _RTF_ESPECIAIS:
                saida.append(_RTF_ESPECIAIS[palavra])
            elif palavra == "uc":
                ucskip = int(arg or 1)
            elif palavra == "u":
                c = int(arg)
                saida.append(chr(c + 0x10000 if c < 0 else c))
                pular = ucskip
        elif hexa:
            if pular > 0:
                pular -= 1
            elif not ignorar:
                saida.append(bytes([int(hexa, 16)]).decode("cp1252", errors="replace"))
        elif letra:
            if pular > 0:
                pular -= 1
            elif not ignorar:
                saida.append(letra)
    texto = "".join(saida)
    return texto.encode("utf-16", "surrogatepass").decode("utf-16", errors="replace")


def carregar_json(texto):
    """Lê o JSON tolerando aspas "inteligentes" (“ ” ‘ ’) que o iPhone às vezes
    coloca. Se mesmo assim falhar, mostra o começo do texto recebido no log."""
    if texto.lstrip().startswith("{\\rtf"):
        print("Aviso: o JSON veio com formatação (RTF); convertendo para texto puro.")
        texto = rtf_para_texto(texto).strip()
    try:
        return json.loads(texto)
    except json.JSONDecodeError as erro:
        corrigido = (texto.replace("\u201c", '"').replace("\u201d", '"')
                     .replace("\u201e", '"').replace("\u00ab", '"').replace("\u00bb", '"')
                     .replace("\u2018", "'").replace("\u2019", "'").replace("\u00a0", " "))
        try:
            dados = json.loads(corrigido)
            print("Aviso: o JSON veio com aspas curvas; corrigido automaticamente.")
            return dados
        except json.JSONDecodeError:
            pass
        raise SystemExit(
            f"JSON inválido ({erro}).\nComeço do que chegou: {texto[:300]!r}\n"
            f"Fim do que chegou: {texto[-150:]!r}\nTamanho: {len(texto)} caracteres")


def ler_roteiro():
    arquivos = posicionais()
    if arquivos:
        texto = Path(arquivos[0]).read_text(encoding="utf-8-sig")
        texto = re.sub(r"^\s*```(?:json)?\s*$", "", texto, flags=re.M).strip()
        return carregar_json(texto)

    print("Cole o JSON do roteiro e pressione Enter "
          "(o script continua sozinho quando o JSON estiver completo):\n")
    linhas = []
    while True:
        try:
            linhas.append(input())
        except EOFError:
            break
        texto = "\n".join(linhas)
        texto = re.sub(r"^\s*```(?:json)?\s*$", "", texto, flags=re.M).strip()
        if texto.startswith("{"):
            try:
                return json.loads(texto)
            except json.JSONDecodeError:
                continue
    raise SystemExit("Não foi possível ler o JSON. Confira se ele foi copiado inteiro.")


def juntar_cenas_curtas(cenas):
    """Junta cenas com pouca fala à cena seguinte, para não aparecer uma imagem
    piscando por menos de um segundo."""
    resultado, pendente = [], None
    for cena in cenas:
        if pendente:
            cena = {**cena,
                    "narracao": f"{pendente['narracao']} {cena['narracao']}",
                    "texto_tela": cena.get("texto_tela") or pendente.get("texto_tela", ""),
                    "fonte": cena.get("fonte") or pendente.get("fonte")}
            pendente = None
        curta = len(cena["narracao"].split()) < MIN_PALAVRAS_CENA
        if curta and not eh_cena_fixa(cena) and cena is not cenas[-1]:
            pendente = cena
            continue
        resultado.append(cena)
    if pendente:  # sobrou uma cena curta no fim: junta à anterior
        if resultado and not eh_cena_fixa(resultado[-1]):
            ant = resultado[-1]
            ant["narracao"] = f"{ant['narracao']} {pendente['narracao']}"
        else:
            resultado.append(pendente)
    juntadas = len(cenas) - len(resultado)
    if juntadas:
        print(f"{juntadas} cena(s) curta(s) juntada(s) à seguinte.")
    return resultado


def validar(roteiro):
    if not roteiro.get("cenas"):
        raise SystemExit("O JSON não tem a lista 'cenas'.")
    for i, c in enumerate(roteiro["cenas"], 1):
        if not c.get("narracao"):
            raise SystemExit(f"A cena {i} está sem 'narracao'.")
    roteiro.setdefault("data", "sem-data")
    roteiro["voz"] = VOZ_PADRAO  # a voz é sempre a da configuração do script


def conferir_voz(voz):
    """Confere se a voz existe no serviço; se não, mostra as opções e usa a padrão."""
    async def listar():
        return {v["ShortName"]: v.get("Locale", "") for v in await edge_tts.list_voices()}
    try:
        vozes = asyncio.run(listar())
    except Exception as e:
        print(f"Aviso: não consegui listar as vozes ({e}). Tentando usar {voz} assim mesmo.")
        return voz
    if voz in vozes:
        print(f"Voz: {voz}")
        return voz
    pt = sorted(n for n, loc in vozes.items() if loc == "pt-BR")
    multi = sorted(n for n in vozes if "Multilingual" in n)
    print(f"\nA voz '{voz}' não existe no serviço usado pelo script.")
    print("Vozes pt-BR disponíveis: " + ", ".join(pt))
    if multi:
        print("Vozes multilíngues (falam português com sotaque estrangeiro): " + ", ".join(multi))
    reserva = "pt-BR-AntonioNeural" if "pt-BR-AntonioNeural" in vozes else (pt[0] if pt else voz)
    print(f"Usando {reserva} neste vídeo.\n")
    return reserva


# ------------------------------- TEXTO --------------------------------
FONTES_SERIFA = [
    "C:/Windows/Fonts/georgiab.ttf",
    "C:/Windows/Fonts/timesbd.ttf",
    "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
    "/usr/share/fonts/truetype/msttcorefonts/Georgia_Bold.ttf",  # servidor Linux
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
]


FONTES_REGULAR = [
    "C:/Windows/Fonts/segoeui.ttf",
    f"{_PASTA_FONTES}/segoeui.ttf",
    f"{_HOME_FONTES}/selawk.ttf",
    f"{_PASTA_FONTES}/selawk.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/msttcorefonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]

# Só os títulos (título do story e caixa de destaque do vídeo):
# News Gothic MT Bold (vem com o Office).
# No GitHub ela não existe; usa a News Cycle Bold, versão gratuita inspirada nela.
FAMILIAS_TITULO = []  # vazio = Arial Bold. Ex.: [("News Gothic MT", "Bold")]
PASTAS_DE_FONTES = [Path(__file__).resolve().parent / "fontes",
                    Path("C:/Windows/Fonts"), Path.home() / ".fonts",
                    Path.home() / ".local/share/fonts", Path.home() / "Library/Fonts",
                    Path("/Library/Fonts"), Path("/usr/share/fonts")]
if os.getenv("LOCALAPPDATA"):
    PASTAS_DE_FONTES.insert(2, Path(os.environ["LOCALAPPDATA"]) / "Microsoft/Windows/Fonts")
_FONTES_ACHADAS = {}


def achar_fonte_por_nome(familia, estilo):
    """Procura uma fonte instalada pelo nome (ex.: 'News Gothic MT', 'Bold')."""
    chave = (familia.lower(), estilo.lower())
    if chave not in _FONTES_ACHADAS:
        achada = None
        for pasta in PASTAS_DE_FONTES:
            if achada or not pasta.is_dir():
                continue
            for arq in pasta.rglob("*"):
                if arq.suffix.lower() not in (".ttf", ".otf"):
                    continue
                try:
                    nome, tipo = ImageFont.truetype(str(arq), 10).getname()
                except Exception:
                    continue
                if (nome or "").lower() == chave[0] and (tipo or "").lower() == chave[1]:
                    achada = str(arq)
                    break
        _FONTES_ACHADAS[chave] = achada
    return _FONTES_ACHADAS[chave]


def _troca_glifos(texto, font):
    """A Selawik (Segoe UI do GitHub) não tem º nem ª: troca por ° e a."""
    caminho = os.path.basename(str(getattr(font, "path", "") or "")).lower()
    if isinstance(texto, str) and caminho.startswith("selawk"):
        return texto.replace("º", "°").replace("ª", "a")
    return texto


_texto_original = ImageDraw.ImageDraw.text
_largura_original = ImageDraw.ImageDraw.textlength


def _text(self, xy, text, *args, font=None, **kwargs):
    return _texto_original(self, xy, _troca_glifos(text, font), *args, font=font, **kwargs)


def _textlength(self, text, font=None, *args, **kwargs):
    return _largura_original(self, _troca_glifos(text, font), font, *args, **kwargs)


ImageDraw.ImageDraw.text = _text
ImageDraw.ImageDraw.textlength = _textlength


FONTES_SEMIBOLD = [
    "C:/Windows/Fonts/seguisb.ttf",
    f"{_PASTA_FONTES}/seguisb.ttf",
    f"{_HOME_FONTES}/selawksb.ttf",
    f"{_PASTA_FONTES}/selawksb.ttf",
]


def fonte_semibold(tamanho):
    for caminho in FONTES_SEMIBOLD:
        if os.path.exists(caminho):
            return ImageFont.truetype(caminho, tamanho)
    return fonte(tamanho)


def fonte_regular(tamanho):
    for caminho in FONTES_REGULAR:
        if os.path.exists(caminho):
            return ImageFont.truetype(caminho, tamanho)
    return fonte(tamanho)


def fonte_titulo(tamanho):
    for familia, estilo in FAMILIAS_TITULO:
        caminho = achar_fonte_por_nome(familia, estilo)
        if caminho:
            return ImageFont.truetype(caminho, tamanho)
    return fonte(tamanho)


def fonte(tamanho, serifa=False):
    for caminho in (FONTES_SERIFA if serifa else []) + FONTES:
        if os.path.exists(caminho):
            return ImageFont.truetype(caminho, tamanho)
    return ImageFont.load_default(size=tamanho)


def quebrar_linhas(texto, font, largura_max, draw):
    linhas, atual = [], ""
    for palavra in texto.split():
        teste = f"{atual} {palavra}".strip()
        if draw.textlength(teste, font=font) <= largura_max or not atual:
            atual = teste
        else:
            linhas.append(atual)
            atual = palavra
    if atual:
        linhas.append(atual)
    return linhas


def imagem_texto(texto, tamanho, cor=(255, 255, 255), fundo=None, serifa=False, titulo=False,
                 largura_max=W - 160, contorno=6, margem=28):
    font = fonte_titulo(tamanho) if titulo else fonte(tamanho, serifa)
    rascunho = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    linhas = quebrar_linhas(texto, font, largura_max - 2 * margem, rascunho)
    ascendente, descendente = font.getmetrics()
    alt_linha = ascendente + descendente
    espaco = int(tamanho * 0.12)
    largura = max(rascunho.textlength(l, font=font) for l in linhas)
    iw = int(largura + 2 * (margem + contorno))
    ih = int(len(linhas) * alt_linha + (len(linhas) - 1) * espaco + 2 * (margem + contorno))

    img = Image.new("RGBA", (iw, ih), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if fundo:
        d.rounded_rectangle([0, 0, iw - 1, ih - 1], radius=24, fill=fundo)
    y = margem + contorno
    for linha in linhas:
        x = (iw - d.textlength(linha, font=font)) / 2
        d.text((x, y), linha, font=font, fill=cor,
               stroke_width=0 if fundo else contorno, stroke_fill=(0, 0, 0))
        y += alt_linha + espaco
    return img


def clip_imagem(img, duracao, posicao, inicio=0.0):
    return (ImageClip(np.array(img), transparent=True)
            .with_duration(duracao).with_start(inicio).with_position(posicao))


# ------------------------------ NARRAÇÃO ------------------------------
async def _narrar(texto, voz, caminho):
    try:
        com = edge_tts.Communicate(texto, voz, rate=VELOCIDADE, pitch=TOM,
                                   boundary="WordBoundary")
    except TypeError:  # versões antigas do edge-tts
        com = edge_tts.Communicate(texto, voz, rate=VELOCIDADE, pitch=TOM)
    palavras = []
    with open(caminho, "wb") as f:
        async for parte in com.stream():
            if parte["type"] == "audio":
                f.write(parte["data"])
            elif parte["type"] == "WordBoundary":
                ini = parte["offset"] / 1e7
                palavras.append((ini, ini + parte["duration"] / 1e7, parte["text"]))
    return palavras


def narrar(texto, voz, caminho):
    return asyncio.run(_narrar(texto, voz, caminho))


def blocos_legenda(palavras, texto, duracao, max_palavras=3):
    if not palavras:  # sem marcação de tempo: distribui pelo tamanho das palavras
        lista = texto.split()
        total = sum(len(p) + 1 for p in lista)
        t = 0.0
        for p in lista:
            d = duracao * (len(p) + 1) / total
            palavras.append((t, t + d, p))
            t += d

    blocos = [palavras[i:i + max_palavras] for i in range(0, len(palavras), max_palavras)]
    resultado = []
    for i, bloco in enumerate(blocos):
        ini = bloco[0][0]
        fim = blocos[i + 1][0][0] if i + 1 < len(blocos) else duracao
        resultado.append((ini, max(fim, ini + 0.2), " ".join(p[2] for p in bloco)))
    return resultado


# ------------------------------- PEXELS -------------------------------
def baixar(url, destino, tentativas=4):
    if destino.exists() and destino.stat().st_size > 0:
        return destino
    parcial = destino.with_suffix(destino.suffix + ".part")
    for n in range(1, tentativas + 1):
        try:
            with SESSAO.get(url, stream=True, timeout=(15, 60)) as r:
                r.raise_for_status()
                with open(parcial, "wb") as f:
                    for pedaco in r.iter_content(256 * 1024):
                        f.write(pedaco)
            parcial.replace(destino)
            return destino
        except Exception as e:
            parcial.unlink(missing_ok=True)
            if n == tentativas:
                raise
            print(f"   conexão caiu, tentando de novo ({n}/{tentativas - 1})...")
            time.sleep(2 * n)


def pegar_json(url, params, cab=None):
    r = SESSAO.get(url, params=params, headers=cab, timeout=(15, 30))
    r.raise_for_status()
    return r.json()


# Palavras que indicam imagem fora do tema (descartadas sempre)
PROIBIDAS = {
    "dance", "dancing", "dancer", "party", "club", "disco", "concert", "music",
    "fashion", "model", "sexy", "bikini", "beach", "wedding", "love", "couple",
    "kiss", "halloween", "christmas", "santa", "horror", "ghost", "zombie",
    "fantasy", "anime", "cartoon", "game", "gaming", "fitness", "yoga", "gym",
    "sport", "football", "soccer", "night", "dark", "nightlife", "neon", "fireworks",
    "house", "home", "bedroom", "religion", "church", "war", "weapon", "gun",
    "blood", "smoke", "drink", "alcohol", "beer", "wine", "selfie", "portrait",
    "girl", "boy", "baby", "kids", "children",
    # imagens com texto, montagens e ilustrações (baixa qualidade no vídeo)
    "greeting", "greetings", "text", "lettering", "typography", "quote", "quotes",
    "words", "message", "font", "illustration", "vector", "drawing", "clipart",
    "clip-art", "animation", "animated", "3d", "render", "wallpaper", "emoji",
    "logo", "banner", "poster", "frame", "heart", "hearts", "valentine",
}
# Palavras do universo do varejo/economia (dão pontos extras)
TEMA = {
    "supermarket", "grocery", "store", "shop", "shopping", "retail", "market",
    "shelf", "shelves", "aisle", "cart", "trolley", "basket", "cashier",
    "checkout", "warehouse", "wholesale", "logistics", "truck", "delivery",
    "boxes", "box", "pallet", "food", "fruit", "vegetables", "coffee", "rice",
    "beans", "meat", "milk", "bread", "price", "money", "coins", "cash",
    "finance", "economy", "business", "chart", "graph", "stock", "bank",
    "calculator", "receipt", "payment", "card", "agriculture", "farm",
    "harvest", "factory", "industry", "port", "container", "fuel", "office",
}
GENERICAS = ["supermarket aisle", "grocery store shelves",
             "warehouse boxes"]

# Abertura ("Bom dia, varejo!") e fechamento: imagens sorteadas a cada vídeo
BUSCAS_ABERTURA = ["sunrise", "morning sky", "sunrise city", "morning sun",
                   "sunrise clouds", "sunrise landscape"]
BUSCAS_FECHAMENTO = ["drinking coffee", "morning coffee", "coffee cup",
                     "coffee mug", "sunrise", "sunrise sky"]
# termos que deixam de ser proibidos nessas cenas (pessoa tomando café etc.)
LIBERAR_FIXAS = frozenset({"drink", "girl", "portrait", "home", "house"})


def _raiz(palavra):
    """Normaliza plural simples: stripes -> stripe, boxes -> box."""
    w = palavra.strip().lower()
    if len(w) > 4 and w.endswith("es") and w[-3] in "sxz":
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _palavras_tags(tags_texto):
    tags = [t.strip().lower() for t in tags_texto.split(",") if t.strip()]
    palavras = {_raiz(w) for t in tags for w in t.split()}
    palavras |= {_raiz(t.replace(" ", "")) for t in tags}  # "bar code" -> "barcode"
    return palavras


def pontuar(tags_texto, busca, liberar=frozenset()):
    """Nota de relevância de uma imagem para o termo de busca.
    As tags do Pixabay vêm em ordem de importância e as últimas costumam ser
    ruído ("fish, carp, ..., gum"). Por isso o termo inteiro precisa estar
    nas PRIMEIRAS tags:
      termo nas 1ª tag -> 10 | nas 2 primeiras -> 7 | nas 3 primeiras -> 4
      fora das 3 primeiras -> 0 (descartada) | termo proibido -> -1"""
    tags = [t.strip().lower() for t in tags_texto.split(",") if t.strip()]
    todas = _palavras_tags(tags_texto)
    if todas & {_raiz(p) for p in (PROIBIDAS - liberar)}:
        return -1
    termos = {_raiz(w) for w in busca.split()}
    for k, nota in ((1, 10), (2, 7), (3, 4)):
        if termos <= _palavras_tags(",".join(tags[:k])):
            return nota + min(2, len(todas & {_raiz(t) for t in TEMA}))
    return 0


# --------------------- CONTROLE DE REPETIÇÃO -------------------------
# Só vale durante a execução atual: nada é gravado em disco.
# "usados" guarda, para este vídeo:
#   - o id de cada imagem já escolhida;
#   - o autor de cada imagem (o mesmo autor costuma subir várias tomadas
#     quase iguais com ids diferentes);
#   - a "assinatura" das tags (vídeos com tags idênticas são quase sempre
#     a mesma filmagem).
def assinatura(tags_texto):
    return "tags:" + ",".join(sorted(t.strip() for t in tags_texto.lower().split(",") if t.strip()))


def ja_usado(usados, chave, autor=None, tags=None):
    if chave in usados:
        return True
    if autor and f"autor:{autor}" in usados:
        return True
    if tags and assinatura(tags) in usados:
        return True
    return False


def marcar(usados, chave, autor=None, tags=None):
    usados.add(chave)
    if autor:
        usados.add(f"autor:{autor}")
    if tags:
        usados.add(assinatura(tags))


def variar(candidatos, folga=2):
    """Embaralha só os candidatos de nota próxima à melhor: mantém o foco no
    tema e faz cada execução escolher imagens diferentes, sem guardar histórico."""
    if not candidatos:
        return []
    melhor = max(n for n, _ in candidatos)
    bons = [c for c in candidatos if c[0] >= melhor - folga]
    resto = sorted((c for c in candidatos if c[0] < melhor - folga), key=lambda x: -x[0])
    random.shuffle(bons)
    return bons + resto


def tem_chave(chave):
    return bool(chave) and "COLE_SUA" not in chave


_CACHE_API = {}


def _pixabay(url, params):
    chave = (url, tuple(sorted(params.items())))
    if chave not in _CACHE_API:
        _CACHE_API[chave] = pegar_json(url, params).get("hits", [])
    return _CACHE_API[chave]


def buscar_pixabay(busca, usados, pasta, liberar=frozenset(), sortear=False, fotos_ok=False,
                   estrito=False, so_fotos=False):
    """Busca vídeos E fotos do termo e escolhe o mais fiel ao tema.
    Vídeo só ganha da foto quando a relevância é igual."""
    if fotos_ok:  # a foto já é avaliada junto com o vídeo, na mesma chamada
        return None
    base = {"key": PIXABAY_API_KEY, "q": busca, "safesearch": "true",
            "per_page": 50, "order": "popular"}
    minimo = 4

    candidatos = []
    videos = [] if so_fotos else _pixabay("https://pixabay.com/api/videos/",
                                          {**base, "video_type": "film"})
    for h in videos:
        chave, tags = f"pixabay_v{h['id']}", h.get("tags", "")
        if ja_usado(usados, chave, h.get("user_id"), tags):
            continue
        nota = pontuar(tags, busca, liberar)
        if nota < minimo:
            continue
        arquivos = [a for a in h["videos"].values()
                    if a.get("url") and min(a.get("width", 0), a.get("height", 0)) >= 720]
        if not arquivos:
            continue
        escolhido = min(arquivos, key=lambda a: abs(max(a["width"], a["height"]) - 1280))
        vertical = escolhido["height"] >= escolhido["width"]
        candidatos.append((nota + 0.5 + (0.5 if vertical else 0),
                           ("video", escolhido["url"], chave, h)))

    for h in _pixabay("https://pixabay.com/api/", {**base, "image_type": "photo",
                                                    "orientation": "vertical"}):
        chave, tags = f"pixabay_f{h['id']}", h.get("tags", "")
        if ja_usado(usados, chave, h.get("user_id"), tags):
            continue
        nota = pontuar(tags, busca, liberar)
        if nota < minimo or h.get("imageHeight", 0) < 1600:  # evita fotos pequenas
            continue
        candidatos.append((nota, ("foto", h["largeImageURL"], chave, h)))

    for _, (tipo, url, chave, h) in variar(candidatos, folga=2 if sortear else 1):
        ext = "mp4" if tipo == "video" else "jpg"
        try:
            midia = tipo, baixar(url, pasta / f"{chave}.{ext}")
            marcar(usados, chave, h.get("user_id"), h.get("tags", ""))
            return midia
        except Exception as e:
            usados.add(chave)
            print(f"   {tipo} {h['id']} não baixou ({type(e).__name__}); tentando outro...")
    return None


def buscar_pexels(busca, usados, pasta, liberar=frozenset(), sortear=False, fotos_ok=False,
                  estrito=False, so_fotos=False):
    if fotos_ok:
        return None
    cab = {"Authorization": PEXELS_API_KEY}
    if so_fotos:
        dados = pegar_json("https://api.pexels.com/v1/search",
                           {"query": busca, "orientation": "portrait", "per_page": 30}, cab)
        fotos = [f for f in dados.get("photos", [])
                 if not ja_usado(usados, f"pexels_f{f['id']}", f.get("photographer_id"))
                 and f.get("height", 0) >= 1600]
        random.shuffle(fotos)
        for f in fotos:
            chave = f"pexels_f{f['id']}"
            try:
                midia = "foto", baixar(f["src"]["large2x"], pasta / f"{chave}.jpg")
                marcar(usados, chave, f.get("photographer_id"))
                return midia
            except Exception as e:
                usados.add(chave)
                print(f"   foto {f['id']} não baixou ({type(e).__name__}); tentando outra...")
        return None
    dados = pegar_json("https://api.pexels.com/videos/search",
                       {"query": busca, "orientation": "portrait", "per_page": 30}, cab)
    videos = [v for v in dados.get("videos", [])
              if not ja_usado(usados, f"pexels_v{v['id']}", (v.get("user") or {}).get("id"))]
    random.shuffle(videos)
    for v in videos:
        arquivos = [a for a in v.get("video_files", [])
                    if a.get("width") and a.get("height")
                    and a["height"] >= a["width"] and a["height"] >= 1280]
        if not arquivos:
            continue
        escolhido = min(arquivos, key=lambda a: abs(a["height"] - 1920))
        chave = f"pexels_v{v['id']}"
        try:
            midia = "video", baixar(escolhido["link"], pasta / f"{chave}.mp4")
            marcar(usados, chave, (v.get("user") or {}).get("id"))
            return midia
        except Exception as e:
            usados.add(chave)
            print(f"   vídeo {v['id']} não baixou ({type(e).__name__}); tentando outro...")
    return None


def buscar_midia(buscas, usados, pasta, liberar=frozenset(), sortear=False, genericas=True,
                 reforco=None, so_fotos=False):
    """reforco: termos extras do mesmo tema (usados no gancho), tentados antes
    das imagens genéricas e com filtro estrito."""
    if isinstance(buscas, str):
        buscas = [buscas]
    especificas = [b for b in (buscas or []) if b]
    gerais = GENERICAS if genericas else []
    fontes = []
    if tem_chave(PIXABAY_API_KEY):
        fontes.append(("Pixabay", buscar_pixabay))
    if tem_chave(PEXELS_API_KEY):
        fontes.append(("Pexels", buscar_pexels))

    # Ordem: cada termo da cena (vídeo, depois foto), do mais específico ao
    # mais genérico; no gancho, depois os termos da notícia; por último,
    # as imagens genéricas de varejo.
    tema = list(especificas)
    if reforco:
        tema += [b for b in reforco if b and b not in tema]
    if so_fotos:  # stories: uma rodada por termo, só fotos
        rodadas = [([t], False, True) for t in tema] + [(gerais, False, True)]
    else:
        rodadas = [([t], fotos, True) for t in tema for fotos in (False, True)]
        rodadas += [(gerais, False, True), (gerais, True, True)]
    for termos, fotos_ok, estrito in rodadas:
        for busca in termos:
            for nome, funcao in fontes:
                try:
                    midia = funcao(busca, usados, pasta, liberar, sortear, fotos_ok, estrito,
                                   so_fotos=so_fotos)
                    if midia:
                        print(f"   imagem: '{busca}' ({nome}, {midia[0]})")
                        return midia
                except Exception as e:
                    print(f"   aviso: {nome} falhou para '{busca}': {e}")
    return None


# ------------------------------- CENAS --------------------------------
def cobrir_tela(clip):
    escala = max(W / clip.w, H / clip.h) * 1.002
    clip = clip.resized(escala)
    return clip.cropped(x1=int((clip.w - W) / 2), y1=int((clip.h - H) / 2), width=W, height=H)


def montar_fundo(midia, duracao):
    if midia and midia[0] == "video":
        try:
            original = VideoFileClip(str(midia[1]), audio=False)
            ABERTOS.append(original)
            c = cobrir_tela(original)
            if c.duration >= duracao:
                return c.subclipped(0, duracao)
            return c.with_effects([vfx.Loop(duration=duracao)])
        except Exception as e:
            print(f"   aviso: vídeo ignorado ({e})")
    if midia and midia[0] == "foto":
        try:
            img = cobrir_tela(ImageClip(str(midia[1])).with_duration(duracao))
            zoom = img.resized(lambda t: 1 + 0.06 * t / duracao)  # zoom lento
            return CompositeVideoClip([zoom.with_position("center")], size=(W, H)).with_duration(duracao)
        except Exception as e:
            print(f"   aviso: foto ignorada ({e})")
    return ColorClip((W, H), color=COR_MARCA).with_duration(duracao)


def eh_cena_fixa(cena):
    if cena.get("tipo") in ("abertura", "fechamento"):
        return True
    t = cena["narracao"].lower()
    return t.startswith("bom dia, varejo") or t.startswith("isso foi o bom dia")


def termos_da_noticia(roteiro, a_partir_de):
    """Termos de busca das cenas de notícia seguintes, para reforçar o gancho."""
    termos = []
    for c in roteiro["cenas"][a_partir_de:]:
        if eh_cena_fixa(c):
            continue
        b = c.get("busca_imagem") or []
        termos += [b] if isinstance(b, str) else list(b)[:1]
        if len(termos) >= 4:
            break
    return termos


def _norm(s):
    return re.sub(r"[^0-9a-zà-ÿ]", "", str(s).lower())


def tokens_da_narracao(narracao):
    """Separa a narração em palavras. Trechos entre **asteriscos** são destaque.
    Se a cena não tiver nenhum **, os números (47%, R$ 10, 2026) viram destaque."""
    tokens = []  # [texto, destaque]
    marcado = "**" in narracao
    for parte in re.split(r"(\*\*.+?\*\*)", narracao):
        if not parte:
            continue
        dest = parte.startswith("**") and parte.endswith("**") and len(parte) > 4
        txt = parte[2:-2] if dest else parte
        palavras = txt.split()
        if palavras and tokens and not txt[:1].isspace() and not dest and not _norm(palavras[0]):
            tokens[-1][0] += palavras.pop(0)  # pontuação colada ao destaque: "47%."
        for pw in palavras:
            hl = dest or (not marcado and bool(re.search(r"\d", pw)))
            tokens.append([pw, hl])
    return tokens


def tempos_das_palavras(tokens, marcas, duracao):
    """Casa as palavras da tela com as marcações de tempo da voz (WordBoundary)."""
    n = len(tokens)
    tempos = [None] * n
    k, sobra, ini_sobra = 0, 0, 0.0
    for j, (txt, _) in enumerate(tokens):
        alvo = len(_norm(txt))
        if not alvo:
            continue
        if sobra:
            tempos[j] = ini_sobra
            usado = min(sobra, alvo)
            sobra, alvo = sobra - usado, alvo - usado
        while alvo > 0 and k < len(marcas):
            L = len(_norm(marcas[k][2])) or 1
            if tempos[j] is None:
                tempos[j] = marcas[k][0]
            ini_sobra = marcas[k][0]
            k += 1
            if L >= alvo:
                sobra, alvo = L - alvo, 0
            else:
                alvo -= L
    # sem marcação (ou acabou): distribui pelo tamanho das palavras
    ultimo = max([i for i, x in enumerate(tempos) if x is not None], default=-1)
    if ultimo < n - 1:
        if ultimo >= 0:
            t0, acc = tempos[ultimo], len(tokens[ultimo][0]) + 1
        else:
            t0, acc = 0.0, 0
        total = acc + sum(len(x[0]) + 1 for x in tokens[ultimo + 1:])
        janela = max(0.5, duracao * 0.97 - t0)
        for i in range(ultimo + 1, n):
            tempos[i] = t0 + janela * acc / total
            acc += len(tokens[i][0]) + 1
    anterior = 0.0
    for i in range(n):  # garante ordem crescente
        if tempos[i] is None or tempos[i] < anterior:
            tempos[i] = anterior
        anterior = tempos[i]
    return tempos


def paginar(tokens, f_norm, f_dest, d):
    """Monta a coluna: quebra em linhas pela largura e em páginas pela altura.
    Cada frase começa numa página nova. Devolve [(índices, [(i, x, linha)])...]."""
    largura = W - 2 * X_TEXTO
    espaco = d.textlength(" ", font=f_norm)
    frases, atual = [], []
    for i, (txt, _) in enumerate(tokens):
        atual.append(i)
        if re.search(r"[.!?…]$", txt):
            frases.append(atual)
            atual = []
    if atual:
        frases.append(atual)

    paginas = []
    for frase in frases:
        linhas, linha, w = [], [], 0
        for i in frase:
            f = f_dest if tokens[i][1] else f_norm
            lw = d.textlength(tokens[i][0], font=f)
            if linha and w + espaco + lw > largura:
                linhas.append(linha)
                linha, w = [], 0
            linha.append((i, w if not linha else w + espaco))
            w = (w + espaco + lw) if len(linha) > 1 else lw
        if linha:
            linhas.append(linha)
        pagina, y = [], Y_TEXTO_INI
        for linha in linhas:
            maior = max(TAM_DESTAQUE if tokens[i][1] else TAM_PALAVRA for i, _ in linha)
            alt = int(maior * 1.2)
            if pagina and y + alt > Y_TEXTO_FIM:
                paginas.append(pagina)
                pagina, y = [], Y_TEXTO_INI
            base = y + int(maior * 0.95)  # linha de base comum para tamanhos diferentes
            pagina += [(i, X_TEXTO + x, base) for i, x in linha]
            y += alt
        if pagina:
            paginas.append(pagina)
    return paginas


def imagem_palavra(texto, font, cor):
    """Uma palavra com sombra suave. Devolve (imagem, deslocamento da linha de base)."""
    sobe, desce = font.getmetrics()
    pad = 8
    larg = int(ImageDraw.Draw(Image.new("RGBA", (1, 1))).textlength(texto, font=font)) + 2 * pad
    img = Image.new("RGBA", (larg, sobe + desce + 2 * pad), (0, 0, 0, 0))
    sombra = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sombra).text((pad, pad + sobe + 3), texto, font=font, fill=(0, 0, 0, 170), anchor="ls")
    img.alpha_composite(sombra.filter(ImageFilter.GaussianBlur(4)))
    ImageDraw.Draw(img).text((pad, pad + sobe), texto, font=font, fill=cor, anchor="ls")
    return img, pad + sobe


def fundo_estatico(midia):
    """Foto fixa, desfocada de leve e bem escurecida sobre preto."""
    preto = Image.new("RGB", (W, H), (0, 0, 0))
    if midia:
        try:
            if midia[0] == "foto":
                img = Image.open(midia[1]).convert("RGB")
            else:
                clip = VideoFileClip(str(midia[1]), audio=False)
                img = Image.fromarray(clip.get_frame(min(1.0, clip.duration / 2)))
                clip.close()
            img = ImageOps.fit(img, (W, H), Image.LANCZOS)
            if DESFOQUE_FOTO:
                img = img.filter(ImageFilter.GaussianBlur(DESFOQUE_FOTO))
            preto = Image.blend(preto, img, OPACIDADE_FOTO)
        except Exception as e:
            print(f"   aviso: imagem ignorada ({e})")
    return preto


def chapeu(texto, laranja):
    """Etiqueta da cena: barra laranja + texto em caixa alta."""
    f = fonte(34)
    d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    larg = int(d.textlength(texto, font=f))
    img = Image.new("RGBA", (larg + 30, 50), (0, 0, 0, 0))
    dd = ImageDraw.Draw(img)
    dd.rectangle([0, 6, 7, 44], fill=laranja)
    dd.text((22, 25), texto, font=f, fill=laranja, anchor="lm")
    return img


def montar_cena(i, cena, roteiro, pasta, usados, laranja):
    narracao = cena["narracao"]
    print(f"-> Cena {i}: {narracao.replace('**', '')[:60]}...")
    caminho_audio = pasta / f"cena_{i:02d}.mp3"
    marcas = narrar(narracao.replace("**", ""), roteiro["voz"], caminho_audio)
    audio = AudioFileClip(str(caminho_audio))
    ABERTOS.append(audio)
    duracao = audio.duration + TRANSICAO + 0.1  # silêncio no fim cobre a fusão

    tipo = cena.get("tipo")
    if eh_cena_fixa(cena):
        fechamento = tipo == "fechamento" or narracao.lower().startswith("isso foi")
        buscas = list(BUSCAS_FECHAMENTO if fechamento else BUSCAS_ABERTURA)
        random.shuffle(buscas)
        midia = buscar_midia(buscas, usados, pasta, LIBERAR_FIXAS, sortear=True,
                             genericas=False, so_fotos=True)
    else:
        primeira = not any(not eh_cena_fixa(c) for c in roteiro["cenas"][:i - 1])
        reforco = termos_da_noticia(roteiro, i) if (tipo == "gancho" or primeira) else None
        midia = buscar_midia(cena.get("busca_imagem"), usados, pasta, reforco=reforco,
                             so_fotos=True)

    camadas = [ImageClip(np.array(fundo_estatico(midia))).with_duration(duracao)]

    if cena.get("texto_tela") and not eh_cena_fixa(cena):
        camadas.append(clip_imagem(chapeu(cena["texto_tela"].upper(), laranja), duracao,
                                   (X_TEXTO, Y_CHAPEU)))

    fonte_txt = cena.get("fonte") or roteiro.get("fonte")
    if fonte_txt and not eh_cena_fixa(cena):
        img_f, _ = imagem_palavra(fonte_txt, fonte_semibold(30), (165, 165, 165))
        camadas.append(clip_imagem(img_f, duracao, (X_TEXTO - 8, Y_FONTE_VIDEO)))

    # Legenda: cada palavra aparece quando é falada, montando a coluna de cima para baixo
    tokens = tokens_da_narracao(narracao)
    tempos = tempos_das_palavras(tokens, marcas, audio.duration)
    f_norm, f_dest = fonte_semibold(TAM_PALAVRA), fonte(TAM_DESTAQUE)
    d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    paginas = paginar(tokens, f_norm, f_dest, d)
    for p, pagina in enumerate(paginas):
        fim_pag = tempos[paginas[p + 1][0][0]] if p + 1 < len(paginas) else duracao
        for idx, x, base in pagina:
            txt, hl = tokens[idx]
            img, desloc = imagem_palavra(txt, f_dest if hl else f_norm,
                                         laranja if hl else (255, 255, 255))
            ini_w = min(tempos[idx], fim_pag - 0.15)
            y = base - desloc

            def pos(tt, x=x - 8, y=y):  # sobe 14 px enquanto aparece
                return (x, y + 14 * max(0.0, 1 - tt / 0.16))
            c = (ImageClip(np.array(img), transparent=True)
                 .with_start(ini_w).with_duration(max(0.15, fim_pag - ini_w))
                 .with_position(pos).with_effects([vfx.CrossFadeIn(0.14)]))
            camadas.append(c)

    return CompositeVideoClip(camadas, size=(W, H)).with_duration(duracao).with_audio(audio)


def _data_extenso(data):
    meses = ["JANEIRO", "FEVEREIRO", "MARÇO", "ABRIL", "MAIO", "JUNHO", "JULHO",
             "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO"]
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(data or ""))
    return f"{int(m[3])} DE {meses[int(m[2]) - 1]} DE {m[1]}" if m else ""


def selo_video(laranja, data):
    """Selo do topo (igual ao do feed, em versão escura) + data por extenso."""
    alt = 104
    logo = _logo(alt - 24, cor_fundo=laranja)
    f1 = fonte(28)
    d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    larg_txt = max(d.textlength("Bom dia,", font=f1), d.textlength("Varejo", font=f1))
    larg = 12 + logo.width + 16 + int(larg_txt) + 30
    data_txt = _data_extenso(data)
    f2 = fonte_semibold(24)
    larg_total = max(larg, int(d.textlength(data_txt, font=f2)) + 4)
    img = Image.new("RGBA", (larg_total, alt + 54), (0, 0, 0, 0))
    dd = ImageDraw.Draw(img)
    x0 = (larg_total - larg) // 2
    dd.rounded_rectangle([x0, 0, x0 + larg, alt], radius=alt // 2, fill=(0, 0, 0, 110),
                         outline=(255, 255, 255, 70), width=2)
    img.alpha_composite(logo, (x0 + 12, 12))
    xt = x0 + 12 + logo.width + 16
    dd.text((xt, alt / 2 - 3), "Bom dia,", font=f1, fill=(255, 255, 255), anchor="ls")
    dd.text((xt, alt / 2 + 3), "Varejo", font=f1, fill=(255, 255, 255), anchor="lt")
    if data_txt:
        dd.text((larg_total / 2, alt + 34), data_txt, font=f2, fill=(170, 170, 170), anchor="mm")
    return img


def barra_progresso(duracao, laranja, largura=300, altura=4):
    """Barrinha laranja que enche ao longo do vídeo."""
    trilho = np.array([60, 60, 60], dtype=np.uint8)
    cheio = np.array(laranja, dtype=np.uint8)

    def quadro(tt):
        f = np.empty((altura, largura, 3), dtype=np.uint8)
        n = int(largura * min(1.0, tt / duracao))
        f[:, :n] = cheio
        f[:, n:] = trilho
        return f
    return VideoClip(frame_function=quadro, duration=duracao)


# ------------------------------- SAÍDA --------------------------------
def salvar_legendas(roteiro, caminho):
    partes = [f"TÍTULO: {roteiro.get('titulo', '')}", ""]
    for rede, texto in (roteiro.get("legendas") or {}).items():
        partes += [f"=== {rede.upper()} ===", texto, ""]
    caminho.write_text("\n".join(partes), encoding="utf-8")


CATEGORIAS = {"1": "noticia", "2": "curiosidade"}
APELIDOS = {"noticia": "noticia", "notícia": "noticia", "noticias": "noticia",
            "notícias": "noticia", "n": "noticia", "curiosidade": "curiosidade",
            "curiosidades": "curiosidade", "c": "curiosidade"}


def escolher_categoria(sugestao=None):
    """Pergunta no terminal se o conteúdo é notícia ou curiosidade."""
    padrao = APELIDOS.get(str(sugestao or "").strip().lower())
    forcada = APELIDOS.get(str(opcao("--categoria") or "").strip().lower())
    if forcada:
        return forcada
    if SEM_JANELA:
        return padrao or "noticia"
    dica = f" (Enter = {padrao})" if padrao else ""
    while True:
        try:
            r = input(f"\nTipo do conteúdo — [1] Notícia  [2] Curiosidade{dica}: ").strip().lower()
        except EOFError:
            r = ""
        if not r and padrao:
            return padrao
        escolha = CATEGORIAS.get(r) or APELIDOS.get(r)
        if escolha:
            return escolha
        print("Digite 1 para Notícia ou 2 para Curiosidade.")


def caminho_livre(caminho):
    """Se o arquivo já existe, acrescenta _2, _3... ao nome."""
    caminho = Path(caminho)
    n = 2
    novo = caminho
    while novo.exists():
        novo = caminho.with_name(f"{caminho.stem}_{n}{caminho.suffix}")
        n += 1
    return novo


def escolher_destino(nome, titulo="Salvar vídeo do Bom dia, Varejo", ext=".mp4",
                     tipos=(("Vídeo MP4", "*.mp4"),), pasta=None):
    if SEM_JANELA:  # servidor: salva direto na pasta indicada, sem sobrescrever
        destino = Path(opcao("--saida"))
        destino.mkdir(parents=True, exist_ok=True)
        return caminho_livre(destino / nome)
    import tkinter as tk
    from tkinter import filedialog
    pasta = pasta or PASTA_INICIAL
    inicial = pasta if pasta.exists() else Path.home()
    sugerido = caminho_livre(inicial / nome).name
    raiz = tk.Tk()
    raiz.withdraw()
    raiz.attributes("-topmost", True)
    caminho = filedialog.asksaveasfilename(
        parent=raiz, title=titulo, initialdir=str(inicial), initialfile=sugerido,
        defaultextension=ext, filetypes=list(tipos))
    raiz.destroy()
    if not caminho:
        raise SystemExit("Salvamento cancelado. Nenhum arquivo foi gerado.")
    return Path(caminho)


# ------------------------------ STORIES -------------------------------
def validar_stories(roteiro):
    stories = roteiro.get("stories")
    if not stories:  # aceita também um story único no próprio JSON
        if roteiro.get("texto_tela") or roteiro.get("texto_apoio") or roteiro.get("topicos"):
            stories = [roteiro]
        else:
            raise SystemExit("O JSON não tem a lista 'stories'.")
    for i, s in enumerate(stories, 1):
        if not (s.get("texto_tela") or s.get("texto_apoio") or s.get("topicos")):
            raise SystemExit(f"O story {i} está sem 'texto_tela', 'texto_apoio' e 'topicos'.")
    roteiro["stories"] = stories
    roteiro.setdefault("data", "sem-data")


def _logo(tamanho, cor_fundo=COR_STORY_FUNDO):
    """Logo redondo: usa logo.png (recortado em círculo) se existir; senão um selo "BV"."""
    escala = 4  # desenha maior e reduz, para a borda do círculo ficar lisa
    grande = tamanho * escala
    mascara = Image.new("L", (grande, grande), 0)
    ImageDraw.Draw(mascara).ellipse([0, 0, grande - 1, grande - 1], fill=255)
    if LOGO_ARQUIVO.exists():
        try:
            img = ImageOps.fit(Image.open(LOGO_ARQUIVO).convert("RGBA"), (grande, grande),
                               Image.LANCZOS)
            alfa = Image.composite(img.getchannel("A"), Image.new("L", img.size, 0), mascara)
            img.putalpha(alfa)
            return img.resize((tamanho, tamanho), Image.LANCZOS)
        except Exception as e:
            print(f"   aviso: logo.png ignorado ({e})")
    img = Image.new("RGBA", (grande, grande), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([0, 0, grande - 1, grande - 1], fill=cor_fundo)
    d.text((grande / 2, grande / 2), "BV", font=fonte(int(grande * 0.40)),
           fill=COR_STORY_BARRA, anchor="mm")
    return img.resize((tamanho, tamanho), Image.LANCZOS)


def _data_br(data):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(data or ""))
    return f"{m[3]}/{m[2]}/{m[1]}" if m else str(data or "")


def montar_story(item, roteiro):
    titulo = (item.get("texto_tela") or "").strip()
    apoio = (item.get("texto_apoio") or "").strip()
    topicos = [str(x).strip() for x in (item.get("topicos") or []) if str(x).strip()]
    print(f"-> Story: {(titulo or apoio or ' '.join(topicos))[:60]}...")

    tela = Image.new("RGB", (W, H), COR_STORY_FUNDO)
    d = ImageDraw.Draw(tela)

    # Barra branca abaixo da área dos indicadores do stories
    y0, y1 = STORY_TOPO_LIVRE, STORY_TOPO_LIVRE + STORY_ALT_BARRA
    d.rectangle([0, y0, W, y1], fill=COR_STORY_BARRA)
    logo = _logo(int(STORY_ALT_BARRA * 0.62))
    tela.paste(logo, (STORY_MARGEM - 12, y0 + (STORY_ALT_BARRA - logo.height) // 2), logo)
    d.text((W / 2, (y0 + y1) / 2), NOME_CANAL, font=fonte_regular(62),
           fill=COR_STORY_FUNDO, anchor="mm")

    # Texto da notícia, alinhado à esquerda como manchete de portal
    largura = W - 2 * STORY_MARGEM
    topo = y1 + 110
    limite = H - STORY_BASE_LIVRE
    rodape_txt = item.get("fonte") or roteiro.get("fonte") or "Por Bom dia, Varejo"
    data_txt = _data_br(item.get("data") or roteiro.get("data"))

    recuo = 46  # espaço entre a bolinha e o texto do tópico

    def bloco(tam_titulo, tam_texto):
        # cada linha: (texto, fonte, cor, x, altura_da_linha, bolinha?)
        linhas, altura = [], 0

        def add(lista, f, cor, alt, depois, x=STORY_MARGEM, bolinha=False):
            nonlocal altura
            for n, txt in enumerate(lista):
                linhas.append((txt, f, cor, x, altura, bolinha and n == 0))
                altura += alt
            altura += depois

        if titulo:
            ft = fonte_titulo(tam_titulo)
            add(quebrar_linhas(titulo, ft, largura, d), ft, COR_STORY_TITULO,
                int(tam_titulo * 1.12), int(tam_texto * 1.2))
        if apoio:
            fa = fonte_regular(tam_texto)
            add(quebrar_linhas(apoio, fa, largura, d), fa, COR_STORY_TEXTO,
                int(tam_texto * 1.38), int(tam_texto * 0.8))
        if topicos:
            fa = fonte_regular(tam_texto)
            for tp in topicos:
                add(quebrar_linhas(tp, fa, largura - recuo, d), fa, COR_STORY_TEXTO,
                    int(tam_texto * 1.32), int(tam_texto * 0.55),
                    x=STORY_MARGEM + recuo, bolinha=True)
        altura += int(tam_texto * 0.6)
        add([rodape_txt], fonte(int(tam_texto * 0.86)), COR_STORY_TEXTO,
            int(tam_texto * 1.25), 6)
        if data_txt:
            add([data_txt], fonte_regular(int(tam_texto * 0.78)), COR_STORY_TEXTO,
                int(tam_texto * 1.1), 0)
        return linhas, altura

    tam_t, tam_a = STORY_TITULO, STORY_TEXTO
    linhas, altura = bloco(tam_t, tam_a)
    while topo + altura > limite and tam_t > 60:  # texto longo: diminui até caber
        tam_t, tam_a = tam_t - 4, max(34, tam_a - 1)
        linhas, altura = bloco(tam_t, tam_a)

    for txt, f, cor, x, y, bolinha in linhas:
        if bolinha:
            r = max(6, int(f.size * 0.16))
            cy = topo + y + f.size * 0.58
            d.ellipse([STORY_MARGEM + 4, cy - r, STORY_MARGEM + 4 + 2 * r, cy + r],
                      fill=COR_STORY_TITULO)
        d.text((x, topo + y), txt, font=f, fill=cor)
    return tela


# -------------------------------- FEED --------------------------------
def cor_laranja():
    """Tira o laranja do logo.png; sem logo, usa COR_LARANJA_PADRAO."""
    import colorsys
    if LOGO_ARQUIVO.exists():
        try:
            img = Image.open(LOGO_ARQUIVO).convert("RGBA").resize((80, 80))
            soma, n = [0, 0, 0], 0
            for r, g, b, a in img.getdata():
                if a < 128:
                    continue
                h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
                if s > 0.45 and v > 0.45 and 0.02 <= h <= 0.13:
                    soma = [soma[0] + r, soma[1] + g, soma[2] + b]
                    n += 1
            if n > 30:
                return tuple(c // n for c in soma)
        except Exception as e:
            print(f"   aviso: não deu para ler a cor do logo ({e})")
    return COR_LARANJA_PADRAO


def _palavras(paragrafo):
    """Quebra o texto em palavras; **assim** vira negrito. Cada palavra é uma
    lista de pedaços (texto, negrito), para pontuação colar no negrito."""
    palavras, nova = [], True
    for parte in re.split(r"(\*\*.+?\*\*)", paragrafo):
        if not parte:
            continue
        negrito = len(parte) > 4 and parte.startswith("**") and parte.endswith("**")
        txt = parte[2:-2] if negrito else parte
        for i, pedaco in enumerate(txt.split(" ")):
            if i > 0:
                nova = True
            if not pedaco:
                continue
            if nova or not palavras:
                palavras.append([(pedaco, negrito)])
            else:
                palavras[-1].append((pedaco, negrito))
            nova = False
        if txt.endswith(" "):
            nova = True
    return palavras


def _linhas_ricas(texto, f_reg, f_neg, largura, d):
    def larg(palavra):
        return sum(d.textlength(tx, font=f_neg if ng else f_reg) for tx, ng in palavra)
    espaco = d.textlength(" ", font=f_reg)
    # não separa "2º turno", "1ª vez" etc. em linhas diferentes
    texto = re.sub(r"(\d+[ºª°])\s+", "\\1\u00a0", texto)
    linhas = []
    for paragrafo in texto.split("\n"):
        atual, w = [], 0
        for palavra in _palavras(paragrafo.strip()):
            lp = larg(palavra)
            if atual and w + espaco + lp > largura:
                linhas.append(atual)
                atual, w = [], 0
            w += (espaco if atual else 0) + lp
            atual.append(palavra)
        linhas.append(atual)
    return linhas, espaco


def _desenhar_linhas(d, linhas, espaco, x, y, alt, f_normal, f_dest, cor_normal, cor_dest,
                     largura=None):
    """Desenha linhas ricas. Trechos **marcados** usam f_dest/cor_dest.
    Se largura for dada, centraliza cada linha nela."""
    for linha in linhas:
        if largura:
            w = sum(d.textlength(tx, font=f_dest if ng else f_normal)
                    for palavra in linha for tx, ng in palavra) + espaco * max(0, len(linha) - 1)
            xl = x + (largura - w) / 2
        else:
            xl = x
        for n, palavra in enumerate(linha):
            if n:
                xl += espaco
            for tx, ng in palavra:
                f = f_dest if ng else f_normal
                d.text((xl, y), tx, font=f, fill=cor_dest if ng else cor_normal)
                xl += d.textlength(tx, font=f)
        y += alt
    return y


def _selo_feed(tela, d, laranja):
    """Selo no canto superior direito: logo redondo + nome, com contorno arredondado."""
    alt_selo, margem = 118, 64
    logo = _logo(alt_selo - 26, cor_fundo=laranja)
    f1 = fonte(30)
    nome1, nome2 = "Bom dia,", "Varejo"
    larg_txt = max(d.textlength(nome1, font=f1), d.textlength(nome2, font=f1))
    larg_selo = 13 + logo.width + 18 + int(larg_txt) + 30
    x0, y0 = FEED_W - margem - larg_selo, margem
    d.rounded_rectangle([x0, y0, x0 + larg_selo, y0 + alt_selo], radius=alt_selo // 2,
                        outline=(205, 205, 205), width=3)
    tela.paste(logo, (x0 + 13, y0 + 13), logo)
    xt = x0 + 13 + logo.width + 18
    d.text((xt, y0 + alt_selo / 2 - 4), nome1, font=f1, fill=COR_FEED_SELO_TEXTO, anchor="ls")
    d.text((xt, y0 + alt_selo / 2 + 4), nome2, font=f1, fill=COR_FEED_SELO_TEXTO, anchor="lt")
    return y0 + alt_selo


def baixar_imagem_url(url, pasta):
    """Baixa a imagem de um link. Aceita link direto da imagem, caminho de arquivo
    local, ou link de página (usa a imagem de compartilhamento og:image)."""
    url = str(url).strip()
    if os.path.exists(url):
        return "foto", Path(url)
    try:
        r = SESSAO.get(url, timeout=30)
        r.raise_for_status()
        tipo = r.headers.get("Content-Type", "")
        if "html" in tipo:
            m = (re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', r.text)
                 or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image', r.text))
            if not m:
                raise ValueError("a página não tem imagem de compartilhamento (og:image)")
            r = SESSAO.get(requests.compat.urljoin(url, m.group(1).replace("&amp;", "&")), timeout=30)
            r.raise_for_status()
        destino = pasta / f"capa_{random.randint(0, 10**9)}.img"
        destino.write_bytes(r.content)
        Image.open(destino).verify()  # garante que é mesmo uma imagem
        print("   imagem: link do JSON")
        return "foto", destino
    except Exception as e:
        print(f"   aviso: não deu para usar a imagem do link ({e}); buscando outra...")
        return None


def montar_capa(item, laranja, midia):
    """1ª imagem do carrossel: foto, degradê preto embaixo, manchete branca com
    trechos **em laranja**, subtítulo e 'arraste para o lado'."""
    titulo = (item.get("titulo") or item.get("texto") or "").strip()
    print(f"-> Capa: {titulo[:60]}...")
    if midia and midia[0] == "foto":
        fundo = ImageOps.fit(Image.open(midia[1]).convert("RGB"), (FEED_W, FEED_H),
                             Image.LANCZOS)
    else:
        fundo = Image.new("RGB", (FEED_W, FEED_H), (45, 45, 45))
    tela = fundo.convert("RGBA")

    # Degradê suave: começa em ~25% da altura sem "degrau" visível
    # (curva smoothstep) e chega quase a preto atrás do texto
    grad = Image.new("L", (1, FEED_H))
    ini_g, fim_g = FEED_H * 0.25, FEED_H * 0.92
    for y in range(FEED_H):
        p = min(1.0, max(0.0, (y - ini_g) / (fim_g - ini_g)))
        suave = p * p * p * (p * (p * 6 - 15) + 10)   # smootherstep
        grad.putpixel((0, y), int(245 * suave))
    sombra = Image.new("RGBA", (FEED_W, FEED_H), (0, 0, 0, 255))
    sombra.putalpha(grad.resize((FEED_W, FEED_H)))
    tela.alpha_composite(sombra)
    topo = Image.new("L", (1, 260))  # leve sombra no topo para o nome aparecer
    for y in range(260):
        topo.putpixel((0, y), int(110 * (1 - y / 260)))
    sombra_topo = Image.new("RGBA", (FEED_W, 260), (0, 0, 0, 255))
    sombra_topo.putalpha(topo.resize((FEED_W, 260)))
    tela.alpha_composite(sombra_topo, (0, 0))
    d = ImageDraw.Draw(tela)

    # Logo + nome, centralizados no topo
    logo = _logo(64, cor_fundo=laranja)
    fn = fonte(40)
    larg_nome = d.textlength("Bom dia, Varejo", font=fn)
    x = (FEED_W - (logo.width + 16 + larg_nome)) / 2
    tela.alpha_composite(logo, (int(x), 56))
    d.text((x + logo.width + 16, 56 + logo.height / 2), "Bom dia, Varejo", font=fn,
           fill=(255, 255, 255), anchor="lm")

    # De baixo para cima: seta, "arraste", subtítulo, manchete
    mx = 64
    largura = FEED_W - 2 * mx
    y_seta = FEED_H - 92
    d.line([(mx, y_seta), (FEED_W - mx, y_seta)], fill=(255, 255, 255), width=3)
    d.line([(FEED_W - mx - 18, y_seta - 12), (FEED_W - mx, y_seta)], fill=(255, 255, 255), width=3)
    d.line([(FEED_W - mx - 18, y_seta + 12), (FEED_W - mx, y_seta)], fill=(255, 255, 255), width=3)
    d.text((mx, y_seta + 22), "ARRASTE PARA O LADO", font=fonte(22), fill=(255, 255, 255))

    y_base = y_seta - 44
    sub = (item.get("subtitulo") or "").strip()
    if sub:
        fs = fonte_regular(36)
        linhas_s, esp_s = _linhas_ricas(sub, fs, fs, largura, d)
        alt_s = 46
        y_base -= len(linhas_s) * alt_s
        _desenhar_linhas(d, linhas_s, esp_s, mx, y_base, alt_s, fs, fs,
                         (255, 255, 255), (255, 255, 255), largura)
        y_base -= 36

    tam = 74
    while True:
        ft = fonte(tam)
        linhas, esp = _linhas_ricas(titulo, ft, ft, largura, d)
        alt = int(tam * 1.12)
        if len(linhas) <= 4 or tam <= 48:
            break
        tam -= 4
    _desenhar_linhas(d, linhas, esp, mx, y_base - len(linhas) * alt, alt, ft, ft,
                     (255, 255, 255), laranja, largura)
    return tela.convert("RGB")


def montar_feed(item, laranja):
    """Imagens 2 a 5: fundo cinza, selo, barra laranja; título, texto e/ou tópicos."""
    titulo = (item.get("titulo") or "").strip()
    texto = (item.get("texto") or item.get("texto_tela") or "").strip()
    topicos = [str(x).strip() for x in (item.get("topicos") or []) if str(x).strip()]
    print(f"-> Feed: {(titulo or texto or ' '.join(topicos))[:60]}...")
    tela = Image.new("RGB", (FEED_W, FEED_H), COR_FEED_FUNDO)
    d = ImageDraw.Draw(tela)
    fim_selo = _selo_feed(tela, d, laranja)

    alt_barra, larg_barra = 92, int(FEED_W * 0.56)
    d.polygon([(0, FEED_H - alt_barra), (larg_barra, FEED_H - alt_barra),
               (larg_barra + alt_barra, FEED_H), (0, FEED_H)], fill=laranja)

    x_txt, larg = 110, FEED_W - 110 - 90
    recuo = 40
    topo, base = fim_selo + 60, FEED_H - alt_barra - 70
    fonte_txt = (item.get("fonte") or "").strip()
    tam = 52  # menor que antes, para caber mais informação
    while True:
        tt = int(tam * 1.2)
        f_tit, f_reg, f_neg = fonte(tt), fonte_regular(tam), fonte(tam)
        blocos, altura = [], 0  # (tipo, linhas, espaço, altura_linha)
        if titulo:
            ls, es = _linhas_ricas(titulo, f_tit, f_tit, larg, d)
            blocos.append(("titulo", ls, es, int(tt * 1.15)))
            altura += len(ls) * int(tt * 1.15) + int(tam * 0.8)
        if texto:
            ls, es = _linhas_ricas(texto, f_reg, f_neg, larg, d)
            blocos.append(("texto", ls, es, int(tam * 1.3)))
            altura += len(ls) * int(tam * 1.3) + int(tam * 0.6)
        for tp in topicos:
            ls, es = _linhas_ricas(tp, f_reg, f_neg, larg - recuo, d)
            blocos.append(("topico", ls, es, int(tam * 1.28)))
            altura += len(ls) * int(tam * 1.28) + int(tam * 0.5)
        if fonte_txt:
            altura += int(tam * 1.3)
        if altura <= base - topo or tam <= 30:
            break
        tam -= 2

    y = topo + (base - topo - altura) // 2
    for tipo, ls, es, alt in blocos:
        if tipo == "titulo":
            y = _desenhar_linhas(d, ls, es, x_txt, y, alt, f_tit, f_tit,
                                 COR_FEED_TEXTO, laranja) + int(tam * 0.8)
        elif tipo == "texto":
            y = _desenhar_linhas(d, ls, es, x_txt, y, alt, f_reg, f_neg,
                                 COR_FEED_TEXTO, COR_FEED_TEXTO) + int(tam * 0.6)
        else:
            r = max(6, int(tam * 0.15))
            cy = y + tam * 0.58
            d.ellipse([x_txt + 2, cy - r, x_txt + 2 + 2 * r, cy + r], fill=laranja)
            y = _desenhar_linhas(d, ls, es, x_txt + recuo, y, alt, f_reg, f_neg,
                                 COR_FEED_TEXTO, COR_FEED_TEXTO) + int(tam * 0.5)
    if fonte_txt:
        d.text((x_txt, y + int(tam * 0.3)), fonte_txt, font=fonte_regular(int(tam * 0.5)),
               fill=(130, 130, 130))
    return tela


def gerar_feed(roteiro):
    capa = roteiro.get("capa")
    imagens = [i for i in (roteiro.get("imagens") or ([] if capa else [roteiro]))
               if (i.get("titulo") or i.get("texto") or i.get("texto_tela") or i.get("topicos"))]
    if not capa and not imagens:
        raise SystemExit("O JSON do feed não tem 'capa' nem 'imagens' com texto.")
    limite = FEED_MAX - (1 if capa else 0)
    if len(imagens) > limite:
        print(f"Aviso: o feed aceita até {FEED_MAX} imagens; o resto foi ignorado.")
        imagens = imagens[:limite]
    roteiro.setdefault("data", "sem-data")
    categoria = escolher_categoria(roteiro.get("categoria"))
    saida = escolher_destino(f"{roteiro['data']}_feed_{categoria}.jpg",
                             titulo="Salvar post do feed do Bom dia, Varejo", ext=".jpg",
                             tipos=(("Imagem JPG", "*.jpg"), ("Imagem PNG", "*.png")),
                             pasta=PASTA_INICIAL_STORIES)
    laranja = cor_laranja()
    pasta_tmp = Path(tempfile.mkdtemp(prefix="bom_dia_varejo_feed_"))
    figuras = []
    if capa:
        midia = None
        if opcao("--foto"):  # foto escolhida no iPhone tem prioridade sobre o link
            capa["imagem_url"] = opcao("--foto")
        if capa.get("imagem_url"):
            midia = baixar_imagem_url(capa["imagem_url"], pasta_tmp)
        if not midia and capa.get("busca_imagem"):
            midia = buscar_midia(capa["busca_imagem"], set(), pasta_tmp, so_fotos=True)
        figuras.append(montar_capa(capa, laranja, midia))
    figuras += [montar_feed(item, laranja) for item in imagens]

    salvos = []
    for i, img in enumerate(figuras, 1):
        destino = saida if len(figuras) == 1 else caminho_livre(
            saida.with_name(f"{saida.stem}_{i:02d}{saida.suffix}"))
        if destino.suffix.lower() == ".png":
            img.save(destino)
        else:
            img.save(destino, "JPEG", quality=QUALIDADE_JPG, optimize=True)
        salvos.append(destino)

    legenda = (roteiro.get("legenda") or "").strip()
    if legenda:  # vai para a descrição do post (e para as notas da release no GitHub)
        arq = caminho_livre(saida.with_name(f"{saida.stem}_legendas.txt"))
        arq.write_text(legenda + "\n", encoding="utf-8")
        salvos.append(arq)
    if APAGAR_TEMPORARIOS:
        shutil.rmtree(pasta_tmp, ignore_errors=True)
    print("\nPronto! " + "\n        ".join(str(s) for s in salvos))


def gerar_stories(roteiro):
    validar_stories(roteiro)
    stories = roteiro["stories"]
    if len(stories) > 1:
        print(f"Aviso: o JSON tem {len(stories)} stories; só o primeiro é gerado.")
    categoria = escolher_categoria(roteiro.get("categoria"))
    saida = escolher_destino(f"{roteiro['data']}_story_{categoria}.jpg",
                             titulo="Salvar story do Bom dia, Varejo", ext=".jpg",
                             tipos=(("Imagem JPG", "*.jpg"), ("Imagem PNG", "*.png")),
                             pasta=PASTA_INICIAL_STORIES)
    img = montar_story(stories[0], roteiro)
    if saida.suffix.lower() == ".png":
        img.save(saida)
    else:
        img.save(saida, "JPEG", quality=QUALIDADE_JPG, optimize=True)
    print(f"\nPronto! {saida}")


def testar_vozes():
    async def listar():
        return [v["ShortName"] for v in await edge_tts.list_voices()
                if v["Locale"] == "pt-BR"]
    vozes = asyncio.run(listar())
    print("Vozes pt-BR encontradas: " + ", ".join(vozes))
    pasta = Path(__file__).resolve().parent / "amostras_vozes"
    pasta.mkdir(exist_ok=True)
    frase = ("Bom dia, varejo! A inflação dos alimentos desacelerou em setembro, "
             "e isso pode aliviar o preço da cesta básica nas próximas semanas.")
    for voz in vozes:
        print(f"Gerando {voz}...")
        try:
            narrar(frase, voz, pasta / f"{voz}.mp3")
        except Exception as e:
            print(f"   falhou: {e}")
    print(f"\nAmostras salvas em: {pasta}")
    if os.name == "nt":
        os.startfile(pasta)


def main():
    if "--testar-vozes" in sys.argv:
        testar_vozes()
        return
    roteiro = ler_roteiro()
    if ("--feed" in sys.argv or roteiro.get("formato") == "feed" or "imagens" in roteiro
            or "capa" in roteiro):
        gerar_feed(roteiro)
        return
    if ("--story" in sys.argv or roteiro.get("formato") == "story"
            or "stories" in roteiro):
        gerar_stories(roteiro)
        return
    validar(roteiro)
    roteiro["cenas"] = juntar_cenas_curtas(roteiro["cenas"])

    roteiro["voz"] = conferir_voz(roteiro["voz"])
    data = roteiro["data"]
    categoria = escolher_categoria(roteiro.get("categoria"))
    saida = escolher_destino(f"{data}_bom-dia-varejo_{categoria}.mp4")
    pasta_tmp = Path(tempfile.mkdtemp(prefix="bom_dia_varejo_"))

    if not (tem_chave(PIXABAY_API_KEY) or tem_chave(PEXELS_API_KEY)):
        print("Aviso: sem chave do Pixabay, as cenas terão fundo liso.\n")

    laranja = cor_laranja()
    usados = set()
    cenas = [montar_cena(i, c, roteiro, pasta_tmp, usados, laranja)
             for i, c in enumerate(roteiro["cenas"], 1)]

    # fusão suave: cada cena começa um pouco antes do fim da anterior
    inicio, partes = 0.0, []
    for i, c in enumerate(cenas):
        if i > 0:
            c = c.with_effects([vfx.CrossFadeIn(TRANSICAO)])
        partes.append(c.with_start(inicio))
        inicio += c.duration - TRANSICAO
    total = inicio + TRANSICAO
    selo = selo_video(laranja, data)
    y_barra = Y_SELO_VIDEO + selo.height + 18
    video = CompositeVideoClip(
        partes + [clip_imagem(selo, total, ("center", Y_SELO_VIDEO)),
                  barra_progresso(total, laranja).with_position(("center", y_barra))],
        size=(W, H)).with_duration(total)
    musicas = sorted(p for p in PASTA_MUSICAS.glob("*")
                     if p.suffix.lower() in (".mp3", ".wav", ".m4a", ".ogg")) \
        if PASTA_MUSICAS.exists() else []
    if musicas:
        escolhida = random.choice(musicas)
        print(f"Música de fundo: {escolhida.name}")
        musica = AudioFileClip(str(escolhida))
        ABERTOS.append(musica)
        trilha = musica.with_effects([
            afx.AudioLoop(duration=video.duration),
            afx.MultiplyVolume(VOLUME_MUSICA),
            afx.AudioFadeIn(1.0),
            afx.AudioFadeOut(2.5),
        ])
        video = video.with_audio(CompositeAudioClip([video.audio, trilha]))
    else:
        print("Sem música de fundo (pasta 'musicas' vazia ou inexistente).")

    video.write_videofile(str(saida), fps=FPS, codec="libx264", audio_codec="aac",
                          preset="medium", threads=4,
                          temp_audiofile=str(pasta_tmp / "audio_temp.m4a"))
    salvar_legendas(roteiro, saida.with_name(f"{saida.stem}_legendas.txt"))

    for clip in [video, *cenas, *ABERTOS]:
        try:
            clip.close()
        except Exception:
            pass
    if APAGAR_TEMPORARIOS:
        shutil.rmtree(pasta_tmp, ignore_errors=True)

    print(f"\nPronto! {saida}  ({video.duration:.0f} s)")
    if video.duration < DURACAO_MINIMA:
        print(f"Atenção: o vídeo tem menos de {DURACAO_MINIMA} s e não monetiza no TikTok. "
              "Diminua VELOCIDADE (ex.: '+0%') ou peça um roteiro um pouco maior.")


if __name__ == "__main__":
    main()
